"""Path-to-100 capital planner: sites x unit cost x family underwriting x funding stack."""
import json

from keystone import config
from keystone.models.sustainability import Design, Family, Home, _pmt, underwrite

# Programs verified 2026-10-31 (see research brief). Per-unit amounts are planning assumptions, not program caps.
FUNDING_SOURCES = [
    {"name": "Faith-land ground lease (SB 4)", "type": "land", "per_unit": None,
     "notes": "Land contributed or ground-leased by congregation; by-right approval, 45-yr ownership deed restriction",
     "url": config.SOURCES["sb4_hcd"]},
    {"name": "CalHome (HCD Homeownership Super NOFA)", "type": "loan/grant", "per_unit_assumption": 60_000,
     "notes": "Nonprofits eligible; homeownership development loans and first-time buyer assistance",
     "url": "https://www.hcd.ca.gov/funding/hosn"},
    {"name": "FHLBank San Francisco AHP", "type": "grant", "per_unit_assumption": 40_000,
     "notes": "Owner-occupied <=80% AMI; via member bank; 2026 General Fund $60.1M",
     "url": "https://www.fhlbsf.com/products/community-programs-grants/ahp"},
    {"name": "Welfare exemption (RTC 214.15 / 214.15.1)", "type": "tax", "per_unit": None,
     "notes": "Property tax exemption while nonprofit holds homes for sale to low-income buyers; 214.15.1 operative to 2027 lien date",
     "url": config.SOURCES["boe_214_15"]},
    {"name": "Keys to 100 philanthropy", "type": "grant", "per_unit_assumption": None,
     "notes": "2026 gala raised $330,000", "url": config.SOURCES["keys_to_100"]},
]


def unit_cost(c=config.COST_ASSUMPTIONS, land_per_unit=0.0):
    hard = c["hard_cost_per_sqft"] * c["unit_sqft"] * (1 - c["volunteer_labor_savings"])
    soft = hard * c["soft_cost_share"]
    return {"hard": round(hard), "soft": round(soft), "land": round(land_per_unit), "total": round(hard + soft + land_per_unit)}


def plan(target_homes: int = 100, family=None, design=None, appraised_value: float = 750_000, land_per_unit: float = 0.0,
         calhome: float = 60_000, ahp: float = 40_000, sites=None, max_units_per_site=30, note_discount_rate=0.05,
         cost_inputs: dict | None = None):
    family = family or Family()
    design = design or Design(rate=0.0, term_years=30, payment_cap=0.30)
    cost_inputs = cost_inputs or config.COST_ASSUMPTIONS  # callers pass a copy to override; never mutate the global
    cost = unit_cost(cost_inputs, land_per_unit=land_per_unit)
    uw = underwrite(family, Home(value=appraised_value), design)
    # A below-market first mortgage is worth its PV to Habitat (e.g. if sold to a note buyer), not its face value
    n = design.term_years * 12
    pay = _pmt(uw["first_mortgage"], design.rate, n)
    r = note_discount_rate / 12
    note_value = pay * (1 - (1 + r) ** -n) / r
    buyer_funds = note_value + uw["down_payment"]
    gap = cost["total"] - buyer_funds - calhome - ahp
    if sites is None:
        sites = json.loads((config.DATA / "site_scores.json").read_text())
    viable = [s for s in sites if s.get("viable")]
    chosen, units = [], 0
    for s in viable:  # largest first; agents re-rank with fire/transit/opportunity filters
        if units >= target_homes:
            break
        take = min(s["units_townhome"], max_units_per_site, target_homes - units)
        chosen.append({"name": s["name"], "city": s.get("city"), "address": s.get("address"), "apn": s.get("apn"),
                       "units": take, "developable_acres": s["developable_acres"]})
        units += take
    return {
        "target_homes": target_homes, "homes_sited": units, "sites_needed": len(chosen), "sites": chosen,
        "unit_cost": cost, "first_mortgage_face": round(uw["first_mortgage"]), "first_mortgage_pv": round(note_value),
        "capital_recovered_per_unit": round(buyer_funds),
        "per_unit_gap_after_public_sources": round(gap),
        "philanthropy_needed_total": round(max(gap, 0) * target_homes),
        "public_sources_total": round((calhome + ahp) * target_homes),
        "silent_second_per_unit": round(uw["silent_second"]),
        "assumptions": {"design": design.label(), "family_income": family.income, "appraised_value": appraised_value,
                        "calhome_per_unit": calhome, "ahp_per_unit": ahp, "note_discount_rate": note_discount_rate,
                        "max_units_per_site": max_units_per_site, "cost_inputs": cost_inputs},
        "funding_sources": FUNDING_SOURCES,
    }


if __name__ == "__main__":
    p = plan()
    print(json.dumps({k: v for k, v in p.items() if k not in ("sites", "funding_sources")}, indent=2))
    for s in p["sites"]:
        print(s)
