"""Precompute demo assets from real model output.

For each featured faith parcel: the NAIP aerial (RGB), the CNN parking mask, the parcel outline, and a generated
townhome site plan packed onto the detected parking (setbacks, drive aisles, building rows). Plus a county-wide
layer of every scored site.

  python -m keystone.demo.build_assets
"""
import base64
import io
import json

import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import binary_dilation, binary_erosion, label
from shapely.geometry import Polygon, shape
from shapely.ops import transform as shp_transform

from keystone import config
from keystone.data import naip
from keystone.models import cnn

OUT = config.ROOT / "keystone" / "app" / "static" / "demo"
OUT.mkdir(parents=True, exist_ok=True)
PX = 0.6
UNIT_W, UNIT_D = 6.5, 12.0      # townhome footprint (m)
UNITS_PER_BLDG = 5
AISLE, END_GAP, SETBACK = 8.0, 5.0, 3.0


def _png(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def site_plan(dev, tf, angle, target):
    """Lay out a townhome neighborhood on the largest parking lot.

    Back-to-back rows of 5-unit buildings with 8 m drive aisles, on a lattice rotated to the parcel. The lattice offset
    that fits the most buildings wins, and buildings are taken center-out so the plan reads as one compact village.
    Rectangle fit is tested with a summed-area table in a 1 m grid.
    """
    lab, n = label(dev)
    if n == 0:
        return []
    sizes = np.bincount(lab.ravel())[1:]
    comp = lab == (np.argmax(sizes) + 1)
    rows, cols = np.nonzero(comp)
    xs, ys = tf * (cols + 0.5, rows + 0.5)
    pts = np.c_[xs, ys]
    c = pts.mean(0)
    th = np.radians(-angle)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    local = (pts - c) @ R.T
    gx = np.floor(local[:, 0]).astype(int)
    gy = np.floor(local[:, 1]).astype(int)
    x0, y0 = gx.min(), gy.min()
    grid = np.zeros((gy.max() - y0 + 2, gx.max() - x0 + 2), bool)
    grid[gy - y0, gx - x0] = True
    sat = np.pad(grid.cumsum(0).cumsum(1), ((1, 0), (1, 0)))

    def fits(x, y, w, h):
        if x < 0 or y < 0 or y + h > grid.shape[0] or x + w > grid.shape[1]:
            return False
        tot = sat[y + h, x + w] - sat[y, x + w] - sat[y + h, x] + sat[y, x]
        return tot >= 0.97 * w * h

    bw, bd = int(UNIT_W * UNITS_PER_BLDG), int(UNIT_D)
    px, py = bw + int(END_GAP), 2 * bd + 1 + int(AISLE)   # lattice pitch: one back-to-back row pair + aisle
    best = []
    for ox in range(0, px, 3):
        for oy in range(0, py, 3):
            cand = []
            for yy in range(oy, grid.shape[0], py):
                for half in (0, bd + 1):
                    for xx in range(ox, grid.shape[1], px):
                        if fits(xx, yy + half, bw, bd):
                            cand.append((xx, yy + half))
            if len(cand) > len(best):
                best = cand
    cx, cy = -x0, -y0  # component centroid sits at local (0, 0)
    best.sort(key=lambda p: (p[0] + bw / 2 - cx) ** 2 + (p[1] + bd / 2 - cy) ** 2)
    out, units = [], 0
    Rinv = R.T
    for xx, yy in best:
        if units >= target:
            break
        n_units = min(UNITS_PER_BLDG, target - units)
        for k in range(n_units):
            lx, ly = xx + x0 + k * UNIT_W, yy + y0
            rect = np.array([[lx, ly], [lx + UNIT_W - 0.35, ly], [lx + UNIT_W - 0.35, ly + UNIT_D], [lx, ly + UNIT_D], [lx, ly]])
            out.append(Polygon(rect @ Rinv.T + c))
        units += n_units
    return out


def build_site(site, allocated):
    parcel = shape(site["parcel_geojson"])
    b = parcel.bounds
    pad = 0.0004
    arr, tf, crs, _ = naip.read_bounds((b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad))
    prob = cnn.segment(arr)
    inside = naip.rasterize_polys([parcel], prob.shape, tf, crs).astype(bool)
    foot = naip.rasterize_polys([shape(site["footprint_geojson"])], prob.shape, tf, crs).astype(bool)
    parking = (prob > 0.5) & inside & ~foot
    dev = binary_erosion(parking, iterations=int(SETBACK / PX))
    to_utm = Transformer.from_crs(4326, crs, always_xy=True).transform
    to_ll = Transformer.from_crs(crs, 4326, always_xy=True).transform
    mrr = shp_transform(to_utm, parcel).minimum_rotated_rectangle
    xy = np.array(mrr.exterior.coords)
    e = xy[1] - xy[0]
    angle = np.degrees(np.arctan2(e[1], e[0]))
    plan = site_plan(dev, tf, angle, allocated)
    homes = [{"polygon": [list(p) for p in shp_transform(to_ll, p).exterior.coords], "i": i,
              "bldg": i // UNITS_PER_BLDG} for i, p in enumerate(plan)]
    H, W = prob.shape
    corners = [tf * (0, H), tf * (W, H), tf * (W, 0), tf * (0, 0)]  # bl, br, tr, tl (deck.gl quad order)
    quad = [list(to_ll(*c)) for c in corners]
    rgb = np.dstack([np.moveaxis(arr[:3], 0, -1), np.where(arr[:3].max(0) > 0, 255, 0).astype(np.uint8)])  # nodata -> transparent
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[parking] = (46, 230, 190, 170)
    edge = binary_dilation(parking, iterations=1) & ~parking & inside
    rgba[edge] = (160, 255, 235, 255)
    outline = np.zeros((H, W, 4), np.uint8)
    pe = binary_dilation(inside, iterations=2) & ~inside
    outline[pe] = (255, 196, 64, 255)
    return {
        "apn": site["apn"], "name": site["name"], "city": site.get("city"), "address": site.get("address"),
        "lon": site["lon"], "lat": site["lat"], "parcel_acres": round(site["parcel_sqm"] / config.SQM_PER_ACRE, 2),
        "parking_sqm": int(parking.sum() * PX * PX), "units": len(homes), "allocated": allocated,
        "bearing": float((90 - angle) % 360), "quad": quad,
        "img_rgb": _png(rgb), "img_mask": _png(rgba), "img_outline": _png(outline),
        "parcel": [list(p) for p in parcel.exterior.coords] if parcel.geom_type == "Polygon"
                  else [list(p) for p in max(parcel.geoms, key=lambda g: g.area).exterior.coords],
        "homes": homes, "model_version": cnn.load_champion()[1]["version"],
    }


def main(n_featured=10, cap=30):
    scores = json.loads((config.DATA / "site_scores.json").read_text())
    raw = {s["apn"]: s for s in json.loads((config.DATA / "faith_sites.json").read_text())}
    viable = [s for s in scores if s.get("viable")]
    featured = []
    for s in viable[:n_featured]:
        alloc = min(cap, s["units_townhome"])
        d = build_site(raw[s["apn"]], alloc)
        featured.append(d)
        print(f"{d['name'][:36]:<36} parking {d['parking_sqm']:>7,} m²  homes placed {d['units']}/{alloc}")
    (OUT / "featured.json").write_text(json.dumps(featured))
    county = [{"lon": s["lon"], "lat": s["lat"], "units": s.get("units_townhome", 0), "viable": s.get("viable", False),
               "name": s["name"], "city": s.get("city"), "apn": s.get("apn")} for s in scores if "cnn_error" not in s]
    (OUT / "county.json").write_text(json.dumps(county))
    print(f"wrote {len(featured)} featured sites, {len(county)} county points")


if __name__ == "__main__":
    main()
