"""The Crossline Church scenario: one land offer run end to end, the product's 90-second demo (Lane 2, Clear it).

A congregation in Laguna Hills offers part of its parking lot. Euodos answers "how do we turn four years into two?"
for the 30 homes it fits: the site is screened in minutes, SB 4 replaces discretionary approval, and the funding
package and family pre-qualification start on day one instead of after approval. The same run shows which families
need Habitat, which mortgages they can keep for 10 years, and who closes the capital gap.

  python -m keystone.scenario        # rebuild the seed (needs the raw 2024 HMDA file under data/raw/)

The seed (households, their optimized designs and one simulated decade each) is precomputed and shipped, so every
beat renders instantly offline. An edit recomputes only what it touches. Counts are expected values (the sum of each
household's probability over 1,500 simulated decades); the animated decade is labelled as one draw.
"""
import copy
import json

from keystone import config, tools
from keystone.models import capital as capital_model
from keystone.models import pathways, timeline
from keystone.models import sustainability as sus

DEMO = config.ROOT / "keystone" / "app" / "static" / "demo"
SEED = DEMO / "scenario_seed.json"
APN = "588-081-21"  # Crossline Church, Laguna Hills: the land offer
HOME_VALUE = 750_000
N_HOMES = 30
REGIMES = ("market", "standard", "keystone")
STANDARD = {"rate": 0.0, "term_years": 30, "payment_cap": 0.30, "stewardship": False}  # homekeeper's "standard"


def _designs(best):
    return {"market": sus.Design(rate=config.MARKET_30Y_RATE, payment_cap=0.45, stewardship=False, restricted_assessment=False),
            "standard": sus.Design(**STANDARD),
            "keystone": sus.Design(**best)}


def household(name, f, i, decade=True):
    """Everything the scenario shows about one household, from the existing tools and models."""
    lim = tools.income_limits(household_size=f.household_size, income=f.income)
    market = tools.family_market_score(income=f.income, price=HOME_VALUE, monthly_debts=f.monthly_debts)
    opt = sus.optimize(f, sus.Home(value=HOME_VALUE))
    best = opt["best"]["design_params"]
    rec = {"name": name, "income": round(f.income), "household_size": f.household_size, "savings": f.savings,
           "monthly_debts": f.monthly_debts, "income_volatility": f.income_volatility,
           "pct_ami": lim["pct_ami"], "band": lim["category"], "p_denied": market["p_denied"],
           "design": opt["best"]["design"], "design_params": best, "meets_target": opt["meets_target"],
           "subsidy": opt["best"]["subsidy_cost"], "p": {}, "decade": {}}
    for k, d in _designs(best).items():
        rec["p"][k] = sus.simulate(f, sus.Home(value=HOME_VALUE), d, n_paths=1500)["p_sustained_10y"]
        if decade:  # one simulated decade per regime, same shocks across regimes (common random numbers)
            r = sus.simulate(f, sus.Home(value=HOME_VALUE), d, n_paths=1, seed=2000 + i, record=True)
            rec["decade"][k] = {"states": "".join(map(str, r["states"][:, 0].tolist())),
                                "steward": [int(m) for m, e in enumerate(r["events"][:, 0]) if e & sus.EV_STEWARD]}
    return rec


def _family(h):
    return sus.Family(income=h["income"], household_size=h["household_size"], savings=h["savings"],
                      monthly_debts=h["monthly_debts"], income_volatility=h["income_volatility"])


def capital(households, hard_cost_per_sqft=None, calhome=60_000, ahp=40_000):
    """Who closes the gap, household by household: each home is underwritten on its own family's design (Euodos)
    or on a standard 0% loan, and only shortfalls count toward philanthropy (one family's surplus pays no one else's)."""
    cost_inputs = dict(config.COST_ASSUMPTIONS)
    if hard_cost_per_sqft is not None:
        cost_inputs["hard_cost_per_sqft"] = hard_cost_per_sqft
    out = {}
    for label, pick in (("keystone", lambda h: sus.Design(**h["design_params"])), ("standard", lambda h: sus.Design(**STANDARD))):
        tot = {"homes": len(households), "cost": 0, "mortgage_capital": 0, "down_payments": 0, "calhome": 0, "ahp": 0,
               "philanthropy": 0, "surplus_homes": 0}
        for h in households:
            p = capital_model.plan(1, family=_family(h), design=pick(h), appraised_value=HOME_VALUE, calhome=calhome,
                                   ahp=ahp, sites=[], cost_inputs=cost_inputs)
            down = p["capital_recovered_per_unit"] - p["first_mortgage_pv"]
            tot["cost"] += p["unit_cost"]["total"] + pick(h).reserve_fund
            tot["mortgage_capital"] += p["first_mortgage_pv"]
            tot["down_payments"] += down
            tot["calhome"] += calhome
            tot["ahp"] += ahp
            gap = p["per_unit_gap_after_public_sources"]
            tot["philanthropy"] += max(gap, 0)
            tot["surplus_homes"] += int(gap < 0)
        out[label] = {k: round(v) for k, v in tot.items()}
    out["unit_cost"] = capital_model.unit_cost(cost_inputs)["total"]
    out["assumptions"] = {"hard_cost_per_sqft": cost_inputs["hard_cost_per_sqft"], "calhome_per_home": calhome,
                          "ahp_per_home": ahp, "note_discount_rate": sus.ASSUMPTIONS["note_discount_rate"]}
    return out


def headlines(s):
    """One headline number per beat, each with its provenance (formula, inputs, source or assumption, tool)."""
    hh, cap = s["households"], s["capital"]
    n = len(hh)
    denied = sum(h["p_denied"] > 0.5 for h in hh)
    exp = {k: round(sum(h["p"][k] for h in hh), 1) for k in REGIMES}
    site = s["site"]
    clock = s["timeline"]
    return {
        "clock": {"value": f"{clock['keystone']['years']} years",
                  "label": f"from offer to move-in, vs {clock['baseline']['years']} years the usual way ({clock['saved_months']} months saved)",
                  "formula": "critical path (longest chain of dependent phases) of the project graph, with and without Euodos's levers",
                  "inputs": {"levers": clock["levers"], "estimates": clock["estimates"], "saved_by_each_lever": clock["lever_savings_alone"]},
                  "source": "SB 4 approval: HCD + SF Planning (90-180 days); funding: Terner Center 2025; baseline: Impact Lab brief; other durations are labelled estimates",
                  "tool": "timeline.compare"},
        "site": {"value": f"{site['homes']} homes", "label": f"on {site['parking_sqm']:,} m² of surface parking the CNN found",
                 "formula": "developable = 50% of detected parking + 50% of lawn, at 16 townhomes/acre, capped at 30 per site",
                 "inputs": {"parking_sqm": site["parking_sqm"], "parcel_acres": site["parcel_acres"]},
                 "source": "U-Net CNN on 2022 NAIP aerial imagery (stored scan) · OC Public Works parcel " + APN, "tool": "sites_search"},
        "families": {"value": f"{denied} of {n}", "label": "would be turned down by a conventional lender",
                     "formula": "count of households with P(denial) > 50% on a 6.86% market loan for a $750k home",
                     "inputs": {"households": n, "home_value": HOME_VALUE},
                     "source": "Gradient-boosted model trained on HMDA OC loan decisions, 2022-2023 (champion, AUC 0.779)",
                     "tool": "family_market_score"},
        "mortgages": {"value": f"{exp['keystone']} of {n}", "label": f"expected to keep their homes for 10 years (market loans: {exp['market']})",
                      "formula": "sum over households of P(still own at year 10), 1,500 simulated decades each",
                      "inputs": {k: exp[k] for k in REGIMES},
                      "source": "Monte Carlo of job loss, insurance shocks, repairs and arrears; hazard rates are labelled assumptions",
                      "tool": "mortgage_optimize"},
        "capital": {"value": f"${cap['keystone']['philanthropy'] / 1e6:.1f}M",
                    "label": f"of philanthropy closes the gap for {n} homes (standard 0% loans: ${cap['standard']['philanthropy'] / 1e6:.1f}M)",
                    "formula": "sum over homes of max(0, cost + reserve - mortgage PV - down payment - CalHome - AHP)",
                    "inputs": cap["assumptions"],
                    "source": "Cost, CalHome and AHP per home are labelled planning assumptions; notes valued at 5% present value",
                    "tool": "capital_plan"},
        "decade": {"value": f"{exp['keystone']} vs {exp['market']}", "label": "expected still owning at year 10: Euodos vs market loans",
                   "formula": "expected counts as in the mortgages beat; the animation shows one simulated decade per household",
                   "inputs": {k: exp[k] for k in REGIMES},
                   "source": "Same simulation, same shocks across the three regimes (common random numbers)", "tool": "family_simulate"},
        "path": _path_headline(s["path"]),
    }


def _path_headline(path):
    res, chosen = path["results"], pathways.BY_KEY[path["choice"]]
    row = next(r for r in res["paths"] if r["key"] == chosen["key"])
    ruled_out = sum(r["verdict"] == "no" for r in res["paths"])
    checks = f"{row['to_verify']} check{'s' if row['to_verify'] != 1 else ''} to verify" if row["to_verify"] else "every test met"
    return {"value": chosen["short"], "label": f"{chosen['name']}: {chosen['review']}, {row['clock'][0].lower() + row['clock'][1:]}; {checks}; {ruled_out} of {len(res['paths'])} paths ruled out",
            "formula": "each path's statutory tests applied to the project; a missing fact is 'to verify', never assumed; fastest viable ministerial path recommended",
            "inputs": res["project"], "source": f"{row['clock_source']['label']} (checked {res['checked']})", "tool": "pathways.evaluate"}


def finish(s):
    s.setdefault("levers", {"instant_screen": True, "sb4_ministerial": True, "parallel_funding": True})
    s.setdefault("estimates", dict(timeline.ESTIMATES))
    path = s.setdefault("path", {"project": {"homes": s["site"]["homes"]}, "choice": None})
    path["results"] = pathways.evaluate(path["project"])
    viable = {r["key"] for r in path["results"]["paths"] if r["verdict"] != "no"}
    if path["choice"] not in viable:
        path["choice"] = path["results"]["recommended"]
    chosen = pathways.BY_KEY[path["choice"]]
    s["levers"]["sb4_ministerial"] = chosen["review"] == "ministerial"  # the clock follows the chosen path
    s["timeline"] = timeline.compare(s["levers"], s["estimates"], chosen["phase"] if chosen["review"] == "ministerial" else None)
    s["capital"] = capital(s["households"], **s["assumptions"])
    s["headlines"] = headlines(s)
    return s


def load_seed():
    return json.loads(SEED.read_text())


def fresh():
    """A private copy of the seeded scenario, for one signed-in session."""
    return copy.deepcopy(load_seed())


def edit_household(s, i, **changes):
    """Recompute one household after an off-script edit (fields and bounds validated by the caller)."""
    h = s["households"][i]
    f = sus.Family(income=changes.get("income", h["income"]), household_size=changes.get("household_size", h["household_size"]),
                   savings=changes.get("savings", h["savings"]), monthly_debts=changes.get("monthly_debts", h["monthly_debts"]),
                   income_volatility=h["income_volatility"])
    s["households"][i] = household(h["name"], f, i)
    return finish(s)


def edit_levers(s, levers=None, estimates=None):
    s["levers"].update(levers or {})
    if levers and "sb4_ministerial" in levers:  # the approval lever and the chosen path are one decision
        s["path"]["choice"] = None if levers["sb4_ministerial"] else "discretionary"
    s["estimates"].update(estimates or {})
    return finish(s)


def edit_path(s, project=None, choice=None):
    """Re-test the legal paths for a different project (size, zoning, city status) and/or choose one."""
    proposed = s["path"]["project"] | (project or {})
    if choice and next(r for r in pathways.evaluate(proposed)["paths"] if r["key"] == choice)["verdict"] == "no":
        raise ValueError(f"{pathways.BY_KEY[choice]['name']} does not fit this project")
    s["path"]["project"] = proposed
    if choice:
        s["path"]["choice"] = choice
    return finish(s)


def edit_assumptions(s, **changes):
    s["assumptions"].update({k: v for k, v in changes.items() if v is not None})
    return finish(s)


def _site():
    feat = next(f for f in json.loads((DEMO / "featured.json").read_text()) if f["apn"] == APN)
    raw = next(r for r in json.loads((config.DATA / "site_scores.json").read_text()) if r.get("apn") == APN)
    return {"apn": APN, "name": feat["name"], "city": feat["city"], "address": feat["address"], "parcel_acres": feat["parcel_acres"],
            "parking_sqm": feat["parking_sqm"], "homes": feat["allocated"], "quad": feat["quad"], "homes_polygons": [h["polygon"] for h in feat["homes"]],
            "parcel": feat["parcel"], "img_rgb": feat["img_rgb"], "img_mask": feat["img_mask"], "model_version": feat["model_version"],
            # SB 4 screen: only what the data shows; everything else is marked for verification, never assumed
            "sb4": [{"check": "Faith-affiliated owner (OpenStreetMap place of worship)", "status": "to verify",
                     "note": "OSM tag, not a title record"},
                    {"check": f"Density allowed: {config.SB4_DENSITY_RESIDENTIAL_ZONE}+ homes/acre by right", "status": "met",
                     "note": f"Plan uses 16/acre; {raw.get('units_sb4_cap', 'n/a')} allowed on the developable area"},
                    {"check": f"{config.SB4_OWNERSHIP_DEED_YEARS}-year affordability deed for ownership units", "status": "met",
                     "note": "Habitat's resale restriction satisfies it"},
                    {"check": "Not in a very high fire hazard severity zone (CAL FIRE)", "status": "to verify", "note": "screen not run"},
                    {"check": "Not in a FEMA flood zone", "status": "to verify", "note": "screen not run"}]}


def build_seed():
    from keystone.models import homekeeper
    fams = homekeeper.build_portfolio(n=N_HOMES, seed=30)
    s = {"title": "Crossline Church offers its parking lot: can 30 families move in within two years?", "site": _site(), "home_value": HOME_VALUE,
         "assumptions": {"hard_cost_per_sqft": config.COST_ASSUMPTIONS["hard_cost_per_sqft"], "calhome": 60_000, "ahp": 40_000},
         "households": [household(name, f, i) for i, (name, f) in enumerate(fams)]}
    s = finish(s)
    SEED.write_text(json.dumps(s, separators=(",", ":")))
    return s


if __name__ == "__main__":
    seed = build_seed()
    print(json.dumps(seed["headlines"], indent=1)[:2000])
