"""Domain tools. One implementation, three front doors: the MCP server, the sandbox, and the offline planner.

Tool names are namespaced `<domain>_<action>` and return compact, high-signal JSON (Anthropic, "Writing effective
tools for agents", 2025). Nothing here has side effects outside artifacts/, so no tool needs a consent gate.
"""
import json

from keystone import config, research, skills
from keystone.models import capital, registry
from keystone.models import sustainability as sus

_SITES = None


def _sites():
    global _SITES
    if _SITES is None:
        _SITES = json.loads((config.DATA / "site_scores.json").read_text())
    return _SITES


def sites_search(city: str | None = None, min_units: int = 0, viable_only: bool = True, limit: int = 15) -> dict:
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


def sites_inspect(apn: str, keep_parking_share: float = 0.5) -> dict:
    """Re-run the parking CNN live on one parcel's NAIP imagery with a different parking-retention share."""
    from keystone.models.site_score import score_site
    raw = json.loads((config.DATA / "faith_sites.json").read_text())
    site = next((s for s in raw if s.get("apn") == apn), None)
    if site is None:
        return {"error": f"APN {apn} not in faith-site inventory"}
    out = score_site(site, keep_parking_share=keep_parking_share)
    return {k: v for k, v in out.items() if not k.endswith("_bounds")}


def market_gap_report(year: int = 2024) -> dict:
    """HMDA (real loan-level data): OC low-income purchase applications, denial rates and reasons for a year (2022-2024)."""
    rows = json.loads((config.DATA / "market_gap.json").read_text())
    r = next((g for g in rows if g["year"] == year), None)
    return r or {"error": "year must be 2022, 2023 or 2024", "available": [g["year"] for g in rows]}


def family_market_score(income: float, price: float, monthly_debts: float = 0.0, down_payment_share: float = 0.05) -> dict:
    """P(conventional lender denies) for an OC purchase, from the champion HMDA model. High = Habitat is needed."""
    from keystone.models import market_gap
    return market_gap.score_family(income, price, down_payment_share, monthly_debts)


def income_limits(household_size: int = 4, income: float | None = None) -> dict:
    """CA HCD 2026 Orange County income limits scaled by household size; classifies an income if given."""
    adj = config.HH_SIZE_ADJ.get(household_size, 1.0)
    limits = {k: round(v * adj, -2) for k, v in config.INCOME_LIMITS_4P.items()}
    out = {"household_size": household_size, "ami_4p": config.OC_AMI_4P, "limits": limits, "source": config.SOURCES["hcd_2026"]}
    if income is not None:
        cat = next((k for k in ("extremely_low", "very_low", "low", "moderate") if income <= limits[k]), "above_moderate")
        out["category"] = cat
        out["pct_ami"] = round(income / (config.OC_AMI_4P * adj) * 100, 1)
        out["habitat_oc_eligible_band"] = limits["extremely_low"] <= income <= limits["moderate"]
    return out


def family_simulate(income: float, household_size: int = 4, savings: float = 5000, monthly_debts: float = 300,
                    income_volatility: float = 1.0, home_value: float = 750_000, rate: float = 0.0,
                    term_years: int = 30, payment_cap: float = 0.30, reserve_fund: float = 0,
                    income_indexed: bool = False, stewardship: bool = True, n_paths: int = 2000) -> dict:
    """Monte Carlo (10y, monthly) of whether a family keeps its Habitat home under one mortgage design."""
    f = sus.Family(income, household_size, savings, monthly_debts, income_volatility)
    d = sus.Design(rate=rate, term_years=term_years, payment_cap=payment_cap, reserve_fund=reserve_fund,
                   income_indexed=income_indexed, stewardship=stewardship)
    return sus.simulate(f, sus.Home(value=home_value), d, n_paths=n_paths)


def mortgage_optimize(income: float, household_size: int = 4, savings: float = 5000, monthly_debts: float = 300,
                      income_volatility: float = 1.0, home_value: float = 750_000, min_sustain: float = 0.95) -> dict:
    """Search 108 mortgage designs for the cheapest (subsidy PV) that keeps P(sustained 10y) >= min_sustain."""
    f = sus.Family(income, household_size, savings, monthly_debts, income_volatility)
    out = sus.optimize(f, sus.Home(value=home_value), min_sustain=min_sustain)
    out["pareto_frontier"] = [{k: p[k] for k in ("design", "p_sustained_10y", "subsidy_cost")} for p in out["pareto_frontier"]]
    return out


def capital_plan(target_homes: int = 100, family_income: float = 95_000, appraised_value: float = 750_000,
                 rate: float = 0.0, term_years: int = 30, payment_cap: float = 0.30, calhome_per_unit: float = 60_000,
                 ahp_per_unit: float = 40_000, max_units_per_site: int = 30, hard_cost_per_sqft: float | None = None) -> dict:
    """Path-to-N plan: which sites, per-unit cost, capital recovered from mortgages, and the philanthropy gap."""
    if hard_cost_per_sqft:
        config.COST_ASSUMPTIONS["hard_cost_per_sqft"] = hard_cost_per_sqft
    d = sus.Design(rate=rate, term_years=term_years, payment_cap=payment_cap)
    return capital.plan(target_homes, sus.Family(income=family_income), d, appraised_value,
                        calhome=calhome_per_unit, ahp=ahp_per_unit, max_units_per_site=max_units_per_site)


def research_lookup(topic: str | None = None, query: str | None = None) -> dict:
    """Verified citations (title, URL, key finding) the agents may cite. Topics: stewardship, payment design, fairness, cv, faith land, agents, self-improvement..."""
    rows = research.lookup(topic, query)
    return {"n": len(rows), "citations": rows[:12]}


def models_registry(name: str | None = None) -> dict:
    """Champion/challenger history for parking_cnn and market_gap, with promotion decisions and reasons."""
    h = registry.history(name)
    return h if name is None else {"name": name, "history": h}


def sandbox_run_python(code: str, save_as_skill: str | None = None, skill_description: str = "",
                       skill_code: str | None = None) -> dict:
    """Run Python in an OS sandbox (no network, temp-dir writes only, no secrets). `keystone` is importable read-only.
    Use for sensitivity sweeps and custom analysis; print() what you want back. If it succeeds and save_as_skill is
    given, the code (or just `skill_code`, the reusable body without run-specific inputs) is added to the skill
    library so future runs can reuse it (Voyager-style)."""
    from keystone.sandbox.runner import run_python
    out = run_python(code, agent="mcp")
    if out["ok"] and save_as_skill:
        out["skill_saved"] = skills.save(save_as_skill, skill_code or code, skill_description)
    return out


def skills_list() -> dict:
    """Verified analysis skills (sandbox code that ran successfully before), with descriptions and use counts."""
    return {"skills": skills.index()}


def skills_get(name: str) -> dict:
    """Source of a saved skill, to run (possibly modified) with sandbox_run_python."""
    return skills.get(name)


def homekeeper_watchlist(month: int = 36, scenario: str = "keystone", limit: int = 12) -> dict:
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
         mortgage_optimize, capital_plan, research_lookup, models_registry, sandbox_run_python, skills_list, skills_get, homekeeper_watchlist, homekeeper_portfolio_summary]
BY_NAME = {f.__name__: f for f in TOOLS}
