"""The Crossline scenario (Lane 2, Clear it): timeline engine, capital aggregation, provenance, sign-in and the API."""
import itertools
import json
import re

import pytest

from keystone import config, scenario
from keystone.app import server
from keystone.models import pathways, timeline

# ---- timeline engine (Clear it)

def test_baseline_is_about_four_years_and_keystone_cuts_it():
    c = timeline.compare()
    assert c["baseline"]["months"] == 50.0 and c["baseline"]["years"] == 4.2
    assert c["keystone"]["months"] == 28.2 and c["saved_months"] == 21.8
    assert c["lever_savings_alone"] == {"instant_screen": 5.8, "sb4_ministerial": 6.0, "parallel_funding": 10.0}


def test_every_duration_is_sourced_or_labelled_an_estimate():
    for levers in ({}, {"instant_screen": True, "sb4_ministerial": True, "parallel_funding": True}):
        for ph in timeline.schedule(levers)["phases"]:
            src = ph["source"]
            assert src["url"] or src["label"].startswith("estimate"), ph


def test_critical_path_is_a_real_dependency_chain():
    sch = timeline.schedule({"parallel_funding": True})
    by = {p["key"]: p for p in sch["phases"]}
    path = sch["critical_path"]
    for a, b in itertools.pairwise(path):
        assert by[b]["start"] == pytest.approx(by[a]["start"] + by[a]["months"])
    assert by[path[-1]]["start"] + by[path[-1]]["months"] == pytest.approx(sch["months"])


def test_levers_never_lengthen_the_clock_and_longer_construction_does():
    base = timeline.schedule()["months"]
    for k in ("instant_screen", "sb4_ministerial", "parallel_funding"):
        assert timeline.schedule({k: True})["months"] <= base
    assert timeline.schedule(estimates={"construction": 20})["months"] > base


# ---- the scenario and its numbers

@pytest.fixture
def seed():
    return scenario.fresh()


def test_seed_is_the_crossline_offer_with_thirty_households(seed):
    assert seed["site"]["apn"] == "588-081-21" and seed["site"]["homes"] == 30
    assert len(seed["households"]) == 30
    assert seed["timeline"]["keystone"]["years"] == 2.4


def test_every_headline_carries_its_provenance(seed):
    for key, h in seed["headlines"].items():
        assert h["value"] and h["formula"] and h["source"] and h["tool"] and "inputs" in h, key


def test_counts_are_expected_values_not_single_draws(seed):
    exp = round(sum(h["p"]["keystone"] for h in seed["households"]), 1)
    assert seed["headlines"]["mortgages"]["value"] == f"{exp} of 30"


def test_philanthropy_sums_only_real_shortfalls(seed):
    from keystone.models import capital
    from keystone.models import sustainability as sus
    total = 0
    for h in seed["households"]:
        p = capital.plan(1, family=scenario._family(h), design=sus.Design(**h["design_params"]), sites=[],
                         cost_inputs=dict(config.COST_ASSUMPTIONS, hard_cost_per_sqft=seed["assumptions"]["hard_cost_per_sqft"]))
        total += max(p["per_unit_gap_after_public_sources"], 0)
    assert seed["capital"]["keystone"]["philanthropy"] == round(total)


def test_hard_cost_raises_the_gap(seed):
    before = seed["capital"]["keystone"]["philanthropy"]
    after = scenario.edit_assumptions(seed, hard_cost_per_sqft=450)["capital"]["keystone"]["philanthropy"]
    assert after > before


def test_turning_off_sb4_lengthens_the_scenario_clock(seed):
    s = scenario.edit_levers(seed, {"sb4_ministerial": False})
    assert s["timeline"]["keystone"]["months"] >= 28.2
    names = [p["name"] for p in s["timeline"]["keystone"]["phases"]]
    assert "Discretionary entitlement + CEQA" in names and "SB 4 ministerial approval" not in names


# ---- legal paths (Clear it: pick the path for one address)

def test_crossline_recommends_sb4_and_rules_out_small_paths():
    r = pathways.evaluate({"homes": 30})
    by = {p["key"]: p for p in r["paths"]}
    assert r["recommended"] == "sb4"
    assert by["sb4"]["verdict"] == "verify" and by["discretionary"]["verdict"] == "fits"
    assert {k for k, p in by.items() if p["verdict"] == "no"} == {"sb684", "sb9_units", "sb9_split", "adu"}


def test_missing_facts_are_to_verify_never_assumed():
    by = {p["key"]: p for p in pathways.evaluate({"homes": 30})["paths"]}
    owner = next(c for c in by["sb4"]["checks"] if "religious institution" in c["test"])
    assert owner["status"] == "verify"
    assert pathways.evaluate({"faith_owner_since_2024": "no"})["paths"][0]["key"] != "sb4"


def test_path_verdicts_follow_project_size_and_zoning():
    small = {p["key"]: p["verdict"] for p in pathways.evaluate({"homes": 8})["paths"]}
    assert small["sb684"] == "verify"
    tiny = pathways.evaluate({"homes": 3, "zoning": "single_family"})
    assert tiny["recommended"] == "sb9_split"
    stuck = pathways.evaluate({"faith_owner_since_2024": "no", "city_streamlining": "no"})
    assert stuck["recommended"] == "discretionary"  # only when no ministerial path survives


def test_every_path_cites_current_law_and_a_clock_source():
    for p in pathways.evaluate()["paths"]:
        assert p["clock_source"]["url"] and p["statute"]
        assert not re.search(r"65852\.2(?!\d)", p["statute"])  # ADU law was renumbered to 66310-66342 (65852.21 is SB 9)
        assert p["days"] is None or "unknown" not in p["clock"].lower()


def test_choosing_the_discretionary_path_slows_the_clock(seed):
    s = scenario.edit_path(seed, choice="discretionary")
    assert s["timeline"]["keystone"]["months"] > 28.2 and s["levers"]["sb4_ministerial"] is False
    s = scenario.edit_path(s, choice="sb35")
    assert s["timeline"]["keystone"]["months"] == 28.2
    assert any(p["name"] == "SB 35 / SB 423 streamlined approval" for p in s["timeline"]["keystone"]["phases"])
    with pytest.raises(ValueError):
        scenario.edit_path(s, choice="sb9_units")


# ---- numbers quoted in the brief and the film stay pinned

def test_pinned_portfolio_and_capital_numbers():
    port = json.loads((config.ROOT / "keystone/app/static/demo/portfolio.json").read_text())["summary"]
    assert (port["market"]["still_own"], port["standard"]["still_own"], port["keystone"]["still_own"]) == (39, 69, 85)
    ref = json.loads((config.ROOT / "keystone/app/static/demo/reference_run.json").read_text())["report"]
    assert "$7,431,500" in ref and "$164,407" in ref


# ---- sign-in and the scenario API

@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("KEYSTONE_DEMO_LOGIN", "1")


def _signin(client):
    r = client.post("/api/session", json={"email": server.DEMO_LOGIN["email"], "password": server.DEMO_LOGIN["password"]})
    assert r.status_code == 200, r.text
    return r


def test_scenario_requires_sign_in(client):
    client.cookies.clear()
    assert client.get("/api/scenario").status_code == 401
    assert client.post("/api/scenario/levers", json={}).status_code == 401


def test_demo_login_is_off_unless_enabled(client, monkeypatch):
    monkeypatch.delenv("KEYSTONE_DEMO_LOGIN", raising=False)
    r = client.post("/api/session", json={"email": server.DEMO_LOGIN["email"], "password": server.DEMO_LOGIN["password"]})
    assert r.status_code == 401
    assert client.get("/api/session").json()["demo_login"] is None


def test_wrong_password_names_no_field(client, demo):
    r = client.post("/api/session", json={"email": server.DEMO_LOGIN["email"], "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "wrong email or password"


def test_password_is_stored_hashed(client, demo, isolated_artifacts):
    _signin(client)
    stored = (isolated_artifacts / "accounts.json").read_text()
    assert server.DEMO_LOGIN["password"] not in stored and "hash" in stored


def test_signed_in_session_runs_the_scenario(client, demo):
    _signin(client)
    s = client.get("/api/scenario").json()
    assert s["headlines"]["clock"]["value"] == "2.4 years"
    s = client.post("/api/scenario/levers", json={"levers": {"parallel_funding": False}}).json()
    assert s["timeline"]["keystone"]["months"] > 28.2
    assert client.post("/api/scenario/levers", json={"estimates": {"construction": 900}}).status_code == 422
    assert client.post("/api/scenario/household", json={"index": 99, "income": 50_000}).status_code == 422
    assert client.post("/api/scenario/household", json={"index": 0, "income": -5}).status_code == 422
    s = client.post("/api/scenario/reset").json()
    assert s["timeline"]["keystone"]["months"] == 28.2


def test_sessions_are_private(client, demo):
    from fastapi.testclient import TestClient
    _signin(client)
    client.post("/api/scenario/levers", json={"levers": {"sb4_ministerial": False}})
    other = TestClient(server.app)
    _signin(other)
    assert other.get("/api/scenario").json()["levers"]["sb4_ministerial"] is True


def test_household_edit_recomputes_that_family(client, demo):
    _signin(client)
    before = client.get("/api/scenario").json()["households"][0]
    after = client.post("/api/scenario/household", json={"index": 0, "income": before["income"] + 40_000}).json()["households"][0]
    assert after["income"] == before["income"] + 40_000 and after["p"]["keystone"] >= before["p"]["keystone"]


def test_path_route_retests_and_rejects_paths_that_do_not_fit(client, demo):
    _signin(client)
    s = client.post("/api/scenario/path", json={"homes": 8}).json()
    assert {p["key"]: p["verdict"] for p in s["path"]["results"]["paths"]}["sb684"] == "verify"
    assert client.post("/api/scenario/path", json={"choice": "adu"}).status_code == 422
    assert client.post("/api/scenario/path", json={"zoning": "castle"}).status_code == 422
    s = client.post("/api/scenario/path", json={"choice": "discretionary"}).json()
    assert s["headlines"]["path"]["value"] == "Rezone" and s["timeline"]["keystone"]["months"] > 28.2


def test_remote_scenario_missions_use_the_offline_policy(client, demo, monkeypatch):
    monkeypatch.setenv("KEYSTONE_SCENARIO_CLAUDE", "")
    _signin(client)

    class Quick:
        def __init__(self, **kw):
            self.kw = kw

        async def __aenter__(self):
            raise RuntimeError("stopped for the test")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(server.runtime, "Hierarchy", Quick)
    r = client.post("/api/scenario/mission").json()
    assert r["policy"] == "scripted"  # TestClient's peer is not loopback: no paid Claude runs for remote visitors
