"""Keystone web app: dashboard (/), demo (/demo), REST API (/api), MCP over Streamable HTTP (/mcp).

  uvicorn keystone.app.server:app --port 8000

/mcp and POST /api/mission run code and spend money, so they fail closed: with KEYSTONE_API_TOKEN set they require
`Authorization: Bearer <token>`; without it they answer only to loopback clients (local development).
"""
import asyncio
import contextlib
import json
import os
import re
import secrets
import time
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from keystone import config, tools
from keystone.agents import evals
from keystone.agents.runtime import RUNS, Hierarchy
from keystone.mcp_server.server import app as mcp_server
from keystone.models import registry

TOKEN = os.environ.get("KEYSTONE_API_TOKEN")
mcp_app = mcp_server.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                         host=os.environ.get("KEYSTONE_HOST", "127.0.0.1"))


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with mcp_app.router.lifespan_context(mcp_app):  # runs the MCP session manager
        yield


app = FastAPI(title="Keystone", lifespan=lifespan)
HERE = config.ROOT / "keystone" / "app"


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def auth(request: Request, call_next):
    protected = request.url.path.startswith("/mcp") or (request.method == "POST" and request.url.path == "/api/mission")
    if protected:
        if TOKEN:
            got = request.headers.get("authorization", "")
            if not secrets.compare_digest(got, f"Bearer {TOKEN}"):
                return JSONResponse({"error": "missing or invalid bearer token"}, status_code=401)
        elif (request.client.host if request.client else "") not in LOOPBACK:
            return JSONResponse({"error": "set KEYSTONE_API_TOKEN to use this endpoint from another machine"}, status_code=403)
    return await call_next(request)


app.mount("/mcp", mcp_app)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
_tasks = {}


@app.get("/demo")
def demo():
    return FileResponse(HERE / "demo.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "region": config.REGION_ID, "champions": {n: (registry.champion(n) or {}).get("version") for n in ("parking_cnn", "market_gap")}}


@app.get("/api/demo/trace")
def demo_trace():
    """Most recent fully graded run: its trace (for the replayed agent feed), brief and grade."""
    for d in sorted(RUNS.iterdir(), reverse=True):
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
    return FileResponse(HERE / "index.html")


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
    income: float = Field(92_000, gt=0, le=2_000_000)
    household_size: int = Field(4, ge=1, le=8)
    savings: float = Field(4_000, ge=0, le=20_000_000)
    monthly_debts: float = Field(350, ge=0, le=1_000_000)
    income_volatility: float = Field(1.0, ge=0, le=5)
    home_value: float = Field(750_000, ge=10_000, le=20_000_000)
    min_sustain: float = Field(0.95, ge=0.5, le=0.999)


@app.post("/api/optimize")
def optimize(f: FamilyIn):
    out = tools.mortgage_optimize(**f.model_dump())
    out["limits"] = tools.income_limits(household_size=f.household_size, income=f.income)
    out["market"] = tools.family_market_score(income=f.income, price=f.home_value, monthly_debts=f.monthly_debts)
    return out


@app.get("/api/registry")
def reg():
    return registry.history()


@app.get("/api/runs")
def runs():
    out = []
    for d in sorted(RUNS.iterdir(), reverse=True):
        if not (d / "trace.jsonl").exists():
            continue
        first = json.loads((d / "trace.jsonl").open().readline())
        g = json.loads((d / "grade.json").read_text()) if (d / "grade.json").exists() else None
        out.append({"id": d.name, "policy": first.get("policy"), "done": (d / "report.md").exists(),
                    "score": g and g["score"], "running": d.name in _tasks and not _tasks[d.name].done()})
    return out[:40]


RUN_ID = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{4}$")


@app.get("/api/runs/{rid}")
def run(rid: str):
    if not RUN_ID.match(rid) or not (RUNS / rid / "trace.jsonl").exists():
        raise HTTPException(404, "unknown run id")
    d = RUNS / rid
    events = [json.loads(l) for l in (d / "trace.jsonl").read_text().splitlines()]
    return {"id": rid, "events": events,
            "report": (d / "report.md").read_text() if (d / "report.md").exists() else None,
            "grade": json.loads((d / "grade.json").read_text()) if (d / "grade.json").exists() else None}


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
        async with Hierarchy(policy=m.policy, run_id=rid) as h:
            report = await h.mission(evals.mission_text(spec))
            (h.trace.dir / "grade.json").write_text(json.dumps(evals.grade(report, h.tool_results, spec), indent=2))

    _tasks[rid] = asyncio.create_task(go())
    return {"run_id": rid, "mission": spec["name"]}


@app.get("/api/missions")
def missions():
    return evals.MISSIONS
