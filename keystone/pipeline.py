"""One-command ingestion for a region: public data in, scored sites + trained models + demo assets out.

  KEYSTONE_REGION=orange_county_ca python -m keystone.pipeline            # run every missing step
  python -m keystone.pipeline --steps hmda,osm,sites --force               # re-run chosen steps

Steps are idempotent: each skips when its output exists unless --force. Model steps go through the registry gate,
so re-running never silently replaces a better champion.
"""
import argparse
import json
import time

import requests

from keystone import config
from keystone.models import registry

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
HMDA_CSV = "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv"


def step_hmda(force=False):
    for y in config.REGION["hmda_years"]:
        out = config.DATA_RAW / f"hmda_oc_{y}.csv"
        if out.exists() and not force:
            continue
        r = requests.get(HMDA_CSV, params={"years": y, "counties": config.REGION["county_fips"], "loan_purposes": 1},
                         timeout=600, allow_redirects=True)
        r.raise_for_status()
        if "should be directed to" in r.text[:300]:  # the API answers with a link to a pre-built file
            url = r.text.split('href="')[1].split('"')[0]
            r = requests.get(url, timeout=600)
            r.raise_for_status()
        out.write_bytes(r.content)
        print(f"hmda {y}: {r.content.count(b'\n') - 1:,} rows")


def _overpass(query):
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": query}, timeout=300)
            if r.ok and r.text.lstrip().startswith("{"):
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(3)
    raise RuntimeError("all Overpass mirrors failed; retry later")


def step_osm(force=False):
    s, w, n, e = config.BBOX[1], config.BBOX[0], config.BBOX[3], config.BBOX[2]
    jobs = {
        "osm_worship.json": f'[out:json][timeout:250];way["amenity"="place_of_worship"]({s},{w},{n},{e});out geom tags;',
        "osm_parking.json": f'[out:json][timeout:250];way["amenity"="parking"]["parking"!~"underground|multi-storey|rooftop"]({s},{w},{n},{e});out geom;',
    }
    for name, q in jobs.items():
        out = config.DATA_RAW / name
        if out.exists() and not force:
            continue
        d = _overpass(q)
        out.write_text(json.dumps(d))
        print(f"{name}: {len(d['elements']):,} elements")


def step_sites(force=False):
    if (config.DATA / "faith_sites.json").exists() and not force:
        return
    from keystone.data import sites
    sites.build()


def step_cnn(force=False):
    from keystone.models import cnn
    if not (config.DATA / "parking_chips.npz").exists() or force:
        cnn.build_dataset()
    if registry.champion("parking_cnn") is None or force:
        print(cnn.train())


def step_score(force=False):
    if (config.DATA / "site_scores.json").exists() and not force:
        return
    from keystone.models import site_score
    site_score.run()


def step_market(force=False):
    if registry.champion("market_gap") is not None and not force:
        return
    from keystone.models import market_gap
    market_gap.main()


def step_homekeeper(force=False):
    out = config.ROOT / "keystone" / "app" / "static" / "demo" / "portfolio.json"
    if out.exists() and not force:
        return
    from keystone.models import homekeeper
    homekeeper.run()


def step_demo(force=False):
    out = config.ROOT / "keystone" / "app" / "static" / "demo" / "featured.json"
    if out.exists() and not force:
        return
    from keystone.demo import build_assets
    build_assets.main()


STEPS = {"hmda": step_hmda, "osm": step_osm, "sites": step_sites, "cnn": step_cnn, "score": step_score,
         "market": step_market, "homekeeper": step_homekeeper, "demo": step_demo}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default=",".join(STEPS))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    print(f"region: {config.REGION['name']} ({config.REGION_ID})")
    for name in a.steps.split(","):
        t0 = time.time()
        STEPS[name](a.force)
        print(f"[{name}] done in {time.time() - t0:.1f}s")
