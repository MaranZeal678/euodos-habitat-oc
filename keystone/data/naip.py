"""NAIP 0.6 m RGB+NIR aerial imagery from Microsoft Planetary Computer (anonymous SAS signing)."""
import json
from functools import lru_cache

import numpy as np
import planetary_computer
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as shp_transform
from shapely.strtree import STRtree

from keystone.config import DATA, OC_BBOX

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


INDEX = DATA / "naip_index.json"


@lru_cache(maxsize=1)
def _index():
    """One STAC search for the whole county, cached on disk; latest year per tile wins."""
    if not INDEX.exists():
        cat = Client.open(STAC)
        items = cat.search(collections=["naip"], bbox=list(OC_BBOX), datetime="2020-01-01/2030-01-01").item_collection()
        rows = [{"href": i.assets["image"].href, "year": i.datetime.year, "geometry": i.geometry} for i in items]
        INDEX.write_text(json.dumps(rows))
    rows = json.loads(INDEX.read_text())
    rows.sort(key=lambda r: -r["year"])
    geoms = [shape(r["geometry"]) for r in rows]
    return rows, geoms, STRtree(geoms)


def item_for(lon, lat):
    rows, geoms, tree = _index()
    pt = Point(lon, lat)
    hits = sorted(i for i in tree.query(pt) if geoms[i].contains(pt))
    if not hits:
        return None, None
    r = rows[hits[0]]
    return planetary_computer.sign(r["href"]), r["year"]


def read_bounds(lonlat_bounds, href=None):
    """Read 4-band chip covering lon/lat bounds. Returns (array[4,H,W] uint8, transform, crs, year)."""
    lon0, lat0, lon1, lat1 = lonlat_bounds
    year = None
    if href is None:
        href, year = item_for((lon0 + lon1) / 2, (lat0 + lat1) / 2)
    with rasterio.open(href) as src:
        tf = Transformer.from_crs(4326, src.crs, always_xy=True)
        x0, y0 = tf.transform(lon0, lat0)
        x1, y1 = tf.transform(lon1, lat1)
        win = from_bounds(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), src.transform)
        arr = src.read(window=win, boundless=True, fill_value=0)
        return arr, src.window_transform(win), src.crs, year


def rasterize_polys(polys_lonlat, out_shape, transform, crs):
    if not polys_lonlat:
        return np.zeros(out_shape, dtype=np.uint8)
    tf = Transformer.from_crs(4326, crs, always_xy=True).transform
    geoms = [shp_transform(tf, p) for p in polys_lonlat]
    return rasterize([(mapping(g), 1) for g in geoms], out_shape=out_shape, transform=transform, fill=0, dtype=np.uint8)


def chip_bounds(lon, lat, meters):
    dlat = meters / 2 / 111_320
    dlon = meters / 2 / (111_320 * np.cos(np.radians(lat)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)
