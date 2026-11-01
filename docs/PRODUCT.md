# Keystone: product strategy

> **Keystone is the operating system for nonprofit homeownership.** It finds buildable land, designs mortgages families can keep, and keeps them in their homes. A team of AI agents does the work, and a five-person affiliate staff supervises it.

From parking lot to front door, and keeping families there.

---

## 1. The customer and the pain

**Buyer:** the executive director of a Habitat for Humanity affiliate. Affiliates operate in all 50 states, DC and Puerto Rico ([habitat.org](https://www.habitat.org/where-we-build/united-states)).
**Expansion:** the 314 community land trusts and shared-equity programs in 46 states ([2022 CLT census, UW summary](https://research.be.uw.edu/2023/07/06/publication-of-the-largest-national-study-on-community-land-trusts-and-nonprofits-with-shared-equity-homeownership-programs)), plus the CDFIs that lend to them.

| Job | Today | With Keystone |
|---|---|---|
| Find land | Staff relationships and driving around. Habitat OC lists "acquire land" as a strategic goal | **Land Radar** scans every faith-owned parcel in the county with a CNN and returns a ranked list with a site plan and units |
| Qualify and underwrite families | Spreadsheets and a fixed 30% rule | **Mortgage Designer** finds the cheapest loan structure that keeps P(still owning at year 10) ≥ 95% |
| Keep families housed | Reactive: staff hear about trouble at 60–90 days late | **HomeKeeper** and the **Steward agent** flag families before the first missed payment, with a workout for each |
| Raise the money | Grant writing by hand | **Capital Planner** sizes the gap per home and drafts the CalHome and AHP packets |

The evidence for the product shape: stewarded resale-restricted loans run at 1.3% serious delinquency against 8.6% in the market ([Thaden 2011](https://www.lincolninst.edu/publications/working-papers/stable-home-ownership-turbulent-economy/)), and payment size, not equity, drives default ([Ganong & Noel 2020](https://doi.org/10.1257/aer.20181243)). Software that makes stewardship cheap and early is the lever.

## 2. Wedge: faith land
- **Why land first.** Land is what a board and a CEO lose sleep over, and it is the most visual result. In the demo, a church parking lot turns into a village of 30 townhomes.
- **Where.** California's SB 4 makes congregation land buildable by right. In Orange County that is 1,907 developable faith-owned acres ([Terner](https://github.com/Terner-Center/SB4-Analysis)).
- **Next markets.** Florida enacted its own YIGBY provision in SB 1730 (2025), and bills have been introduced in about ten more states ([Nat. Law Review](https://natlawreview.com/article/floridas-live-local-act-and-yigby-form-unified-affordable-housing-strategy)). Each new state is one region pack (`keystone/regions/<id>.json`), not new code.
- **The land funnel feeds HomeKeeper.** Every home Keystone sites becomes a home Keystone stewards. HomeKeeper is the recurring relationship.

## 3. Product surface
| Module | What ships | AI under the hood |
|---|---|---|
| **Land Radar** | Ranked parcel list, CNN scan, generated site plan, congregation outreach letter | U-Net CNN on NAIP RGB+NIR imagery; lattice site planner; Land lead and Site-analyst agents |
| **Mortgage Designer** | Term sheet per family: rate, term, cap, income-indexed reset, reserve | Two-layer Monte Carlo optimizer; Underwriter agents stress-test designs in the sandbox |
| **HomeKeeper** | Portfolio watchlist, early-warning alerts, workout playbooks, outreach drafts | Steward agent; event-driven risk states; human approves every message |
| **Capital Planner** | Per-home waterfall, sensitivity range, funding stack, application drafts | HMDA demand model (fairness-gated); Capital lead agent |
| **Agent Console + MCP** | Mission control, traces, grades, registry; the MCP endpoint plugs Keystone into Claude Desktop, Claude Code or any MCP host | Director → leads → workers hierarchy; graders; self-improvement gate |

## 4. Business model (hypotheses to test in the pilot)
- **Affiliate SaaS**, priced by homes under stewardship so small affiliates pay little. *Hypothesis:* $6k–$24k per affiliate per year. Free for affiliates building fewer than 10 homes a year, as a mission tier funded by a foundation partner.
- **HomeKeeper for lenders and CDFIs** that hold affordable-ownership loans: *hypothesis* $5–$10 per loan per month. It is cheaper than a single foreclosure.
- **State-level licenses** for Habitat state support organizations and housing finance agencies, which onboard many affiliates at once.
- **Cost to serve.** Claude usage per mission still needs to be measured in the pilot; the hierarchy already logs tokens per run. Workers run on Sonnet 5.5 and leads on Opus 5.5, and fixed workflows replace agents wherever the path is known.

## 5. Moat: the loop gets better with every affiliate
1. **Outcome data.** No public data on Habitat loan performance exists. Every affiliate on HomeKeeper adds real delinquency, cure and buyback outcomes. These recalibrate the sustainability model through the same champion/challenger gate already running on HMDA data. Better predictions draw more affiliates, which produce more data.
2. **Region packs.** Parcel schemas, income limits and land-use law, verified once and reused by every affiliate in that county.
3. **Trust.** Agents propose and gates decide. Every number is sourced or labelled an assumption, every citation is checked, and every run is graded and logged. Lenders and boards can audit it.

## 6. Responsible AI and compliance (built in, not bolted on)
- **Keystone never makes a credit decision.** It recommends; staff decide. Adverse-action reasons come from interpretable drivers (ECOA / Reg B).
- **Fairness.** Protected attributes are excluded from features. A challenger model that widens the race-group calibration gap is blocked ([Fuster et al. 2022](https://doi.org/10.1111/jofi.13090)).
- **Homeowner privacy.** Homeowner data stays in the affiliate's deployment. The Steward drafts outreach, and nothing is sent without a person approving it and the homeowner having opted in.
- **Agent safety.** Least-privilege tool sets per agent. Tool output is treated as data, not instructions. MCP requires a bearer token. Agent code runs in an OS sandbox with no network or secrets, and every run is audit-logged.

## 7. Architecture and deployment
- **One container** serves the dashboard (`/`), the demo (`/demo`), the REST API (`/api`) and the MCP server (`/mcp`, Streamable HTTP with bearer auth). The ingestion pipeline (`python -m keystone.pipeline`) turns a region config into scored sites, trained models and demo assets, idempotently.
- **Deploy:** `docker build` → Render (`render.yaml`) or any container host. `KEYSTONE_REGION` selects the market. Set `ANTHROPIC_API_KEY` for live agents; without it the scripted policy runs the same pipeline.
- **Sandbox in production:** Linux bubblewrap ships in the image, but some hosts block user namespaces. On those, route agent code to Anthropic's code execution tool (no network, managed container) or a Firecracker microVM.

## 8. Roadmap
| When | Milestone | Proof point |
|---|---|---|
| 0–90 days | Pilot with Habitat OC: title-check the top 10 sites, open 4 congregation conversations, load the servicing history | Simulator recalibrated on real outcomes; first site LOI |
| 3–6 months | HomeKeeper live for existing homeowners (opt-in check-ins); LLM zoning reader for OC's 34 cities; fire and flood screens | Early-warning recall measured against actual delinquencies |
| 6–12 months | Florida and LA County region packs; multi-tenant SaaS; SOC 2 readiness; Freddie Mac loan-level pretraining | 5 affiliates, 1 lender customer |

## 9. KPIs
Homes sited → entitled → built · P(sustained) calibration error · 90+ day delinquency against the affiliate's baseline · days of warning before the first missed payment · staff hours per intervention · grant dollars won · agent pass^k on the eval suite.

## 10. Risks and honest answers
- **"Will congregations say yes?"** Unknown, and that is the pilot's first test. The product ranks sites and drafts the ask; humans build the relationship. Terner's SB 9 review is a caution: feasibility is not delivery ([Terner](https://ternercenter.berkeley.edu/?p=3232)).
- **"Your default model is made up."** Its hazard rates are literature-calibrated assumptions, labelled as such. Recalibrating on the affiliate's own servicing data is the first pilot deliverable, and the gate decides when the new model ships.
- **"The 100 families are synthetic."** Yes. Their incomes are sampled from real 2024 HMDA applicants within Habitat OC's published eligibility band, and their life shocks come from the simulator. They show the mechanism, not a forecast.
- **"Why agents and not a spreadsheet?"** Fixed workflows run wherever the path is known. Agents handle the open-ended parts: site verification, stress tests and drafting. Every run is graded, and the graders caught real failures (a single-site plan, an unrun sensitivity analysis) that the agents then learned to avoid.

---

## Demo script (`/demo?autoplay`, about 2:15; recorded copy at `docs/keystone_demo.mp4`)
1. **0:00 · Orange County.** The county outline lights up over the LA basin. On screen: median home $1.48M, AMI $138,600, 24% of low-income buyers denied in 2024, and only 2,719 of the 46,416 very-low-income units in OC's RHNA target reported so far. Then Habitat OC itself: 239 homes since 1988, Keys to 100.
2. **0:20 · Act 1, Find the land.** Columns rise as the CNN scores 305 faith-owned OC parcels: room for 2,696 townhomes across 33 OC cities (Anaheim 19 sites, Orange 15, Irvine 14, Westminster 14…). The camera flies to Crossline Church in Laguna Hills, the scan paints the parking lot teal, and 30 townhomes rise. Mariners (Irvine), Needham Chapel (Costa Mesa) and Friends Church (Yorba Linda) follow, and the counter passes 100. *Talking point: real NAIP imagery, real OC parcels, real model output, not a mock-up.*
3. **1:05 · Act 2, Keep families home.** 100 Orange County families at 30–80% of AMI live 10 years three ways. Red rings mark layoffs and blue rings mark the Steward reaching out. Year 10: 58 still home with market loans, 80 with a standard 0% loan, 87 with Keystone.
4. **1:48 · Act 3, Fund and ship.** Who pays for a $539k OC townhome; the $16.3M gap, with the $330K Keys to 100 gala for scale; congregation letters for Laguna Hills, Irvine, Costa Mesa and Yorba Linda. The final card reads "Built for Habitat for Humanity of Orange County."
5. **Agent rail, throughout.** A replay of a real graded run: every MCP call each agent made.

Controls: space pauses, ← and → change scene, R restarts. To re-record the video: `make serve`, then `.venv/bin/python scripts/record_demo.py`.
