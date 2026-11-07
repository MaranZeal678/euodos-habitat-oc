# Euodos

> For a nonprofit project manager handed a land offer: Euodos finds the fastest legal path for that address, shows offer-to-move-in in 2.4 years instead of 4.2, and proves the families can afford and keep the homes.

## The real user

Maria Reyes (a made-up persona) runs real estate at Habitat for Humanity of Orange County. Crossline Church in Laguna Hills (APN 588-081-21, a real public parcel) offers part of its parking lot. She has to answer a board question fast: can 30 families move in within two years, under which law, and who pays?

**Before:** she works out which of seven legal paths might apply from city pages and statutes (some still cite renumbered law), assumes the usual sequence of about four years, and only finds out whether families qualify and what the gap is after approval.
**After:** she signs in, sees every path tested against this parcel with its statute, clock and open checks, watches the critical path drop to 2.4 years, and gets the family and funding answer in the same session, with a source behind every number.

## What we built

A Mac app (also a web server) that runs one land offer end to end in six steps:

1. **The offer.** A U-Net CNN reads the parking lot from 0.6 m NAIP aerial imagery: 45,450 m², room for 30 townhomes. SB 4 screen marked met or "to verify".
2. **The path.** Seven legal paths (SB 4, SB 35/423, SB 684, SB 9 duplex, SB 9 lot split, ADU, rezone) tested against the project. Each shows its current statute (ADU law cited as 66314, formerly 65852.2), review type, clock and every test as met / to verify / fails. Change homes, zoning or city status and the verdicts update; pick a path and the clock follows.
3. **The clock.** The project as a dependency graph; the clock is its critical path. 4.2 years the usual way, 2.4 with the site pre-screened, a ministerial path and funding started on day one.
4. **Families.** 30 households with incomes sampled from real 2024 HMDA records: chance a bank says no, and chance they keep the home for 10 years under a mortgage design optimized for them. Edit an income and it recomputes live.
5. **Who pays.** Capital stack summed home by home: $5.4M philanthropy versus $6.8M with standard 0% loans.
6. **Ten years.** The same families under three ways of financing, same shocks: 22.0 of 30 expected to keep their homes versus 7.5 on market loans.

Plus a one-page printable summary, a source dialog on every headline, and a team of Claude agents you can run on the offer.

**Demo video:** uploaded on the hub
**Mac app:** [Euodos for Mac (Apple Silicon)](https://github.com/MaranZeal678/euodos-releases/releases/latest). Demo sign-in `maria@habitat-oc.demo` / `keys-to-100`.
**For engineers:** flowcharts and system design in [hackathon-info/ARCHITECTURE.md](hackathon-info/ARCHITECTURE.md).

## How Claude is used

- **Building it:** Claude Code wrote and reviewed the code, the models, the tests and the CI that builds the Mac app, and drafted the demo script.
- **Inside the tool:** a hierarchy of Claude agents (Opus 5.5 leads, Sonnet 5.5 workers) works the offer through an MCP server: land, family and capital leads delegate to site analysts and underwriters, run analysis code in an OS sandbox, and write a brief that code graders check (every URL must be real, every assumption disclosed). Without an API key the same hierarchy runs on a deterministic offline policy.
- **What a person checks:** every "to verify" item (title, hazard screens, the city's streamlining status, zoning), the labelled assumptions, and the final brief. Euodos files nothing and contacts no one.

## Try it

Needs macOS or Linux, Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/MaranZeal678/euodos-habitat-oc.git
cd euodos-habitat-oc
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
KEYSTONE_DEMO_LOGIN=1 .venv/bin/uvicorn keystone.app.server:app --port 8000
```

Open <http://localhost:8000/scenario> and sign in with `maria@habitat-oc.demo` / `keys-to-100`. Use ← → to move between steps, **P** for the one-page summary.

The sample data and trained models ship in the repo (`data/processed`, `artifacts/`, `keystone/app/static/demo/scenario_seed.json`), so no account is needed. Optional environment variables are listed in `.env.example`; `ANTHROPIC_API_KEY` switches the agents from the offline policy to Claude. Tests: `uv pip install --python .venv/bin/python -r requirements-dev.txt && .venv/bin/python -m pytest -q tests`.

## Sources and assumptions

| Item | Source or assumption | Date checked |
|---|---|---|
| SB 4: ownership as of Jan 1, 2024, 100% lower income, all zones, hazard exclusions, 60-day conflict notice, 90-day design review | [HCD SB 4 fact sheet, Gov 65913.16](https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/aff-hsg-faith-higher-ed-sb-4.pdf) (April 2026) | 2026-11-07 |
| SB 35 / SB 423: consistency in 60 days, approval in 90 days (150 homes or fewer) | [HCD SB 35 Guidelines §301(b)](https://www.hcd.ca.gov/policy-research/docs/SB-35-Guidelines-Update-Final.pdf), Gov 65913.4 | 2026-11-07 |
| SB 684 / SB 1123 map for 10 or fewer parcels; SB 9 (65852.21, 66411.7, 60-day lot split); ADU 66314 (60 days, formerly 65852.2) | Impact Lab Lane 2 DATA-SOURCES (leginfo, HCD); SB 684 clock shown as unknown | 2026-11-07 |
| City subject to SB 35 streamlining, parcel zoning, title, fire/flood/fault screens | Not checked: shown as "to verify" | — |
| Baseline about 4 years; rezone ~1 year + entitlements ~1 year | Impact Lab brief and timeline.json (ASSUMPTION) | 2026-11-07 |
| SB 4 approval in practice 90–180 days | [SF Planning](https://sfplanning.org/node/3069) | 2026-11-01 |
| Discretionary approval 6 to 25+ months | [Pew 2024](https://pewtrusts.org/it/research-and-analysis/issue-briefs/2024/08/reforms-spur-faster-housing-approvals-in-california) | 2026-11-01 |
| Funding application to award 10+ months | Terner Center 2025 via [Davis Vanguard](https://davisvanguard.org/2025/05/california-affordable-housing-finance/) | 2026-11-01 |
| Site screen 6 mo, land deal 4, permits 4, construction 14, family selection 6 | ASSUMPTION (editable in the app) | — |
| Parking area and homes per site | CNN on [NAIP](https://planetarycomputer.microsoft.com/dataset/naip) imagery, labels from OpenStreetMap; homes = 16 per acre on half the parking plus half the lawn, capped at 30 (ASSUMPTION) | 2026-10-31 |
| Bank denial model | [CFPB HMDA](https://ffiec.cfpb.gov/data-browser/) Orange County 2022–2024 | 2026-11-01 |
| Household incomes | Sampled from 2024 HMDA applicants at or under 80% AMI; savings, debts, job-loss and repair risks are ASSUMPTIONS | 2026-11-01 |
| Income limits | CA HCD 2026 Orange County limits | 2026-10-31 |
| Hard cost per sq ft, CalHome $60k and AHP $40k per home, 5% note discount rate, $750k home value | ASSUMPTION (editable in the app) | — |

Every assumed number is labelled ASSUMPTION or "estimate" here and in the app.

## What is real and what is mocked

| Part | Status |
|---|---|
| Parcel, CNN parking scan, SB 4 density check | working (real data; scan stored, live re-scan on the server build) |
| Legal path tests and clocks | working for the facts listed above; zoning, city status, title and hazards are inputs marked "to verify" |
| Timeline critical path | working; durations are sourced or labelled estimates |
| Bank-denial and 10-year models | working on real HMDA incomes; households are synthetic and the hazard rates are assumptions |
| Capital stack | working; per-home program amounts are assumptions |
| Agent hierarchy | working offline; with a key it runs on Claude |
| Sign-in | demo account only |

## Where it gets things wrong

- It cannot see zoning for this parcel (the county field is empty) or whether Laguna Hills is subject to SB 35 streamlining, so those paths stay "to verify".
- The OpenStreetMap place-of-worship tag is not a title record; SB 4 needs ownership as of January 1, 2024.
- SB 684's clock and its zone and lot-size tests were not read in detail, so the app says "unknown".
- It does not yet model plan-check correction rounds, utility and fire sign-offs, annual funding cycles, the condo map or tenant relocation as separate delays.
- Household finances and loan-performance hazards are assumptions; no public Habitat loan data exists.

## Next steps

Next month a Habitat project manager could use it to triage land offers. With one more week: city-by-city checklists and fees for all 34 OC cities, measured approval times from HCD's Annual Progress Report data, a stale-statute checker for city forms, and the other delays as phases with their cost per month.

## Data and privacy

This project uses only public or provided data. It contains no personal information about real tenants, buyers or residents; the persona and households are made up. It does not file applications or contact any city or person. Not legal, financial or lending advice.

## License

MIT, see [LICENSE](LICENSE).

## Under the hood

Euodos uses AI on the three technical problems between Habitat OC and 100 more homes:

| Problem | Euodos component | AI technique | Real data |
|---|---|---|---|
| **Land.** OC land is the binding constraint | Faith-land site finder (SB 4) | **CNN** (U-Net) on aerial imagery | NAIP 2022 RGB+NIR, OSM, OC parcel GIS, Terner SB4 |
| **Sustainability.** Families must *keep* the home | Mortgage designer | Two-layer Monte Carlo simulate-and-optimize | HCD 2026 income limits, literature-calibrated hazards |
| **Capital.** 0% mortgages tie up money | Path-to-100 planner + market-gap model | Gradient boosting with fairness guardrail | HMDA loan-level 2022–2024 (52K OC decisions) |

All of it is run by a **hierarchy of Claude agents** (Director → Land / Family / Capital leads → Site analysts & Underwriters). The agents reach every tool through an **MCP server**, run their own analysis code in an **OS-level sandbox**, and **improve themselves** through gated champion/challenger loops. The same loop governs the CNN, the credit model and the agents' own playbooks.

See [hackathon-info/RESEARCH_BRIEF.md](hackathon-info/RESEARCH_BRIEF.md) for the evidence base (about 45 verified citations) and the prototype results.

```
                       ┌──────────── Director (Opus 5.5) ─────────────┐   progress ledger, final brief
                       │ delegate (parallel)                          │
       ┌───────────────┼──────────────────────┬───────────────────────┘
  Land lead (Opus)  Family lead (Opus)    Capital lead (Opus)
       │ delegate         │ delegate              │
  Site analysts      Underwriters (Sonnet 5.5)    │
  (Sonnet 5.5)            │                       │
       └───── MCP (stdio / Streamable HTTP) ──────┴──► Euodos MCP server: 13 tools + 2 resources
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
