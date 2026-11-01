"""Faith-owned site inventory for SB 4: OSM places of worship joined to OC Public Works parcels.

Run: python -m keystone.data.sites
"""
import json
from concurrent.futures import ThreadPoolExecutor

import requests
from shapely.geometry import Polygon, mapping, shape

from keystone.config import DATA, DATA_RAW, REGION

PS = REGION["parcel_service"]
PARCEL_QUERY = PS["url"] + "/query"
F = PS["fields"]
FIELDS = ",".join([v for v in F.values() if v] + [PS["area_field"]])


def load_worship_sites():
    elements = json.loads((DATA_RAW / "osm_worship.json").read_text())["elements"]
    sites = []
    for el in elements:
        geom = el.get("geometry")
        if not geom or len(geom) < 4:
            continue
        poly = Polygon([(p["lon"], p["lat"]) for p in geom])
        if not poly.is_valid:
            poly = poly.buffer(0)
        tags = el.get("tags", {})
        sites.append({
            "osm_id": el["id"],
            "name": tags.get("name", "Unnamed place of worship"),
            "religion": tags.get("religion"),
            "denomination": tags.get("denomination"),
            "footprint": poly,
        })
    return sites


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parcel_for_point(lon, lat):
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": FIELDS,
        "returnGeometry": "true", "outSR": 4326, "f": "geojson",
    }
    for _ in range(3):
        try:
            r = requests.get(PARCEL_QUERY, params=params, timeout=60)
            feats = r.json().get("features", [])
            if not feats:
                return None
            f = max(feats, key=lambda f: f["properties"].get(PS["area_field"]) or 0)
            return f
        except (requests.RequestException, ValueError):
            continue
    return None


def build():
    sites = load_worship_sites()
    print(f"{len(sites)} OSM places of worship in OC bbox")

    def enrich(site):
        pt = site["footprint"].representative_point()
        f = parcel_for_point(pt.x, pt.y)
        out = {k: v for k, v in site.items() if k != "footprint"}
        out["lon"], out["lat"] = pt.x, pt.y
        out["footprint_geojson"] = mapping(site["footprint"])
        if f:
            p = f["properties"]
            parcel = shape(f["geometry"])
            g = lambda k: p.get(F[k]) if F.get(k) else None
            out.update({
                "apn": g("apn"), "address": g("address"),
                "city": (g("city") or "").replace(" CA", "").strip().title(),
                "zip": g("zip"), "assessed": _num(g("assessed")),
                "land_value": _num(g("land_value")), "improved_value": _num(g("improved_value")),
                "general_plan": g("general_plan"), "zoning": g("zoning"), "zclass": g("zclass"),
                "parcel_sqm": (p.get(PS["area_field"]) or 0) * PS["area_to_sqm"],
                "parcel_geojson": f["geometry"],
                "parcel_bounds": list(parcel.bounds),
            })
        return out

    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(enrich, sites))
    rows = [r for r in rows if r.get("apn")]
    # Several worship buildings can share a parcel; keep one row per APN
    by_apn = {}
    for r in rows:
        by_apn.setdefault(r["apn"], r)
    rows = sorted(by_apn.values(), key=lambda r: -r["parcel_sqm"])
    (DATA / "faith_sites.json").write_text(json.dumps(rows))
    print(f"{len(rows)} unique parcels written to {DATA / 'faith_sites.json'}")
    return rows


if __name__ == "__main__":
    build()
