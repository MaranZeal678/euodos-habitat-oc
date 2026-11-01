"""Domain tools. One implementation, three front doors: the MCP server, the sandbox, and the offline planner.

Tool names are namespaced `<domain>_<action>` and return compact, high-signal JSON (Anthropic, "Writing effective
tools for agents", 2025). Nothing here has side effects outside artifacts/, so no tool needs a consent gate.
"""
import json
from typing import Annotated, Literal

from pydantic import Field, validate_call

from keystone import config, research, skills
from keystone.models import capital, registry
from keystone.models import sustainability as sus

_SITES = None

# Bounds live in the signatures: pydantic enforces them on every call, and MCP publishes them in each tool's input
# schema, so an agent sees the valid range before it calls.
Income = Annotated[float, Field(ge=1_000, le=2_000_000, description="annual household income, USD (floor $1,000: below that no payment ratio is meaningful)")]
HouseholdSize = Annotated[int, Field(ge=1, le=8, description="people in the household (HUD scale 1-8)")]
Money = Annotated[float, Field(ge=0, le=20_000_000)]
HomeValue = Annotated[float, Field(ge=10_000, le=20_000_000, description="appraised home value, USD")]
Share = Annotated[float, Field(ge=0, lt=1)]
Volatility = Annotated[float, Field(ge=0, le=5, description="multiplier on job-loss risk; 1 = typical")]
Rate = Annotated[float, Field(ge=0, le=0.2, description="annual mortgage rate, e.g. 0.04")]
Term = Annotated[int, Field(ge=5, le=50)]
Cap = Annotated[float, Field(ge=0.05, le=0.8, description="housing payment as a share of gross income")]
Limit = Annotated[int, Field(ge=1, le=100)]


def _sites():
    global _SITES
    if _SITES is None:
        _SITES = json.loads((config.DATA / "site_scores.json").read_text())
    return _SITES


@validate_call
def sites_search(city: Annotated[str, Field(max_length=60)] | None = None, min_units: Annotated[int, Field(ge=0, le=10_000)] = 0,
                 viable_only: bool = True, limit: Limit = 15) -> dict:
    """Search CNN-scored faith-owned parcels (SB 4) in Orange County, largest townhome yield first."""
    rows = [s for s in _sites() if "cnn_error" not in s]
    if viable_only:
        rows = [s for s in rows if s["viable"]]
    if city:
        rows = [s for s in rows if (s.get("city") or "").lower() == city.lower()]
    rows = [s for s in rows if s["units_townhome"] >= min_units]
    keep = ["name", "city", "address", "apn", "lat", "lon", "parcel_sqm", "parking_sqm", "green_sqm",
            "developable_acres", "units_townhome", "units_sb4_cap", "religion", "denomination"]
    return {"total_matches": len(rows), "total_townhome_units": sum(s["units_townhome"] for s in rows),
            "sites": [{k: s.get(k) for k in keep} for s in rows[:limit]],
            "method": "U-Net on NAIP 2022 RGB+NIR, OSM-labelled; developable = 50% of parking + 50% of lawn; 16 du/ac townhomes"}


@validate_call
def sites_inspect(apn: Annotated[str, Field(pattern=r"^[0-9A-Za-z-]{3,20}$", description="assessor parcel number, e.g. 588-081-21")],
                  keep_parking_share: Annotated[float, Field(ge=0, le=0.95)] = 0.5) -> dict:
    """Re-run the parking CNN live on one parcel's NAIP imagery with a different parking-retention share."""
    from keystone.models.site_score import score_site
    raw = json.loads((config.DATA / "faith_sites.json").read_text())
    site = next((s for s in raw if s.get("apn") == apn), None)
    if site is None:
        return {"error": f"APN {apn} not in faith-site inventory"}
    try:
        out = score_site(site, keep_parking_share=keep_parking_share)
    except Exception as e:  # noqa: BLE001 - imagery is remote; without it, fall back to the stored offline scan
        stored = next((s for s in _sites() if s.get("apn") == apn and "cnn_error" not in s), None)
        if stored is None:
            return {"error": f"live imagery unavailable ({type(e).__name__}) and no stored scan for APN {apn}"}
        return {**stored, "live_rescan": f"unavailable ({type(e).__name__}); stored offline scan at 50% parking kept",
                "keep_parking_share": 0.5}
    return {k: v for k, v in out.items() if not k.endswith("_bounds")}


@validate_call
def market_gap_report(year: Annotated[int, Field(ge=2018, le=2030)] = 2024) -> dict:
    """HMDA (real loan-level data): OC low-income purchase applications, denial rates and reasons for a year (2022-2024)."""
    rows = json.loads((config.DATA / "market_gap.json").read_text())
    r = next((g for g in rows if g["year"] == year), None)
    return r or {"error": "year must be 2022, 2023 or 2024", "available": [g["year"] for g in rows]}


@validate_call
def family_market_score(income: Income, price: HomeValue, monthly_debts: Money = 0.0, down_payment_share: Share = 0.05) -> dict:
    """P(conventional lender denies) for an OC purchase, from the champion HMDA model. High = Habitat is needed."""
    from keystone.models import market_gap
    return market_gap.score_family(income, price, down_payment_share=down_payment_share, monthly_debts=monthly_debts)


@validate_call
def income_limits(household_size: HouseholdSize = 4, income: Income | None = None) -> dict:
    """CA HCD 2026 Orange County income limits scaled by household size; classifies an income if given."""
    adj = config.HH_SIZE_ADJ[household_size]
    limits = {k: round(v * adj, -2) for k, v in config.INCOME_LIMITS_4P.items()}
    out = {"household_size": household_size, "ami_4p": config.OC_AMI_4P, "limits": limits, "source": config.SOURCES["hcd_2026"]}
    if income is not None:
        cat = next((k for k in ("extremely_low", "very_low", "low", "moderate") if income <= limits[k]), "above_moderate")
        out["category"] = cat
        out["pct_ami"] = round(income / (config.OC_AMI_4P * adj) * 100, 1)
        out["habitat_oc_eligible_band"] = limits["extremely_low"] <= income <= limits["moderate"]
    return out


@validate_call
def family_simulate(income: Income, household_size: HouseholdSize = 4, savings: Money = 5000, monthly_debts: Money = 300,
                    income_volatility: Volatility = 1.0, home_value: HomeValue = 750_000, rate: Rate = 0.0,
                    term_years: Term = 30, payment_cap: Cap = 0.30, reserve_fund: Money = 0,
                    income_indexed: bool = False, stewardship: bool = True,
                    n_paths: Annotated[int, Field(ge=100, le=10_000)] = 2000) -> dict:
    """Monte Carlo (10y, monthly) of whether a family keeps its Habitat home under one mortgage design."""
    f = sus.Family(income, household_size, savings, monthly_debts, income_volatility)
    d = sus.Design(rate=rate, term_years=term_years, payment_cap=payment_cap, reserve_fund=reserve_fund,
                   income_indexed=income_indexed, stewardship=stewardship)
    return sus.simulate(f, sus.Home(value=home_value), d, n_paths=n_paths)


@validate_call
def mortgage_optimize(income: Income, household_size: HouseholdSize = 4, savings: Money = 5000, monthly_debts: Money = 300,
                      income_volatility: Volatility = 1.0, home_value: HomeValue = 750_000,
                      min_sustain: Annotated[float, Field(ge=0.5, le=0.999)] = 0.95) -> dict:
    """Search 108 mortgage designs for the cheapest (subsidy PV) that keeps P(sustained 10y) >= min_sustain."""
    f = sus.Family(income, household_size, savings, monthly_debts, income_volatility)
    out = sus.optimize(f, sus.Home(value=home_value), min_sustain=min_sustain)
    out["pareto_frontier"] = [{k: p[k] for k in ("design", "p_sustained_10y", "subsidy_cost")} for p in out["pareto_frontier"]]
    return out


@validate_call
def capital_plan(target_homes: Annotated[int, Field(ge=1, le=5_000)] = 100, family_income: Income = 95_000,
                 appraised_value: HomeValue = 750_000, rate: Rate = 0.0, term_years: Term = 30, payment_cap: Cap = 0.30,
                 reserve_fund: Money = 0, calhome_per_unit: Money = 60_000, ahp_per_unit: Money = 40_000,
                 max_units_per_site: Annotated[int, Field(ge=1, le=500)] = 30,
                 hard_cost_per_sqft: Annotated[float, Field(gt=0, le=2_000)] | None = None) -> dict:
    """Path-to-N plan: which sites, per-unit cost, capital recovered from mortgages, and the philanthropy gap."""
    cost = dict(config.COST_ASSUMPTIONS)  # per-call copy: an override must never leak into later requests
    if hard_cost_per_sqft is not None:
        cost["hard_cost_per_sqft"] = hard_cost_per_sqft
    d = sus.Design(rate=rate, term_years=term_years, payment_cap=payment_cap, reserve_fund=reserve_fund)
    return capital.plan(target_homes, sus.Family(income=family_income), d, appraised_value,
                        calhome=calhome_per_unit, ahp=ahp_per_unit, max_units_per_site=max_units_per_site, cost_inputs=cost)


@validate_call
def research_lookup(topic: Annotated[str, Field(max_length=60)] | None = None,
                    query: Annotated[str, Field(max_length=200)] | None = None) -> dict:
    """Verified citations (title, URL, key finding) the agents may cite. Topics: stewardship, payment design, fairness, cv, faith land, agents, self-improvement..."""
    rows = research.lookup(topic, query)
    return {"n": len(rows), "citations": rows[:12]}


@validate_call
def models_registry(name: Annotated[str, Field(max_length=80)] | None = None) -> dict:
    """Champion/challenger history for parking_cnn and market_gap, with promotion decisions and reasons."""
    h = registry.history(name)
    return h if name is None else {"name": name, "history": h}


@validate_call
def sandbox_run_python(code: Annotated[str, Field(min_length=1, max_length=50_000)],
                       save_as_skill: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,59}$")] | None = None,
                       skill_description: Annotated[str, Field(max_length=500)] = "",
                       skill_code: Annotated[str, Field(max_length=50_000)] | None = None) -> dict:
    """Run Python in an OS sandbox (no network, temp-dir writes only, no secrets). `keystone` is importable read-only.
    Use for sensitivity sweeps and custom analysis; print() what you want back. If it succeeds and save_as_skill is
    given, the code (or just `skill_code`, the reusable body without run-specific inputs) is added to the skill
    library so future runs can reuse it (Voyager-style)."""
    from keystone.sandbox.runner import run_python
    if save_as_skill and skill_code is not None and skill_code not in code:
        return {"ok": False, "stdout": "", "stderr": "skill_code must be part of the code that runs, so a saved skill has run"}
    out = run_python(code, agent="mcp")
    if out["ok"] and save_as_skill:
        saved = skills.save(save_as_skill, skill_code or code, skill_description)
        out["skill_saved" if saved else "skill_not_saved"] = save_as_skill if saved else \
            f"a different skill named {save_as_skill} already exists; pick a new name"
    return out


def skills_list() -> dict:
    """Verified analysis skills (sandbox code that ran successfully before), with descriptions and use counts."""
    return {"skills": skills.index()}


@validate_call
def skills_get(name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,59}$")]) -> dict:
    """Source of a saved skill, to run (possibly modified) with sandbox_run_python."""
    return skills.get(name)


@validate_call
def homekeeper_watchlist(month: Annotated[int, Field(ge=0, le=119)] = 36,
                         scenario: Literal["market", "standard", "keystone"] = "keystone", limit: Limit = 12) -> dict:
    """HomeKeeper: homeowners stressed, behind, or 90+ days late at a month (0-119) of the 10-year portfolio, with the
    shocks behind it and the Steward's recommended action. Portfolio families are synthetic (incomes sampled from HMDA)."""
    from keystone.models import homekeeper
    return homekeeper.watchlist(month, scenario, limit)


def homekeeper_portfolio_summary() -> dict:
    """HomeKeeper: 10-year outcomes for the 100-family portfolio under market, standard Habitat, and Keystone regimes."""
    data = json.loads((config.ROOT / "keystone" / "app" / "static" / "demo" / "portfolio.json").read_text())
    return {"scenarios": data["scenarios"], "summary": data["summary"], "n_families": len(data["families"]),
            "note": "synthetic families; incomes sampled from 2024 HMDA OC applicants within Habitat OC's 30-80% AMI band"}


TOOLS = [sites_search, sites_inspect, market_gap_report, family_market_score, income_limits, family_simulate,
         mortgage_optimize, capital_plan, research_lookup, models_registry, sandbox_run_python, skills_list, skills_get,
         homekeeper_watchlist, homekeeper_portfolio_summary]
BY_NAME = {f.__name__: f for f in TOOLS}
