# Keystone: research brief

**UCI Paul Merage School of Business Center for Real Estate × Habitat for Humanity of Orange County Impact Lab**
Prepared 2026-10-31. Every external fact below links to a source that was opened and checked. Model inputs that aren't sourced are labelled **assumption**.

---

## 1. The problem in numbers

| Metric | Value | Source |
|---|---|---|
| Habitat OC goal | 100 homes ("Keys to 100"), launched Nov 2024 as a three-year goal | [PR Newswire](https://prnewswire.com/news-releases/habitat-for-humanity-oc-celebrates-inaugural-keys-to-100-gala-302312178.html) |
| Habitat OC homes built since 1988 | 239 | same |
| 2026 Keys to 100 gala | raised $330,000; six families moving into West Washington Ave, Santa Ana | [Habitat OC](https://habitatoc.org/keys-to-100-raises-330000-for-affordable-homeownership-in-orange-county/) |
| OC median existing single-family price | $1,480,000 (Sept 2026, +5.6% YoY) | [C.A.R.](https://www.car.org/aboutus/mediacenter/newsreleases/2026releases/sept2026sales) |
| 30-yr fixed rate | 6.86% (Sept 2026 average) | same |
| OC Area Median Income (4-person) | $138,600 (2026) | [CA HCD](https://www.hcd.ca.gov/sites/default/files/docs/grants-and-funding/income-limits-2026.pdf) |
| OC 4-person limits | Very Low $93,050 · Low $148,850 · Moderate $166,300 | same |
| Habitat OC buyer terms | payments capped ~30–35% of income; 1–5% down; 200–500 sweat-equity hours | [Habitat OC](https://habitatoc.org/myths-facts/), [qualifications](https://habitatoc.org/review-qualifications) |
| OC RHNA 6th cycle | 183,861 units; **very-low-income progress 5.9%**, total ~15.5% (HCD data, updated 2026-10-30) | [SCAG](https://sp.scag.ca.gov/sites/default/files/2024-05/6th_cycle_final_rhna_allocation_plan_070121.pdf), [data.ca.gov](https://data.ca.gov/dataset/rhna-progress-report) |
| OC low-income purchase denials | **24% of ≤80% AMI applicants denied in 2024; 59% of those for debt-to-income** (Keystone analysis of HMDA loan-level data) | [FFIEC HMDA](https://ffiec.cfpb.gov/data-browser/) |
| Faith-owned developable land in OC | 1,907 acres on 707 parcels, median 1.6 acres | [Terner Center SB4 data](https://github.com/Terner-Center/SB4-Analysis) |

**The core insight.** The market already shows that low-income OC families fail on *monthly cash flow*, since DTI is the leading denial reason. The research shows that cash flow, not equity, is what makes ownership last. Keystone is designed around that.

---

## 2. What the literature says, and the design choice each finding drives

### A. Sustainability of low-income ownership
- **Thaden (2011), Lincoln Institute.** CLT loans were 1.30% seriously delinquent vs 8.57% (MBA). 82% of seriously delinquent CLT owners kept the home or sold with help. [link](https://www.lincolninst.edu/publications/working-papers/stable-home-ownership-turbulent-economy/). **Design:** the simulator includes a steward that detects 90+ DPD early and cures 82% of cases. The steward is a switch, so its value can be measured.
- **Chun et al. (2026), Habitat Wealth Building Project, WashU / HFHI.** Over 2,000 Habitat owners gained +22 credit points, and those with post-purchase education held about $5,000 more liquid assets by year 6. Not peer reviewed. [link](https://doi.org/10.7936/w9p5-s022). **Design:** liquid buffers are a tracked outcome.
- **Ganong & Noel (2020), AER.** Payment reductions cut default; principal cuts with unchanged payments did not. [link](https://doi.org/10.1257/aer.20181243). **Design:** the optimizer searches *payment* structure, including income-indexed payments.
- **Fuster & Willen (2017), AEJ: Policy.** Halving the payment cuts the delinquency hazard by about 55%. [link](https://doi.org/10.1257/pol.20150007)
- **Tian, Quercia & Riley (2016), JREFE.** Unemployment is the adverse trigger, and savings moderate it. [link](https://doi.org/10.1007/s11146-015-9501-8). **Design:** job loss is the shock process; the reserve fund is a design lever.
- **Ge, Johnson & Tzur-Ilan (Dallas Fed WP 2505).** Insurance-premium increases raise delinquency among constrained households. [link](https://doi.org/10.24149/wp2505r1). **Design:** stochastic insurance shocks in every path.
- **Goodman, Seidman & Zhu (2014), Urban Institute.** The VA residual-income test helps explain lower VA defaults. [link](https://www.urban.org/research/publication/va-loans-outperform-fha-loans-why-and-what-can-we-learn)
- **Ding et al. (2011), JRER.** Product design drives default as much as borrower traits. [link](https://doi.org/10.1080/10835547.2011.12091305)
- **Temkin, Theodos & Price (2010); Theodos et al. (2019).** Shared-equity homes stay affordable, with low delinquency. [Urban](https://www.urban.org/research/publication/balancing-affordability-and-opportunity-evaluation-affordable-homeownership-programs-long-term-affordability-controls), [HPD](https://doi.org/10.1080/10511482.2019.1596965)
- **Reid (2005).** More than half of low-income first-time buyers returned to renting within five years. [link](https://doi.org/10.7936/K71J998S). This is the problem Keystone targets: ownership that *lasts*, not closings.

### B. ML credit risk and fairness
- **Sirignano, Sadhwani & Giesecke (2021), JFEC.** Deep multi-state mortgage model on 120 million loans. [link](https://arxiv.org/abs/1607.02470)
- **Fuster, Goldsmith-Pinkham, Ramadorai & Walther (2022), J. Finance, "Predictably Unequal?"** ML can widen racial disparities. [link](https://doi.org/10.1111/jofi.13090). **Design:** protected attributes are excluded from features, and a fairness-gap guardrail blocks promotion.
- **Bartlett, Morse, Stanton & Wallace (2022), JFE.** Algorithmic lenders discriminate about 40% less than face-to-face lenders, but pricing disparities persist. [link](https://doi.org/10.1016/j.jfineco.2021.05.047)
- **Blattner & Nelson (2021).** Thin-file noise drives approval gaps. [link](https://arxiv.org/abs/2105.07554). **Di Maggio et al. (2022), "Invisible Primes".** [link](https://doi.org/10.3386/w29840). **Next step:** add alternative data such as rent and utility payments.

### C. Computer vision for land and housing
- **Jo, Vallebueno, Ouyang & Ho (2025), JAPA.** CV on NAIP imagery finds about 3–4 unpermitted ADUs per permitted ADU in San José, with code and data released. [link](https://doi.org/10.1080/01944363.2024.2345730)
- **Qiam, Devunuri & Lehe (2024).** Near-infrared improves parking-lot segmentation (84.9% mIoU). [link](https://arxiv.org/abs/2412.13179). **Design:** the Keystone U-Net takes RGB + NIR + NDVI.
- **Jun et al. (2024), Cities.** Deep learning detects 3,710 LA infill projects. [link](https://doi.org/10.1016/j.cities.2024.105019). **Jean et al. (2016), Science.** Transfer from cheap proxy labels. [link](https://doi.org/10.1126/science.aaf7894). **Law et al. (2019).** Imagery-based valuation. [link](https://arxiv.org/abs/1807.07155)
- **Gap:** no published CV study targets affordable-ownership site selection in Orange County. Keystone fills it.

### D. Land supply and feasibility
- **Terner Center (2023), faith-based and college land.** About 171,000 developable acres statewide under SB 4. [link](https://ternercenter.berkeley.edu/research-and-policy/faith-based-and-college-land-housing/)
- **SB 4 (Gov. Code §65913.16).** By-right approval. In a metropolitan county like OC, minimum density is 30 du/ac in residential zones and 40 du/ac in non-residential zones. Ownership units carry a 45-year deed restriction. [HCD fact sheet](https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/aff-hsg-faith-higher-ed-sb-4.pdf)
- **Terner SB 9 one-year review.** Theoretical feasibility is far above delivery (LA approved 38 of 211 unit applications). [link](https://ternercenter.berkeley.edu/?p=3232). **Design:** Keystone verifies sites, applies a buffer, and caps units per site.
- **Bartik, Gupta & Milo (2026).** LLMs read zoning codes with 96% agreement with human coders. [link](https://conference.nber.org/conf_papers/f233049.pdf). **Next step:** a zoning-reader agent for OC's 34 cities.
- **Welfare exemption (RTC 214.15 / 214.15.1).** [BOE LTA 2023/044](https://www.boe.ca.gov/proptaxes/pdf/lta23044.pdf). **CalHome** [link](https://www.hcd.ca.gov/funding/hosn). **FHLBank SF AHP** [link](https://www.fhlbsf.com/products/community-programs-grants/ahp)

### E. Simulation
- **Ardon et al. (2024), ICAIF.** A two-layer simulator plus optimizer for designing mortgage-assistance products. [link](https://arxiv.org/abs/2411.00563). This is the architecture of Keystone's sustainability engine.
- **Garg et al. (2024)** [link](https://arxiv.org/abs/2402.17932) · **Geanakoplos et al. (2012), AER** [link](https://doi.org/10.1257/aer.102.3.53) · **Follain & Giertz (2011)** [link](https://ideas.repec.org/a/eee/jhouse/v20y2011i2p101-119.html)

### F. Agent architecture
- **Anthropic (2025), multi-agent research system.** Lead agent plus parallel subagents; +90.2% over a single agent. [link](https://www.anthropic.com/engineering/multi-agent-research-system)
- **Anthropic (2024), Building effective agents** [link](https://www.anthropic.com/engineering/building-effective-agents) · **Magentic-One** (orchestrator with a progress ledger) [link](https://arxiv.org/abs/2411.04468)
- **MCP spec 2026-07-28** [link](https://modelcontextprotocol.io/specification/latest) · **MCP tool-poisoning threat model** [link](https://arxiv.org/abs/2603.22489) · **Code execution with MCP** [link](https://www.anthropic.com/engineering/code-execution-with-mcp)
- **Sandboxing:** OS-level filesystem and network isolation [link](https://www.anthropic.com/engineering/claude-code-sandboxing)
- **Self-improvement:** Reflexion [link](https://arxiv.org/abs/2303.11366) · Voyager [link](https://arxiv.org/abs/2305.16291) · DSPy [link](https://arxiv.org/abs/2310.03714) · Darwin Gödel Machine [link](https://arxiv.org/abs/2505.22954) · AlphaEvolve [link](https://arxiv.org/abs/2506.13131) · **validation-gated promotion** (Lim et al. 2026) [link](https://arxiv.org/abs/2606.03321)
- **Evals:** τ-bench [link](https://arxiv.org/abs/2406.12045) · Anthropic, Demystifying evals for AI agents [link](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

---

## 3. Datasets actually used in the prototype

| Dataset | Volume used | Access |
|---|---|---|
| HMDA loan-level, OC home purchases 2022–2024 | 97,857 application rows → 52,075 owner-occupied first-lien decisions | FFIEC Data Browser API, no key |
| OC Public Works legal-lot parcels | 317 faith parcels joined live (of 987,692 total) | ArcGIS FeatureServer, no key |
| OpenStreetMap | 473 place-of-worship polygons; 7,753 surface parking polygons | Overpass API |
| NAIP 0.6 m RGB+NIR imagery (2022) | 680 training chips + full-parcel windows for 305 parcels | Microsoft Planetary Computer STAC |
| Terner Center SB4 analysis | OC county totals (validation) | GitHub |
| CA HCD 2026 income limits, C.A.R., HCD SB 4 / SB 9 / AB 2011 / Surplus Land Act fact sheets, BOE LTA 2023/044, CDI FAIR Plan release | constants and rules | cached in `data/raw/source_docs/` |

---

## 4. Prototype results (reproducible with the commands in README)

- **Land.** The parking U-Net reaches holdout IoU 0.54 and pixel accuracy 0.85 against noisy OSM labels. It scored 305 OC faith parcels; **166 are viable, with capacity for about 2,700 for-sale townhomes**. That assumes 50% of parking is retained (an assumption) and 16 du/ac, well under SB 4's 30 du/ac floor. Even at 70% parking retention, the top four sites alone hold more than 100 homes.
- **Families.** For a $92,000 family of four, the optimizer picks a 4% / 40-year / 35%-cap income-indexed design: **99.2% probability of keeping the home for 10 years**, against 85.6% for a market-rate first mortgage without stewardship, at a subsidy PV of about $153k.
- **Capital.** At $375/sf hard cost (assumption) and a 0% first mortgage valued at a 5% discount rate, the gap is about $164k per home after an assumed $100k per home of CalHome + AHP, or about $16.4M for 100 homes. The sandbox sweep shows a range of $5.9M–$26.4M across hard cost ($325–425/sf) and discount rate (4–6%).
- **Self-improving models.** On real data, the HMDA market-gap model was retrained as each new year arrived (2022 → 2023 → 2024). A challenger is promoted only if the 95% bootstrap interval of its AUC gain on the newest year clears the threshold *and* its calibration gap is not significantly wider. The 2022+2023 model was promoted (AUC 0.761 → 0.779, gain CI +0.010 to +0.026); a 2023-only challenger (0.782) was rejected because its gain sat inside the noise. Measured on every race and ethnicity group with 100+ applicants, the champion's largest calibration gap is 6.9 points, for Black applicants, which an earlier 300-applicant cut-off had hidden. Habitat should treat the denial score as a screening aid, not a decision.

## 5. Limits we state openly
- No public Habitat loan-performance data exists, so hazard parameters are literature-guided **assumptions**. The fix is to calibrate on Habitat OC's own servicing data (see next steps).
- OSM parking labels are incomplete, so the CNN is weakly supervised. OSM "place of worship" does not prove faith ownership. Every site needs a title check, a fire-hazard and flood screen (SB 4 exclusions), and a congregation conversation.
- HMDA has no loan performance. It measures *access* (denials), not sustainability.

## 6. Next steps
1. Calibrate the simulator on Habitat OC's servicing history (delinquencies, cures, buybacks).
2. Add CAL FIRE FHSZ and FEMA flood layers to screen sites against SB 4 exclusions, and an LLM zoning-reader for local height and density.
3. Pretrain the default model on the Freddie Mac loan-level dataset (registration needed) and fine-tune it to Habitat's portfolio.
4. Hand-label 300 OC parking chips to replace weak labels, and add a counting head for parking stalls.
5. Pilot the Steward agent: monthly cash-buffer check-ins with consenting homeowners.
