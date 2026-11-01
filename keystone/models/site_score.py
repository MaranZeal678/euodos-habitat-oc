"""Score faith-owned parcels for SB 4 Habitat townhomes using the parking CNN on NAIP imagery.

  python -m keystone.models.site_score
"""
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from shapely.geometry import shape

from keystone import config
from keystone.data import naip
from keystone.models import cnn

PIXEL_SQM = 0.36  # NAIP 0.6 m


def score_site(site, keep_parking_share=0.5, min_parking_sqm=1500):
    parcel = shape(site["parcel_geojson"])
    b = parcel.bounds
    pad = 0.0002
    arr, tf, crs, _ = naip.read_bounds((b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad))
    if arr.max() == 0:
        return {**site, "cnn_error": "no imagery"}
    prob = cnn.segment(arr)
    inside = naip.rasterize_polys([parcel], prob.shape, tf, crs).astype(bool)
    footprint = naip.rasterize_polys([shape(site["footprint_geojson"])], prob.shape, tf, crs).astype(bool)
    a = arr.astype(np.float32)
    ndvi = (a[3] - a[0]) / (a[3] + a[0] + 1e-6)
    parking = (prob > 0.5) & inside & ~footprint
    green = (ndvi > 0.25) & inside & ~parking & ~footprint
    parking_sqm = float(parking.sum() * PIXEL_SQM)
    green_sqm = float(green.sum() * PIXEL_SQM)
    # Developable: the parking the congregation can give up (SB 4 lets a project keep prior parking
    # only if total parking does not increase), plus half of open lawn. Both shares are agent-tunable.
    dev_sqm = parking_sqm * (1 - keep_parking_share) + 0.5 * green_sqm
    dev_acres = dev_sqm / config.SQM_PER_ACRE
    units_townhome = int(dev_acres * config.TOWNHOME_DU_PER_ACRE)
    units_sb4_cap = int(dev_acres * config.SB4_DENSITY_RESIDENTIAL_ZONE)
    viable = parking_sqm >= min_parking_sqm and units_townhome >= 4
    return {
        **{k: v for k, v in site.items() if k not in ("parcel_geojson", "footprint_geojson")},
        "parking_sqm": round(parking_sqm), "green_sqm": round(green_sqm),
        "parking_share_of_parcel": round(parking_sqm / max(site["parcel_sqm"], 1), 3),
        "developable_acres": round(dev_acres, 2), "units_townhome": units_townhome,
        "units_sb4_cap": units_sb4_cap, "viable": bool(viable),
        "model_version": cnn.load_champion()[1]["version"],
    }


def run(limit=None, max_acres=30):
    sites = json.loads((config.DATA / "faith_sites.json").read_text())
    # very large parcels are campuses/open space where the parcel envelope is not a useful proxy
    sites = [s for s in sites if 0.25 <= s["parcel_sqm"] / config.SQM_PER_ACRE <= max_acres][:limit]
    cnn.load_champion()

    def safe(s):
        try:
            return score_site(s)
        except Exception as e:  # noqa: BLE001 - one bad parcel is recorded as cnn_error, the batch continues
            return {**{k: v for k, v in s.items() if not k.endswith("_geojson")}, "cnn_error": str(e)[:200]}

    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(safe, sites))
    rows.sort(key=lambda r: -r.get("units_townhome", 0))
    (config.DATA / "site_scores.json").write_text(json.dumps(rows))
    ok = [r for r in rows if "cnn_error" not in r]
    viable = [r for r in ok if r["viable"]]
    print(f"scored {len(ok)}/{len(rows)}; viable {len(viable)}; "
          f"townhome yield {sum(r['units_townhome'] for r in viable)}; "
          f"CNN parking detected {sum(r['parking_sqm'] for r in ok) / config.SQM_PER_ACRE:.0f} acres")
    return rows


if __name__ == "__main__":
    run()
