"""Euodos web app: dashboard (/), demo (/demo), REST API (/api), MCP over Streamable HTTP (/mcp).

  uvicorn keystone.app.server:app --port 8000

/mcp and POST /api/mission run code and spend money, so they fail closed: with KEYSTONE_API_TOKEN set they require
`Authorization: Bearer <token>`; without it they answer only to loopback clients, and only when the server itself is
bound to loopback (local development). A deployed server (KEYSTONE_HOST=0.0.0.0, as in the Dockerfile) never trusts
loopback, because a reverse proxy in front of it would make every visitor look local.
/api/optimize is open but CPU-heavy (~3 s), so it is rate-limited per client and capped in concurrency.
"""
import asyncio
import contextlib
import hashlib
import json
import logging
import os
import pathlib
import re
import secrets
import threading
import time
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from keystone import config, tools
from keystone import scenario as scenario_model
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


app = FastAPI(title="Euodos", lifespan=lifespan)
HERE = config.ROOT / "keystone" / "app"


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, exc):
    # FastAPI's default 422 echoes the offending input, and NaN/Infinity are not JSON, so it would 500 on exactly the
    # inputs it is rejecting. Field location, message and type are all a client needs.
    return JSONResponse({"detail": [{k: e[k] for k in ("loc", "msg", "type") if k in e} for e in exc.errors()]}, status_code=422)


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def trust_loopback():
    return HOST in LOOPBACK


def host_name(host):
    return host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host


PROXY_HOPS = int(os.environ.get("KEYSTONE_PROXY_HOPS", "0"))  # reverse proxies in front (Render: 1)


def client_key(request):
    """The address to rate-limit. Behind N trusted proxies the real client is the Nth entry from the right of
    X-Forwarded-For (entries further left are client-supplied and spoofable); otherwise the TCP peer."""
    xff = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if PROXY_HOPS and len(xff) >= PROXY_HOPS:
        return xff[-PROXY_HOPS]
    return request.client.host if request.client else ""


@app.middleware("http")
async def auth(request: Request, call_next):
    protected = request.url.path.startswith("/mcp") or (request.method == "POST" and request.url.path == "/api/mission")
    if protected:
        if TOKEN:
            got = request.headers.get("authorization", "").encode("latin-1", "replace")  # bytes: non-ASCII can't 500
            if not secrets.compare_digest(got, f"Bearer {TOKEN}".encode()):
                return JSONResponse({"error": "missing or invalid bearer token"}, status_code=401)
        elif (not trust_loopback() or (request.client.host if request.client else "") not in LOOPBACK
              or host_name(request.headers.get("host", "")) not in LOOPBACK):  # a rebound DNS name keeps its own Host
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


REFERENCE_RUN = HERE / "static" / "demo" / "reference_run.json"  # a graded scripted run shipped with the app


@app.get("/api/demo/trace")
def demo_trace():
    """Most recent fully graded run: its trace (for the replayed agent feed), brief and grade. A fresh deploy has no
    runs yet, so it replays the reference run instead and the demo never loses its agent rail."""
    for d in sorted(runtime.RUNS.iterdir(), reverse=True):
        if (d / "grade.json").exists() and (d / "report.md").exists():
            return run(d.name)
    return json.loads(REFERENCE_RUN.read_text()) | {"reference": True}


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
    The key comes from client_key (the proxy-added client address when KEYSTONE_PROXY_HOPS is set)."""

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
    if not optimize_limiter.allow(client_key(request)):
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
    # Record the run before answering: the dashboard opens it right away, while the MCP server is still starting
    runtime.Trace(rid).log(type="mission_queued", policy=m.policy, mission=spec["name"])
    _tasks[rid] = asyncio.create_task(go())
    return {"run_id": rid, "mission": spec["name"]}


@app.get("/api/missions")
def missions():
    return evals.MISSIONS


# ---------------------------------------------------------------- scenario app (sign-in + the Crossline scenario)
# One demo account, private per-session scenarios. The seeded login exists only where KEYSTONE_DEMO_LOGIN=1 (the Mac
# app sets it; a hosted public demo may set it): every session gets its own copy of the scenario and nothing it does
# is persisted, so a shared demo password exposes nothing. Real accounts live in STATE/accounts.json (scrypt hashes).
DEMO_LOGIN = {"email": "maria@habitat-oc.demo", "password": "keys-to-100", "name": "Maria Reyes",
              "role": "Director of Real Estate, Habitat for Humanity OC (demo persona)"}


def accounts_path():  # read per call, so tests and the Mac app's state dir always win over the import-time default
    return (pathlib.Path(os.environ["KEYSTONE_STATE_DIR"]) if os.environ.get("KEYSTONE_STATE_DIR") else config.STATE) / "accounts.json"


_sessions: dict = {}
_session_lock = threading.Lock()
MAX_SESSIONS = 500
scenario_limiter = RateLimiter(rate=1.0, burst=20)


def demo_login_enabled():
    return os.environ.get("KEYSTONE_DEMO_LOGIN") == "1"


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


def _accounts():
    accounts = read_json(accounts_path()) or {}
    if demo_login_enabled() and DEMO_LOGIN["email"] not in accounts:
        salt = secrets.token_bytes(16)
        accounts[DEMO_LOGIN["email"]] = {"salt": salt.hex(), "hash": _hash(DEMO_LOGIN["password"], salt),
                                         "name": DEMO_LOGIN["name"], "role": DEMO_LOGIN["role"], "demo": True}
        write_atomic(accounts_path(), json.dumps(accounts, indent=2))
    if not demo_login_enabled():
        accounts = {k: v for k, v in accounts.items() if not v.get("demo")}
    return accounts


def _session(request: Request):
    token = request.cookies.get("ks_session", "")
    with _session_lock:
        sess = _sessions.get(token)
        if sess:
            sess["seen"] = time.monotonic()
    if not sess:
        raise HTTPException(401, "sign in to use the scenario")
    return sess


def _limit(request: Request):
    if not scenario_limiter.allow(client_key(request)):
        raise HTTPException(429, "too many requests; wait a moment", headers={"Retry-After": "2"})


class SignIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@app.get("/scenario")
def scenario_page():
    return FileResponse(HERE / "scenario.html", headers=NO_CACHE)


@app.get("/api/session")
def session_status(request: Request):
    token = request.cookies.get("ks_session", "")
    sess = _sessions.get(token)
    hint = {k: DEMO_LOGIN[k] for k in ("email", "password")} if demo_login_enabled() else None
    return {"signed_in": bool(sess), "name": sess and sess["name"], "role": sess and sess["role"], "demo_login": hint}


@app.post("/api/session")
def sign_in(body: SignIn, request: Request, response: Response):
    _limit(request)
    acct = _accounts().get(body.email.strip().lower())
    if acct is None or not secrets.compare_digest(_hash(body.password, bytes.fromhex(acct["salt"])), acct["hash"]):
        raise HTTPException(401, "wrong email or password")
    token = secrets.token_urlsafe(32)
    with _session_lock:
        if len(_sessions) >= MAX_SESSIONS:  # forget the idlest session
            del _sessions[min(_sessions, key=lambda t: _sessions[t]["seen"])]
        _sessions[token] = {"email": body.email.strip().lower(), "name": acct["name"], "role": acct["role"],
                            "scenario": scenario_model.fresh(), "seen": time.monotonic(), "lock": threading.Lock()}
    response.set_cookie("ks_session", token, httponly=True, samesite="lax", secure=request.url.scheme == "https",
                        max_age=12 * 3600)
    return {"signed_in": True, "name": acct["name"], "role": acct["role"]}


@app.delete("/api/session")
def sign_out(request: Request, response: Response):
    with _session_lock:
        _sessions.pop(request.cookies.get("ks_session", ""), None)
    response.delete_cookie("ks_session")
    return {"signed_in": False}


@app.get("/api/scenario")
def get_scenario(request: Request):
    return _session(request)["scenario"]


class HouseholdEdit(BaseModel):
    index: int = Field(ge=0, le=scenario_model.N_HOMES - 1)
    income: float | None = Field(None, ge=1_000, le=2_000_000)
    household_size: int | None = Field(None, ge=1, le=8)
    savings: float | None = Field(None, ge=0, le=20_000_000)
    monthly_debts: float | None = Field(None, ge=0, le=1_000_000)


class AssumptionEdit(BaseModel):
    hard_cost_per_sqft: float | None = Field(None, gt=0, le=2_000)
    calhome: float | None = Field(None, ge=0, le=20_000_000)
    ahp: float | None = Field(None, ge=0, le=20_000_000)


class LeverEdit(BaseModel):
    levers: dict[Literal["instant_screen", "sb4_ministerial", "parallel_funding"], bool] = {}
    estimates: dict[Literal["screen", "land_deal", "entitlement", "permits", "construction", "families"],
                    float] = {}


def _edit(request, fn):
    _limit(request)
    sess = _session(request)
    if not sess["lock"].acquire(blocking=False):
        raise HTTPException(409, "the last change is still computing", headers={"Retry-After": "1"})
    try:
        sess["scenario"] = fn(sess["scenario"])
        return sess["scenario"]
    finally:
        sess["lock"].release()


@app.post("/api/scenario/household")
def edit_household(body: HouseholdEdit, request: Request):
    changes = body.model_dump(exclude={"index"}, exclude_none=True)
    return _edit(request, lambda s: scenario_model.edit_household(s, body.index, **changes))


@app.post("/api/scenario/assumptions")
def edit_assumptions(body: AssumptionEdit, request: Request):
    return _edit(request, lambda s: scenario_model.edit_assumptions(s, **body.model_dump()))


@app.post("/api/scenario/levers")
def edit_levers(body: LeverEdit, request: Request):
    if any(not 0.25 <= v <= 60 for v in body.estimates.values()):
        raise HTTPException(422, "each estimate must be between 0.25 and 60 months")
    return _edit(request, lambda s: scenario_model.edit_levers(s, body.levers, body.estimates))


class PathEdit(BaseModel):
    homes: int | None = Field(None, ge=1, le=500)
    zoning: Literal["unknown", "single_family", "multifamily", "nonresidential"] | None = None
    city_streamlining: Literal["unknown", "yes", "no"] | None = None
    faith_owner_since_2024: Literal["unknown", "yes", "no"] | None = None
    hazards_clear: Literal["unknown", "yes", "no"] | None = None
    choice: Literal["sb4", "sb35", "sb684", "sb9_units", "sb9_split", "adu", "discretionary"] | None = None


@app.post("/api/scenario/path")
def edit_path(body: PathEdit, request: Request):
    project = body.model_dump(exclude={"choice"}, exclude_none=True)
    try:
        return _edit(request, lambda s: scenario_model.edit_path(s, project, body.choice))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@app.post("/api/scenario/reset")
def reset_scenario(request: Request):
    return _edit(request, lambda s: scenario_model.fresh())


def scenario_policy(request):
    """Claude runs cost money: only the local app (loopback) or an explicit opt-in may use it; else scripted."""
    trusted = trust_loopback() and (request.client.host if request.client else "") in LOOPBACK
    return "auto" if trusted or os.environ.get("KEYSTONE_SCENARIO_CLAUDE") == "1" else "scripted"


class MissionAsk(BaseModel):
    question: str | None = Field(None, max_length=400)


@app.post("/api/scenario/mission")
async def scenario_mission(request: Request, body: MissionAsk | None = None):
    _limit(request)
    s = _session(request)["scenario"]
    if sum(1 for t in _tasks.values() if not t.done()) >= 3:
        raise HTTPException(429, "three missions are already running; wait for one to finish")
    hh = sorted(s["households"], key=lambda h: h["income"])
    picks = [hh[0], hh[len(hh) // 2], hh[-1]]  # the lowest, median and highest income in the cohort
    spec = {"name": f"{s['site']['name']}: {s['site']['homes']} homes", "target_homes": s["site"]["homes"],
            "city": s["site"]["city"],
            "families": [{"name": h["name"], "income": h["income"], "household_size": h["household_size"],
                          "savings": h["savings"], "monthly_debts": h["monthly_debts"],
                          "income_volatility": h["income_volatility"]} for h in picks]}
    if body and body.question and body.question.strip():
        spec["question"] = body.question.strip()  # the user's own ask, handed to the director with the mission
    rid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    policy = scenario_policy(request)

    async def go():
        try:
            async with runtime.Hierarchy(policy=policy, run_id=rid) as h:
                report = await h.mission(evals.mission_text(spec))
                write_atomic(h.trace.dir / "grade.json", json.dumps(evals.grade(report, h.tool_results, spec), indent=2))
        except Exception as e:  # a failed mission must say so in its run, not vanish with the task
            msg = f"{type(e).__name__}: {e}"[:2000]
            trace = runtime.Trace(rid)
            trace.log(type="mission_error", policy=policy, error=msg)
            write_atomic(trace.dir / "error.json", json.dumps({"error": msg}))
            log.exception("scenario mission %s failed", rid)

    runtime.Trace(rid).log(type="mission_queued", policy=policy, mission=spec["name"])
    _tasks[rid] = asyncio.create_task(go())
    return {"run_id": rid, "policy": policy}
