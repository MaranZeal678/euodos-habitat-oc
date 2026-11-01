"""Parking-lot segmentation CNN (compact U-Net) on 4-band NAIP + NDVI, weakly supervised by OSM polygons.

Method follows Qiam, Devunuri & Lehe (2024, arXiv:2412.13179), who show NIR improves parking segmentation;
labels are OpenStreetMap amenity=parking polygons (surface lots only), which is noisy-but-free supervision.

  python -m keystone.models.cnn build     # download chips + labels
  python -m keystone.models.cnn train     # train a challenger, gate it against the champion
"""
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
import torch.nn.functional as F
from shapely.geometry import Polygon, box
from shapely.strtree import STRtree
from torch import nn

from keystone.config import ARTIFACTS, DATA, DATA_RAW
from keystone.data import naip
from keystone.models import registry

CHIP_PX = 128
CHIP_M = CHIP_PX * 0.6
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


# ---------------------------------------------------------------- data
def _parking_polys():
    els = json.loads((DATA_RAW / "osm_parking.json").read_text())["elements"]
    polys = []
    for el in els:
        g = el.get("geometry")
        if g and len(g) >= 4:
            p = Polygon([(q["lon"], q["lat"]) for q in g])
            polys.append(p if p.is_valid else p.buffer(0))
    return polys


def to_input(arr):
    """uint8 [4,H,W] -> float [5,H,W]: RGB, NIR, NDVI."""
    a = arr.astype(np.float32) / 255.0
    ndvi = (a[3] - a[0]) / (a[3] + a[0] + 1e-6)
    return np.concatenate([a, ndvi[None]], axis=0)


def build_dataset(n_pos=520, n_rand=160, seed=7):
    rng = random.Random(seed)
    polys = _parking_polys()
    tree = STRtree(polys)
    centers = []
    for p in rng.sample(polys, n_pos):
        c = p.representative_point()
        jitter = CHIP_M * 0.3 / 111_320
        centers.append((c.x + rng.uniform(-jitter, jitter), c.y + rng.uniform(-jitter, jitter)))
    for _ in range(n_rand):  # urban core of OC, mostly negatives
        centers.append((rng.uniform(-118.05, -117.70), rng.uniform(33.62, 33.90)))

    def fetch(c):
        try:
            b = naip.chip_bounds(c[0], c[1], CHIP_M + 6)
            arr, tf, crs, _ = naip.read_bounds(b)
            arr = arr[:, :CHIP_PX, :CHIP_PX]
            if arr.shape[1:] != (CHIP_PX, CHIP_PX) or arr.max() == 0:
                return None
            hits = [polys[i] for i in tree.query(box(*b))]
            y = naip.rasterize_polys(hits, (CHIP_PX, CHIP_PX), tf, crs)
            return arr, y, c
        except Exception as e:  # noqa: BLE001 - a bad chip (network, nodata, CRS) is skipped, never fatal to the dataset
            print("skip", c, e, file=sys.stderr)
            return None

    with ThreadPoolExecutor(6) as ex:
        out = [r for r in ex.map(fetch, centers) if r is not None]
    X = np.stack([o[0] for o in out]).astype(np.uint8)
    Y = np.stack([o[1] for o in out]).astype(np.uint8)
    C = np.array([o[2] for o in out])
    np.savez_compressed(DATA / "parking_chips.npz", X=X, Y=Y, C=C)
    print(f"{len(X)} chips, parking pixel share {Y.mean():.3f}")


# ---------------------------------------------------------------- model
def _block(i, o):
    return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                         nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True))


class UNet(nn.Module):
    def __init__(self, c_in=5, w=24):
        super().__init__()
        self.e1, self.e2, self.e3 = _block(c_in, w), _block(w, 2 * w), _block(2 * w, 4 * w)
        self.mid = _block(4 * w, 8 * w)
        self.u3, self.d3 = nn.ConvTranspose2d(8 * w, 4 * w, 2, 2), _block(8 * w, 4 * w)
        self.u2, self.d2 = nn.ConvTranspose2d(4 * w, 2 * w, 2, 2), _block(4 * w, 2 * w)
        self.u1, self.d1 = nn.ConvTranspose2d(2 * w, w, 2, 2), _block(2 * w, w)
        self.head = nn.Conv2d(w, 1, 1)

    def forward(self, x):
        e1 = self.e1(x)
        e2 = self.e2(F.max_pool2d(e1, 2))
        e3 = self.e3(F.max_pool2d(e2, 2))
        m = self.mid(F.max_pool2d(e3, 2))
        d3 = self.d3(torch.cat([self.u3(m), e3], 1))
        d2 = self.d2(torch.cat([self.u2(d3), e2], 1))
        d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
        return self.head(d1)


def _augment(x, y):
    k = random.randint(0, 3)
    x, y = torch.rot90(x, k, (1, 2)), torch.rot90(y, k, (1, 2))
    if random.random() < 0.5:
        x, y = x.flip(2), y.flip(2)
    return x, y


def iou(pred, y):
    inter = ((pred == 1) & (y == 1)).sum()
    union = ((pred == 1) | (y == 1)).sum()
    return float(inter) / max(float(union), 1.0)


def evaluate(model, X, Y):
    model.eval()
    preds = []
    with torch.no_grad():
        for i in range(0, len(X), 32):
            xb = torch.from_numpy(np.stack([to_input(a) for a in X[i:i + 32]])).to(DEVICE)
            preds.append((torch.sigmoid(model(xb)) > 0.5).squeeze(1).cpu().numpy())
    P = np.concatenate(preds)
    return {"iou": round(iou(P, Y), 4), "pixel_acc": round(float((P == Y).mean()), 4)}


def train(epochs=30, width=24, lr=2e-3, seed=0, tag=None):
    torch.manual_seed(seed); random.seed(seed); np.random.seed(seed)
    d = np.load(DATA / "parking_chips.npz")
    X, Y = d["X"], d["Y"]
    idx = np.random.RandomState(42).permutation(len(X))  # fixed split shared by every challenger
    n_te = len(X) // 5
    te, tr = idx[:n_te], idx[n_te:]
    Xtr = torch.from_numpy(np.stack([to_input(a) for a in X[tr]]))
    Ytr = torch.from_numpy(Y[tr]).float().unsqueeze(1)
    model = UNet(w=width).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=epochs * ((len(tr) + 15) // 16))
    pos_w = torch.tensor([float((1 - Y[tr].mean()) / max(Y[tr].mean(), 1e-3))], dtype=torch.float32, device=DEVICE).clamp(max=4.0)
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(tr))
        tot = 0.0
        for i in range(0, len(tr), 16):
            b = perm[i:i + 16]
            xb, yb = zip(*[_augment(Xtr[j], Ytr[j]) for j in b])
            xb, yb = torch.stack(xb).to(DEVICE), torch.stack(yb).to(DEVICE)
            logits = model(xb)
            prob = torch.sigmoid(logits)
            dice = 1 - (2 * (prob * yb).sum() + 1) / (prob.sum() + yb.sum() + 1)
            loss = F.binary_cross_entropy_with_logits(logits, yb, pos_weight=pos_w) + dice
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            tot += loss.item() * len(b)
        if ep % 5 == 4 or ep == epochs - 1:
            print(f"epoch {ep + 1}/{epochs} loss {tot / len(tr):.4f} holdout {evaluate(model, X[te], Y[te])}")
    metrics = evaluate(model, X[te], Y[te])
    params = {"epochs": epochs, "width": width, "lr": lr, "seed": seed, "n_train": len(tr), "n_holdout": int(n_te)}
    path = ARTIFACTS / f"parking_unet_{tag or registry.new_version()}.pt"
    torch.save({"state": model.state_dict(), "width": width}, path)
    # 136 holdout chips: require a real gain, not noise
    return registry.propose("parking_cnn", registry.relative(path), metrics, params, primary="iou", min_gain=0.01)


_LOADED = {}


def load_champion():
    champ = registry.champion("parking_cnn")
    if champ is None:
        raise RuntimeError("No parking_cnn champion yet: run `python -m keystone.models.cnn train`")
    if champ["path"] not in _LOADED:
        ck = torch.load(registry.model_file(champ), map_location=DEVICE)
        m = UNet(w=ck["width"]).to(DEVICE)
        m.load_state_dict(ck["state"]); m.eval()
        _LOADED.clear(); _LOADED[champ["path"]] = m
    return _LOADED[champ["path"]], champ


def segment(arr):
    """uint8 [4,H,W] -> parking probability [H,W]. Pads to a multiple of 8 for the U-Net."""
    model, _ = load_champion()
    H, W = arr.shape[1:]
    ph, pw = (-H) % 8, (-W) % 8
    x = np.pad(to_input(arr), ((0, 0), (0, ph), (0, pw)), mode="reflect")
    with torch.no_grad():
        p = torch.sigmoid(model(torch.from_numpy(x)[None].to(DEVICE)))[0, 0].cpu().numpy()
    return p[:H, :W]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "build":
        build_dataset()
    else:
        print(json.dumps(train(epochs=int(sys.argv[2]) if len(sys.argv) > 2 else 30), indent=2))
