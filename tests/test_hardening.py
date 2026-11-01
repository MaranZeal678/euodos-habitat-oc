"""Fool-proofing: every front door rejects bad input with a clear error instead of returning a confident wrong answer."""
import asyncio

import pytest
from pydantic import ValidationError

from keystone import config, tools
from keystone.app import server
from keystone.mcp_server.server import app as mcp_app
from keystone.models import market_gap
from keystone.models import sustainability as sus
from keystone.sandbox.runner import run_python

BAD_TOOL_CALLS = [
    (tools.family_market_score, {"income": -5, "price": 750_000}),
    (tools.family_market_score, {"income": 90_000, "price": 750_000, "down_payment_share": 1.5}),
    (tools.homekeeper_watchlist, {"month": 120}),
    (tools.homekeeper_watchlist, {"month": -1}),
    (tools.homekeeper_watchlist, {"scenario": "best"}),
    (tools.income_limits, {"household_size": 12}),
    (tools.income_limits, {"household_size": 4, "income": 0}),
    (tools.sites_inspect, {"apn": "../../etc/passwd"}),
    (tools.capital_plan, {"hard_cost_per_sqft": -1}),
    (tools.capital_plan, {"target_homes": 0}),
    (tools.family_simulate, {"income": 90_000, "payment_cap": 2.0}),
    (tools.mortgage_optimize, {"income": 90_000, "household_size": 0}),
    (tools.sandbox_run_python, {"code": ""}),
    (tools.sandbox_run_python, {"code": "print(1)", "save_as_skill": "../evil"}),
    (tools.skills_get, {"name": "../../keystone/config"}),
]


@pytest.mark.parametrize(("fn", "kwargs"), BAD_TOOL_CALLS, ids=[f"{f.__name__}-{i}" for i, (f, _) in enumerate(BAD_TOOL_CALLS)])
def test_tools_reject_bad_input(fn, kwargs):
    with pytest.raises(ValidationError):
        fn(**kwargs)


def test_domain_objects_reject_nonsense_directly():
    for make in (lambda: sus.Family(income=0), lambda: sus.Family(household_size=9), lambda: sus.Design(rate=-0.01),
                 lambda: sus.Design(term_years=100), lambda: sus.Home(value=1)):
        with pytest.raises(ValueError):
            make()
    with pytest.raises(ValueError):
        market_gap.score_family(92_000, 750_000, 350)  # positional mistake: 350 lands in down_payment_share


def test_cost_override_does_not_leak_between_requests():
    before = dict(config.COST_ASSUMPTIONS)
    hi = tools.capital_plan(hard_cost_per_sqft=600)
    lo = tools.capital_plan()
    assert config.COST_ASSUMPTIONS == before
    assert hi["unit_cost"]["total"] > lo["unit_cost"]["total"]


def test_mcp_schemas_publish_bounds():
    ts = {t.name: t for t in asyncio.run(mcp_app.list_tools())}
    income = ts["family_market_score"].input_schema["properties"]["income"]
    assert income["minimum"] == 1_000 and income["maximum"] == 2_000_000
    assert ts["homekeeper_watchlist"].input_schema["properties"]["scenario"]["enum"] == ["market", "standard", "keystone"]
    assert ts["sites_search"].annotations.read_only_hint and ts["sites_search"].annotations.idempotent_hint
    assert not ts["sandbox_run_python"].annotations.read_only_hint


def test_api_validates_and_hides_internals(client, monkeypatch):
    monkeypatch.setattr(server, "TOKEN", "t0k")
    auth = {"Authorization": "Bearer t0k"}
    assert client.post("/api/optimize", json={"income": -1}).status_code == 422
    assert client.post("/api/optimize", json={"household_size": 40}).status_code == 422
    assert client.post("/api/mission", json={"mission": 99}, headers=auth).status_code == 422
    assert client.post("/api/mission", json={"policy": "rm -rf"}, headers=auth).status_code == 422
    assert client.get("/api/homekeeper/watchlist", params={"month": 500}).status_code == 422
    for rid in ("..", "..%2F..", "20261031_000000_zzzz", "x" * 300):
        assert client.get(f"/api/runs/{rid}").status_code == 404
    assert client.get("/healthz").json()["ok"] is True


def test_token_gates_mcp_and_mission(client, monkeypatch):
    monkeypatch.setattr(server, "TOKEN", "s3cret")
    assert client.post("/api/mission", json={}).status_code == 401
    assert client.post("/mcp/", json={}).status_code == 401
    assert client.post("/mcp/", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/summary").status_code == 200  # reads stay open


def test_no_token_means_loopback_only(client, monkeypatch):
    monkeypatch.setattr(server, "TOKEN", None)
    # TestClient's peer is "testclient", i.e. not loopback: exactly the docker-without-a-token case
    assert client.post("/mcp/", json={}).status_code == 403
    assert client.post("/api/mission", json={}).status_code == 403


def test_sandbox_cannot_read_home_directory():
    import os
    r = run_python(f"print(open({os.path.expanduser('~/.zshrc')!r}).read())")
    assert not r["ok"]
    r = run_python(f"import os\nprint(os.listdir({os.path.expanduser('~')!r}))")
    assert not r["ok"]


def test_optimize_is_rate_limited_per_client(client, monkeypatch):
    monkeypatch.setattr(tools, "mortgage_optimize", lambda **kw: {"best": None})
    monkeypatch.setattr(server, "optimize_limiter", server.RateLimiter(rate=0, burst=3))
    codes = [client.post("/api/optimize", json={}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = client.post("/api/optimize", json={})
    assert r.headers["retry-after"] and "wait" in r.json()["detail"]


def test_optimize_concurrency_is_capped(client, monkeypatch):
    import threading
    busy = threading.BoundedSemaphore(1)
    busy.acquire()  # every slot taken
    monkeypatch.setattr(server, "optimize_slots", busy)
    monkeypatch.setattr(server, "optimize_limiter", server.RateLimiter(rate=1e9, burst=1e9))
    r = client.post("/api/optimize", json={})
    assert r.status_code == 429 and "busy" in r.json()["detail"]
    busy.release()  # the refused call must not have released a slot it never took
    assert busy.acquire(blocking=False)


def test_rate_limiter_forgets_idle_clients():
    lim = server.RateLimiter(rate=0, burst=1, max_clients=10)
    for i in range(50):
        assert lim.allow(f"10.0.0.{i}")
    assert len(lim.buckets) <= 10


def test_partial_traces_never_500(client, isolated_artifacts):
    runs = isolated_artifacts / "runs"
    (runs / "20261031_000000_aaaa").mkdir()
    (runs / "20261031_000000_aaaa" / "trace.jsonl").write_text("")  # mission just started
    (runs / "20261031_000001_bbbb").mkdir()
    (runs / "20261031_000001_bbbb" / "trace.jsonl").write_text('{"type": "agent_start", "policy": "scripted"}\n{"type": "to')
    (runs / "20261031_000001_bbbb" / "grade.json").write_text('{"score": 0.')  # torn write
    listing = client.get("/api/runs")
    assert listing.status_code == 200
    assert {r["id"]: r["policy"] for r in listing.json()} == {"20261031_000000_aaaa": None, "20261031_000001_bbbb": "scripted"}
    one = client.get("/api/runs/20261031_000001_bbbb").json()
    assert len(one["events"]) == 1 and one["grade"] is None


def test_failed_mission_is_recorded_not_lost(client, monkeypatch):
    import time as _time

    class Exploding:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            raise RuntimeError("model endpoint unreachable")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(server, "TOKEN", "t")
    monkeypatch.setattr(server.runtime, "Hierarchy", Exploding)
    rid = client.post("/api/mission", json={"policy": "scripted"}, headers={"Authorization": "Bearer t"}).json()["run_id"]
    for _ in range(50):
        r = client.get(f"/api/runs/{rid}")
        if r.status_code == 200 and r.json()["error"]:
            break
        _time.sleep(0.05)
    assert "model endpoint unreachable" in r.json()["error"]
    row = next(x for x in client.get("/api/runs").json() if x["id"] == rid)
    assert row["error"] and not row["running"]


def test_deployed_server_never_trusts_loopback(client, monkeypatch):
    # behind a reverse proxy every visitor arrives from 127.0.0.1; a 0.0.0.0-bound server must not treat that as local
    monkeypatch.setattr(server, "TOKEN", None)
    monkeypatch.setattr(server, "HOST", "0.0.0.0")
    assert not server.trust_loopback()
    monkeypatch.setattr(server, "HOST", "127.0.0.1")
    assert server.trust_loopback()


def test_healthz_proves_the_sandbox_runs(client, monkeypatch):
    monkeypatch.setattr(server, "_sandbox_check", {})
    h = client.get("/healthz").json()
    assert h["sandbox"]["ok"] and h["degraded"] == []
    monkeypatch.setattr(server, "_sandbox_check", {})
    monkeypatch.setattr(server, "run_python", lambda *a, **k: {"ok": False, "stdout": "", "stderr": "bwrap: No permissions", "sandbox": "bubblewrap"})
    h = client.get("/healthz").json()
    assert h["ok"] and h["degraded"] == ["sandbox"] and "bwrap" in h["sandbox"]["error"]


def test_skill_index_survives_concurrent_writers():
    from concurrent.futures import ThreadPoolExecutor

    from keystone import skills
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: skills.save(f"s{i}", f"print({i})", "x"), range(40)))
    assert len(skills.index()) == 40
