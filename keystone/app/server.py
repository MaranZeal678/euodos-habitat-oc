"""Keystone web app: dashboard (/), demo (/demo), REST API (/api), MCP over Streamable HTTP (/mcp).

  uvicorn keystone.app.server:app --port 8000

/mcp and POST /api/mission run code and spend money, so they fail closed: with KEYSTONE_API_TOKEN set they require
`Authorization: Bearer <token>`; without it they answer only to loopback clients, and only when the server itself is
bound to loopback (local development). A deployed server (KEYSTONE_HOST=0.0.0.0, as in the Dockerfile) never trusts
loopback, because a reverse proxy in front of it would make every visitor look local.
/api/optimize is open but CPU-heavy (~3 s), so it is rate-limited per client and capped in concurrency.
"""
import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from keystone import config, tools
from keystone.agents import evals, runtime
from keystone.mcp_server.server import app as mcp_server
from keystone.models import registry
from keystone.sandbox.runner import run_python

log = logging.getLogger("keystone")
TOKEN = os.environ.get("KEYSTONE_API_TOKEN")
HOST = os.environ.get("KEYSTONE_HOST", "127.0.0.1")
mcp_app = mcp_server.streamable_http_app(streamable_http_path="/", stateless_http=True, host=HOST)


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with mcp_app.router.lifespan_context(mcp_app):  # runs the MCP session manager
        yield


app = FastAPI(title="Keystone", lifespan=lifespan)
HERE = config.ROOT / "keystone" / "app"


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, exc):
    # FastAPI's default 422 echoes the offending input, and NaN/Infinity are not JSON, so it would 500 on exactly the
    # inputs it is rejecting. Field location, message and type are all a client needs.
    return JSONResponse({"detail": [{k: e[k] for k in ("loc", "msg", "type") if k in e} for e in exc.errors()]}, status_code=422)


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def trust_loopback():
    return HOST in LOOPBACK


@app.middleware("http")
async def auth(request: Request, call_next):
    protected = request.url.path.startswith("/mcp") or (request.method == "POST" and request.url.path == "/api/mission")
    if protected:
        if TOKEN:
            got = request.headers.get("authorization", "")
            if not secrets.compare_digest(got, f"Bearer {TOKEN}"):
                return JSONResponse({"error": "missing or invalid bearer token"}, status_code=401)
        elif not trust_loopback() or (request.client.host if request.client else "") not in LOOPBACK:
            return JSONResponse({"error": "set KEYSTONE_API_TOKEN to use this endpoint from another machine"}, status_code=403)
    return await call_next(request)


app.mount("/mcp", mcp_app)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
_tasks = {}


NO_CACHE = {"Cache-Control": "no-cache"}  # pages revalidate, so a redeploy never shows a stale dashboard or demo


@app.get("/demo")
def demo():
    return FileResponse(HERE / "demo.html", headers=NO_CACHE)


_sandbox_check = {}


def sandbox_status():
    """Run one trivial program through the OS sandbox, once per process: a host without a working sandbox (no bwrap,
    no user namespaces in the container) shows up at deploy time instead of failing mid-mission."""
    if not _sandbox_check:
        r = run_python("print(6 * 7)", timeout=30, agent="healthz")
        _sandbox_check.update({"ok": r["ok"] and r["stdout"].strip() == "42", "kind": r.get("sandbox")}
                              | ({} if r["ok"] else {"error": r["stderr"][-300:]}))
    return _sandbox_check


@app.get("/healthz")
def healthz():
    sbx = sandbox_status()
    return {"ok": True, "degraded": [] if sbx["ok"] else ["sandbox"], "sandbox": sbx, "region": config.REGION_ID,
            "champions": {n: (registry.champion(n) or {}).get("version") for n in ("parking_cnn", "market_gap")}}


@app.get("/api/demo/trace")
def demo_trace():
    """Most recent fully graded run: its trace (for the replayed agent feed), brief and grade."""
    for d in sorted(runtime.RUNS.iterdir(), reverse=True):
        if (d / "grade.json").exists() and (d / "report.md").exists():
            return run(d.name)
    raise HTTPException(404, "no graded runs yet")


@app.get("/api/demo/capital")
def demo_capital():
    p = tools.capital_plan(100)
    imp = config.ARTIFACTS / "improve_log.json"
    return {k: p[k] for k in ("unit_cost", "first_mortgage_face", "first_mortgage_pv", "capital_recovered_per_unit",
                              "per_unit_gap_after_public_sources", "philanthropy_needed_total", "public_sources_total")} | {
        "public_per_unit": p["assumptions"]["calhome_per_unit"] + p["assumptions"]["ahp_per_unit"],
        "improve": json.loads(imp.read_text()) if imp.exists() else [],
        "champions": {n: registry.champion(n) for n in ("parking_cnn", "market_gap")}}


@app.get("/api/homekeeper/watchlist")
def hk_watchlist(month: int = 36, scenario: Literal["market", "standard", "keystone"] = "keystone"):
    if not 0 <= month <= 119:
        raise HTTPException(422, "month must be 0-119")
    return tools.homekeeper_watchlist(month=month, scenario=scenario)


@app.get("/")
def index():
    return FileResponse(HERE / "index.html", headers=NO_CACHE)


@app.get("/api/summary")
def summary():
    sites = [s for s in json.loads((config.DATA / "site_scores.json").read_text()) if s.get("viable")]
    gaps = json.loads((config.DATA / "market_gap.json").read_text())
    imp = config.ARTIFACTS / "improve_log.json"
    return {
        "viable_sites": len(sites), "townhome_units": sum(s["units_townhome"] for s in sites),
        "parcels_scored": len(json.loads((config.DATA / "site_scores.json").read_text())),
        "terner_oc": config.TERNER_OC, "market_gap": gaps,
        "champions": {n: registry.champion(n) for n in ("parking_cnn", "market_gap")},
        "improve": json.loads(imp.read_text()) if imp.exists() else [],
        "income_limits": tools.income_limits(4), "sources": config.SOURCES,
    }


@app.get("/api/sites")
def sites():
    rows = json.loads((config.DATA / "site_scores.json").read_text())
    keep = ["name", "city", "address", "apn", "lat", "lon", "parcel_sqm", "parking_sqm", "green_sqm",
            "developable_acres", "units_townhome", "units_sb4_cap", "viable", "religion", "denomination"]
    return [{k: r.get(k) for k in keep} for r in rows if "cnn_error" not in r]


class FamilyIn(BaseModel):
    income: float = Field(92_000, ge=1_000, le=2_000_000)
    household_size: int = Field(4, ge=1, le=8)
    savings: float = Field(4_000, ge=0, le=20_000_000)
    monthly_debts: float = Field(350, ge=0, le=1_000_000)
    income_volatility: float = Field(1.0, ge=0, le=5)
    home_value: float = Field(750_000, ge=10_000, le=20_000_000)
    min_sustain: float = Field(0.95, ge=0.5, le=0.999)


class RateLimiter:
    """Token bucket per client: `burst` calls at once, refilled at `rate` per second. In-process, so per worker.
    The key is the peer address uvicorn resolved (it honours X-Forwarded-For only from FORWARDED_ALLOW_IPS)."""

    def __init__(self, rate, burst, max_clients=10_000):
        self.rate, self.burst, self.max_clients = rate, burst, max_clients
        self.buckets = {}
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            self.buckets[key] = (tokens - 1 if tokens >= 1 else tokens, now)
            if len(self.buckets) > self.max_clients:  # forget the idlest clients; a full bucket loses nothing
                for k in sorted(self.buckets, key=lambda k: self.buckets[k][1])[: self.max_clients // 2]:
                    del self.buckets[k]
            return tokens >= 1


optimize_limiter = RateLimiter(rate=0.5, burst=10)  # 10 back-to-back, then one every 2 s
optimize_slots = threading.BoundedSemaphore(4)       # at most 4 optimizations burning CPU at once


@app.post("/api/optimize")
def optimize(f: FamilyIn, request: Request):
    if not optimize_limiter.allow(request.client.host if request.client else ""):
        raise HTTPException(429, "too many requests from this client; wait a few seconds", headers={"Retry-After": "2"})
    if not optimize_slots.acquire(blocking=False):
        raise HTTPException(429, "the optimizer is busy with other families; try again in a few seconds", headers={"Retry-After": "3"})
    try:
        out = tools.mortgage_optimize(**f.model_dump())
        out["limits"] = tools.income_limits(household_size=f.household_size, income=f.income)
        out["market"] = tools.family_market_score(income=f.income, price=f.home_value, monthly_debts=f.monthly_debts)
        return out
    finally:
        optimize_slots.release()


@app.get("/api/registry")
def reg():
    return registry.history()


def read_jsonl(path):
    """Events of a trace that may still be being written: a torn last line is skipped, not a 500."""
    out = []
    for line in path.read_text().splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            out.append(json.loads(line))
    return out


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


@app.get("/api/runs")
def runs():
    out = []
    for d in sorted(runtime.RUNS.iterdir(), reverse=True):
        if not (d / "trace.jsonl").exists():
            continue
        events = read_jsonl(d / "trace.jsonl")
        g = read_json(d / "grade.json")
        err = read_json(d / "error.json")
        out.append({"id": d.name, "policy": events[0].get("policy") if events else None, "done": (d / "report.md").exists(),
                    "score": g and g.get("score"), "running": d.name in _tasks and not _tasks[d.name].done(),
                    "error": err and err.get("error")})
    return out[:40]


def write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


RUN_ID = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{4}$")


@app.get("/api/runs/{rid}")
def run(rid: str):
    if not RUN_ID.match(rid) or not (runtime.RUNS / rid / "trace.jsonl").exists():
        raise HTTPException(404, "unknown run id")
    d = runtime.RUNS / rid
    err = read_json(d / "error.json")
    return {"id": rid, "events": read_jsonl(d / "trace.jsonl"),
            "report": (d / "report.md").read_text() if (d / "report.md").exists() else None,
            "grade": read_json(d / "grade.json"), "error": err and err.get("error")}


class MissionIn(BaseModel):
    mission: int = Field(0, ge=0, le=len(evals.MISSIONS) - 1)
    policy: Literal["auto", "claude", "scripted"] = "auto"


@app.post("/api/mission")
async def mission(m: MissionIn):
    rid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    if sum(1 for t in _tasks.values() if not t.done()) >= 3:
        raise HTTPException(429, "three missions are already running; wait for one to finish")
    spec = evals.MISSIONS[m.mission]

    async def go():
        try:
            async with runtime.Hierarchy(policy=m.policy, run_id=rid) as h:
                report = await h.mission(evals.mission_text(spec))
                write_atomic(h.trace.dir / "grade.json", json.dumps(evals.grade(report, h.tool_results, spec), indent=2))
        except Exception as e:  # a failed mission must say so in its run, not vanish with the task
            msg = f"{type(e).__name__}: {e}"[:2000]
            trace = runtime.Trace(rid)  # also lists the run when it died before its first event
            trace.log(type="mission_error", policy=m.policy, error=msg)
            write_atomic(trace.dir / "error.json", json.dumps({"error": msg}))
            log.exception("mission %s failed", rid)

    for done in [k for k, t in _tasks.items() if t.done()]:  # keep the task table bounded
        del _tasks[done]
    _tasks[rid] = asyncio.create_task(go())
    return {"run_id": rid, "mission": spec["name"]}


@app.get("/api/missions")
def missions():
    return evals.MISSIONS
