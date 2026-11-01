"""Fool-proofing: every front door rejects bad input with a clear error instead of returning a confident wrong answer."""
import asyncio

import pytest
from fastapi.testclient import TestClient
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
    assert income["exclusiveMinimum"] == 0 and income["maximum"] == 2_000_000
    assert ts["homekeeper_watchlist"].input_schema["properties"]["scenario"]["enum"] == ["market", "standard", "keystone"]
    assert ts["sites_search"].annotations.read_only_hint and ts["sites_search"].annotations.idempotent_hint
    assert not ts["sandbox_run_python"].annotations.read_only_hint


@pytest.fixture(scope="module")
def client():
    # one lifespan per process: MCP's session manager can only start once, exactly like a real uvicorn worker
    with TestClient(server.app) as c:
        yield c


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
