import json

import numpy as np

from keystone import config, tools
from keystone.models import sustainability as sus

DEMO = config.ROOT / "keystone" / "app" / "static" / "demo"


def test_same_seed_same_life_shocks_across_designs():
    f = sus.Family(income=90_000, income_volatility=1.5)
    a = sus.simulate(f, sus.Home(), sus.Design(), n_paths=1, seed=7, record=True)
    b = sus.simulate(f, sus.Home(), sus.Design(rate=0.0686, payment_cap=0.45, stewardship=False), n_paths=1, seed=7, record=True)
    shocks = sus.EV_JOB_LOSS | sus.EV_INSURANCE | sus.EV_REPAIR
    assert np.array_equal(a["events"][:, 0] & shocks, b["events"][:, 0] & shocks)


def test_portfolio_ordering_and_watchlist():
    s = tools.homekeeper_portfolio_summary()["summary"]
    assert s["keystone"]["still_own"] > s["standard"]["still_own"] > s["market"]["still_own"]
    w = tools.homekeeper_watchlist(36)
    assert w["n_at_risk"] >= len(w["families"]) and all(f["action"] for f in w["families"])


def test_region_config_drives_constants():
    assert config.REGION["county_fips"] == "06059"
    assert config.INCOME_LIMITS_4P["low"] == config.REGION["income_limits_4p"]["low"]
    template = json.loads((config.ROOT / "keystone" / "regions" / "_template.json").read_text())
    assert set(config.REGION) - {"benchmark"} <= set(template)


def test_demo_site_plans_sit_inside_parcels():
    from shapely.geometry import Polygon
    feat = json.loads((DEMO / "featured.json").read_text())
    assert len(feat) >= 4
    for f in feat:
        parcel = Polygon(f["parcel"]).buffer(1e-5)
        assert f["units"] > 0 and all(parcel.contains(Polygon(h["polygon"])) for h in f["homes"])
