"""Property-based fuzzing. Strategies are derived from the JSON schemas the MCP server publishes, so this proves two
things at once: every input an agent is told is valid produces a finite, JSON-safe answer, and every input just outside
a published bound is rejected. Domain properties (monotonicity, probabilities in [0, 1]) are checked on top."""
import asyncio
import json
import math
import urllib.parse

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from keystone import tools
from keystone.app import server
from keystone.mcp_server.server import app as mcp_app

SCHEMAS = {t.name: t.input_schema for t in asyncio.run(mcp_app.list_tools())}
# sites_inspect fetches imagery over the network and sandbox_run_python spawns a process; both have their own tests
SKIP = {"sites_inspect", "sandbox_run_python"}
SLOW = {"mortgage_optimize": 6}  # ~3 s per call: a few examples still cover the schema corners
SPEED_CAPS = {("family_simulate", "n_paths"): 300}  # still inside the published range, just cheaper


def strategy(s, cap=None):
    if "enum" in s:
        return st.sampled_from(s["enum"])
    if "anyOf" in s:
        return st.one_of(*[strategy(x, cap) for x in s["anyOf"]])
    t = s.get("type")
    if t == "null":
        return st.none()
    if t == "boolean":
        return st.booleans()
    if t == "integer":
        lo = s.get("minimum", s.get("exclusiveMinimum", -(10**6) - 1) + 1)
        hi = s.get("maximum", s.get("exclusiveMaximum", 10**6 + 1) - 1)
        return st.integers(lo, min(hi, cap) if cap else hi)
    if t == "number":
        return st.floats(min_value=s.get("minimum", s.get("exclusiveMinimum", -1e6)),
                         max_value=s.get("maximum", s.get("exclusiveMaximum", 1e6)),
                         exclude_min="exclusiveMinimum" in s, exclude_max="exclusiveMaximum" in s, allow_nan=False)
    if t == "string":
        if "pattern" in s:
            return st.from_regex(s["pattern"], fullmatch=True)
        return st.text(max_size=s.get("maxLength", 200))
    raise AssertionError(f"no strategy for schema {s}")


def arguments(name):
    sch = SCHEMAS[name]
    props = {k: strategy(v, SPEED_CAPS.get((name, k))) for k, v in sch.get("properties", {}).items()}
    req = set(sch.get("required", []))
    return st.fixed_dictionaries({k: v for k, v in props.items() if k in req},
                                 optional={k: v for k, v in props.items() if k not in req})


def assert_sane(out):
    assert isinstance(out, dict)
    json.dumps(out, allow_nan=False)  # raises on NaN/inf anywhere in the answer

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif key.startswith("p_") and isinstance(x, float):
            assert 0 <= x <= 1, f"{key}={x} is not a probability"
    walk(out)


FUZZED = sorted(n for n in SCHEMAS if n not in SKIP)


@pytest.mark.parametrize("name", FUZZED)
def test_every_schema_valid_input_gives_a_sane_answer(name):
    @settings(max_examples=SLOW.get(name, 60), deadline=None, database=None,
              suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])
    @given(arguments(name))
    def check(kwargs):
        assert_sane(tools.BY_NAME[name](**kwargs))
    check()


def _bounded_numeric_props():
    for name in FUZZED:
        for prop, s in SCHEMAS[name].get("properties", {}).items():
            for branch in s.get("anyOf", [s]):
                if branch.get("type") in ("number", "integer") and ("maximum" in branch or "minimum" in branch):
                    yield name, prop, branch


BOUNDED = list(_bounded_numeric_props())
VALID = {"income": 90_000, "price": 750_000, "name": "stress_test_design"}  # a known-good value per required argument


@pytest.mark.parametrize(("name", "prop", "branch"), BOUNDED, ids=[f"{n}.{p}" for n, p, _ in BOUNDED])
def test_every_published_bound_is_enforced(name, prop, branch):
    required = {k: VALID[k] for k in SCHEMAS[name].get("required", [])}
    outside = []
    if "maximum" in branch:
        outside += [branch["maximum"] + 1, math.inf]
    if "minimum" in branch:
        outside += [branch["minimum"] - 1, -math.inf]
    for bad in [*outside, math.nan]:
        with pytest.raises(ValidationError):
            tools.BY_NAME[name](**{**required, prop: bad})


# Domain properties: the simulator uses common random numbers, so these hold path-for-path, not just on average.
@settings(max_examples=40, deadline=None, database=None)
@given(income=st.floats(30_000, 200_000), reserve=st.floats(0, 20_000), extra=st.floats(1, 20_000),
       vol=st.floats(0, 3))
def test_more_reserve_never_lowers_sustainment(income, reserve, extra, vol):
    def p(r):
        return tools.family_simulate(income=income, income_volatility=vol, reserve_fund=r, n_paths=300)["p_sustained_10y"]
    assert p(reserve + extra) >= p(reserve)


@settings(max_examples=200, deadline=None, database=None)
@given(size=st.integers(1, 8), a=st.floats(1_000, 400_000), b=st.floats(1_000, 400_000))
def test_income_category_is_monotone(size, a, b):
    rank = ["extremely_low", "very_low", "low", "moderate", "above_moderate"].index
    lo, hi = sorted((a, b))
    assert rank(tools.income_limits(size, lo)["category"]) <= rank(tools.income_limits(size, hi)["category"])


@settings(max_examples=60, deadline=None, database=None)
@given(c1=st.floats(100, 1_500), c2=st.floats(100, 1_500), n=st.integers(1, 300))
def test_philanthropy_gap_rises_with_hard_cost(c1, c2, n):
    lo, hi = sorted((c1, c2))
    gap = lambda c: tools.capital_plan(target_homes=n, hard_cost_per_sqft=c)["per_unit_gap_after_public_sources"]
    assert gap(hi) >= gap(lo)


# HTTP surface: any JSON body or path must produce a deliberate status code, never a 500.
JSONISH = st.recursive(st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=20),
                       lambda kids: st.lists(kids, max_size=3) | st.dictionaries(st.text(max_size=8), kids, max_size=3),
                       max_leaves=8)
FAMILY_KEYS = list(server.FamilyIn.model_fields)


@settings(max_examples=150, deadline=None, database=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(body=st.dictionaries(st.sampled_from(FAMILY_KEYS) | st.text(max_size=8), JSONISH, max_size=8) | JSONISH)
def test_optimize_never_500s(client, monkeypatch, body):
    # the compute path is fuzzed above; here only the HTTP layer is under test, so swap the 3 s optimizer for a stub
    monkeypatch.setattr(tools, "mortgage_optimize", lambda **kw: {"best": None, "stub": True})
    monkeypatch.setattr(server, "optimize_limiter", server.RateLimiter(rate=1e9, burst=1e9))
    r = client.post("/api/optimize", content=json.dumps(body, allow_nan=True), headers={"content-type": "application/json"})
    assert r.status_code in (200, 422), (body, r.status_code, r.text[:200])


@settings(max_examples=150, deadline=None, database=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(rid=st.text(min_size=1, max_size=60))
def test_run_lookup_never_500s(client, rid):
    r = client.get("/api/runs/" + urllib.parse.quote(rid, safe=""))
    assert r.status_code in (404, 405, 307, 200), (rid, r.status_code)


@settings(max_examples=100, deadline=None, database=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(month=st.text(max_size=12) | st.integers(), scenario=st.text(max_size=12))
def test_watchlist_never_500s(client, month, scenario):
    r = client.get("/api/homekeeper/watchlist", params={"month": month, "scenario": scenario})
    assert r.status_code in (200, 422), (month, scenario, r.status_code)
