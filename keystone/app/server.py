"""Keystone web app: dashboard (/), demo (/demo), REST API (/api), MCP over Streamable HTTP (/mcp).

  uvicorn keystone.app.server:app --port 8000

Set KEYSTONE_API_TOKEN to require `Authorization: Bearer <token>` on /mcp and on endpoints that start agent runs.
"""
import asyncio
import contextlib
import json
import os
import secrets
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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


@app.middleware("http")
async def auth(request: Request, call_next):
    protected = request.url.path.startswith("/mcp") or (request.method == "POST" and request.url.path == "/api/mission")
    if TOKEN and protected:
        got = request.headers.get("authorization", "")
        if not secrets.compare_digest(got, f"Bearer {TOKEN}"):
            return JSONResponse({"error": "missing or invalid bearer token"}, status_code=401)
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
def hk_watchlist(month: int = 36, scenario: str = "keystone"):
    return tools.homekeeper_watchlist(month, scenario)


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
    income: float = 92_000
    household_size: int = 4
    savings: float = 4_000
    monthly_debts: float = 350
    income_volatility: float = 1.0
    home_value: float = 750_000
    min_sustain: float = 0.95


@app.post("/api/optimize")
def optimize(f: FamilyIn):
    out = tools.mortgage_optimize(**f.model_dump())
    out["limits"] = tools.income_limits(f.household_size, f.income)
    out["market"] = tools.family_market_score(f.income, f.home_value, f.monthly_debts)
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


@app.get("/api/runs/{rid}")
def run(rid: str):
    d = RUNS / rid
    if not d.exists() or "/" in rid:
        raise HTTPException(404)
    events = [json.loads(l) for l in (d / "trace.jsonl").read_text().splitlines()]
    return {"id": rid, "events": events,
            "report": (d / "report.md").read_text() if (d / "report.md").exists() else None,
            "grade": json.loads((d / "grade.json").read_text()) if (d / "grade.json").exists() else None}


class MissionIn(BaseModel):
    mission: int = 0
    policy: str = "auto"


@app.post("/api/mission")
async def mission(m: MissionIn):
    rid = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    spec = evals.MISSIONS[m.mission % len(evals.MISSIONS)]

    async def go():
        async with Hierarchy(policy=m.policy, run_id=rid) as h:
            report = await h.mission(evals.mission_text(spec))
            (h.trace.dir / "grade.json").write_text(json.dumps(evals.grade(report, h.tool_results, spec), indent=2))

    _tasks[rid] = asyncio.create_task(go())
    return {"run_id": rid, "mission": spec["name"]}


@app.get("/api/missions")
def missions():
    return evals.MISSIONS
