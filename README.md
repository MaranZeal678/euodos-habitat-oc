# Keystone: an agentic operating system for Habitat OC's Keys to 100

UCI Paul Merage School of Business Center for Real Estate × Habitat for Humanity of Orange County Impact Lab.

**Keystone is the operating system for nonprofit homeownership.** It finds buildable land, designs mortgages families can keep, and keeps them in their homes, with a team of AI agents that a small affiliate staff supervises. Product strategy, business model and the judge demo script are in [docs/PRODUCT.md](docs/PRODUCT.md).

**For engineers:** flowcharts and the system design (containers, request lifecycle, timeline engine, agents, model governance, security, deployment, scale path) are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**See it:** `make serve`, then open <http://localhost:8000/demo?autoplay>, a two-minute 3D mission-control demo of Orange County. A recorded 1080p copy is at `docs/keystone_demo.mp4`; re-record with `.venv/bin/python scripts/record_demo.py`, which renders frame-exact on a virtual clock.
- **Act 1:** the CNN scans church parking lots and townhomes rise out of them.
- **Act 2:** 100 families live 10 years under three ways of financing.
- **Act 3:** the capital waterfall and the agent-drafted follow-through.

A replay of a real graded agent run streams alongside throughout.

| Module | Ships |
|---|---|
| Land Radar | CNN-scored faith parcels, generated site plans, outreach drafts |
| Mortgage Designer | per-family term sheets that keep P(still home at year 10) ≥ 95% |
| HomeKeeper + Steward agent | early-warning watchlist and workouts for existing homeowners |
| Capital Planner | per-home funding waterfall, sensitivity range, application drafts |
| Agent Console + MCP | `/mcp` endpoint (Streamable HTTP, bearer auth) for Claude Desktop, Claude Code or any MCP host |

**Deploy:** `docker build -t keystone .` then run the image with `-e KEYSTONE_API_TOKEN=<secret>`, or use the Render blueprint in `render.yaml` (it generates the token). `/mcp` and `POST /api/mission` fail closed: without a token they answer only to loopback clients. One container serves `/`, `/demo`, `/api` and `/mcp`. Choose the market with `KEYSTONE_REGION` (configs live in `keystone/regions/`). Onboarding a new county means filling in `_template.json` and running `python -m keystone.pipeline`.

Keystone uses AI on the three technical problems between Habitat OC and 100 more homes:

| Problem | Keystone component | AI technique | Real data |
|---|---|---|---|
| **Land.** OC land is the binding constraint | Faith-land site finder (SB 4) | **CNN** (U-Net) on aerial imagery | NAIP 2022 RGB+NIR, OSM, OC parcel GIS, Terner SB4 |
| **Sustainability.** Families must *keep* the home | Mortgage designer | Two-layer Monte Carlo simulate-and-optimize | HCD 2026 income limits, literature-calibrated hazards |
| **Capital.** 0% mortgages tie up money | Path-to-100 planner + market-gap model | Gradient boosting with fairness guardrail | HMDA loan-level 2022–2024 (52K OC decisions) |

All of it is run by a **hierarchy of Claude agents** (Director → Land / Family / Capital leads → Site analysts & Underwriters). The agents reach every tool through an **MCP server**, run their own analysis code in an **OS-level sandbox**, and **improve themselves** through gated champion/challenger loops. The same loop governs the CNN, the credit model and the agents' own playbooks.

See [docs/RESEARCH_BRIEF.md](docs/RESEARCH_BRIEF.md) for the evidence base (about 45 verified citations) and the prototype results.

```
                       ┌──────────── Director (Opus 5.5) ─────────────┐   progress ledger, final brief
                       │ delegate (parallel)                          │
       ┌───────────────┼──────────────────────┬───────────────────────┘
  Land lead (Opus)  Family lead (Opus)    Capital lead (Opus)
       │ delegate         │ delegate              │
  Site analysts      Underwriters (Sonnet 5.5)    │
  (Sonnet 5.5)            │                       │
       └───── MCP (stdio / Streamable HTTP) ──────┴──► Keystone MCP server: 13 tools + 2 resources
                                                        ├─ sites_* ─────► U-Net CNN on NAIP
                                                        ├─ family_*, mortgage_optimize ─► Monte Carlo
                                                        ├─ capital_plan, market_gap_report ─► HMDA model
                                                        ├─ sandbox_run_python ─► seatbelt / bubblewrap sandbox
                                                        └─ skills_*, models_registry, research_lookup
  Self-improvement: graders → Reflexion lessons → playbook challengers → deterministic gate (registry.py)
```

## Quick start

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python torch numpy pandas scikit-learn anthropic "mcp[cli]" fastapi uvicorn requests pillow rasterio shapely pystac-client planetary-computer pyproj matplotlib
```

The data and models are already built in `data/` and `artifacts/`. To rebuild everything from the public sources:

```bash
.venv/bin/python -m keystone.data.sites            # OSM worship sites ⨝ OC parcels
.venv/bin/python -m keystone.models.cnn build      # NAIP chips + OSM parking labels
.venv/bin/python -m keystone.models.cnn train 30   # U-Net champion/challenger
.venv/bin/python -m keystone.models.site_score     # score every faith parcel
.venv/bin/python -m keystone.models.market_gap     # HMDA temporal champion/challenger
```

Run the agents:

```bash
.venv/bin/python -m keystone.cli --mission 0                      # uses Claude if credentials exist, else offline scripted policy
.venv/bin/python -m keystone.agents.improve --generations 3        # self-improvement loop
.venv/bin/uvicorn keystone.app.server:app --port 8000             # dashboard at http://localhost:8000
.venv/bin/python -m keystone.mcp_server.server --http 8765        # expose the MCP server to other hosts
```

To use Claude, set `ANTHROPIC_API_KEY` or run `ant auth login`. Leads run on `claude-opus-5-5` and workers on `claude-sonnet-5-5`, with adaptive thinking, per-agent effort, and server-side refusal fallbacks (`fallbacks: "default"`). Without credentials, a deterministic scripted policy drives the *same* hierarchy, MCP tools, sandbox and graders, so the whole pipeline can be demonstrated offline.

To use the MCP server from Claude Code: `claude mcp add keystone -- /path/to/.venv/bin/python -m keystone.mcp_server.server`.

## Layout

```
keystone/
  config.py            sourced constants (every number has a URL)
  research.py          verified citations the agents can cite
  tools.py             the 13 domain tools (one implementation, three front doors)
  skills.py            Voyager-style library of verified sandbox code
  data/                sites.py (OSM ⨝ parcels), naip.py (Planetary Computer)
  models/              cnn.py (U-Net), site_score.py, market_gap.py (HMDA), sustainability.py, capital.py, registry.py
  sandbox/runner.py    seatbelt/bubblewrap sandbox + AST screen + audit log
  mcp_server/server.py MCP server (stdio + Streamable HTTP)
  agents/              specs.py (hierarchy), runtime.py (Claude + scripted policies over MCP),
                       memory.py (lessons, playbooks), evals.py (missions + graders), improve.py (loop)
  app/                 FastAPI dashboard
data/raw               HMDA CSVs, OSM extracts, Terner SB4 tables, cached source PDFs
artifacts/             model weights, registry.json, runs/<id>/{trace.jsonl,report.md,grade.json}, skills/, memory/
```

## Honest limits
Hazard rates are assumptions, because no public Habitat loan-performance data exists. CNN labels are weak (OSM). OSM worship sites are not proof of ownership. HMDA measures access, not performance. Details and next steps are in the research brief.
