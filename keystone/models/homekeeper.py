"""HomeKeeper: post-purchase stewardship for a portfolio of homeowners.

The demo portfolio is 100 *synthetic* families whose incomes are sampled from real 2024 HMDA applicants in
Orange County earning <=80% AMI. Savings, debts and job-loss risk are drawn from labelled assumptions.
Each family lives the same 10 years (same job losses, repairs and insurance shocks, via common random numbers) under
three regimes, so the difference is the product, not luck:

  market    6.86% / 30y loan sized to 45% DTI, no stewardship (what "affordable" means without Habitat)
  standard  0% / 30y loan at a 30% payment cap, no early-warning stewardship
  keystone  per-family optimized design (mortgage designer) + the Steward agent's early outreach and workouts

  python -m keystone.models.homekeeper
"""
import json

import numpy as np

from keystone import config
from keystone.models import sustainability as sus

OUT = config.ROOT / "keystone" / "app" / "static" / "demo"
SCENARIOS = {
    "market": "Market-rate loan, no steward",
    "standard": "0% Habitat loan, no early warning",
    "keystone": "Keystone design + Steward agent",
}
FIRST = ["Maria", "Duc", "Ana", "Kwame", "Lucia", "Minh", "Rosa", "Tomas", "Leilani", "Omar", "Grace", "Jae",
         "Sofia", "Andre", "Priya", "Luis", "Mai", "Isaac", "Elena", "Hector"]
LAST = ["Garcia", "Nguyen", "Okafor", "Hernandez", "Tran", "Lopez", "Kim", "Martinez", "Pham", "Ramirez", "Le",
        "Flores", "Santos", "Vu", "Reyes", "Cruz", "Alvarez", "Do", "Morales", "Castillo"]


def hmda_incomes():
    from keystone.models.market_gap import load
    d = load(2024)
    low = d.loc[d.income_pct_ami <= 80]
    return (low.income_k.values * 1000).astype(float)


def build_portfolio(n=100, seed=11):
    """Sample families until n pass Habitat OC's published band: 30% (extremely low) to 80% (low) limit for their size."""
    rng = np.random.default_rng(seed)
    pool = hmda_incomes()
    fams = []
    while len(fams) < n:
        size = int(rng.choice([2, 3, 4, 5, 6], p=[.15, .25, .3, .2, .1]))
        income = float(rng.choice(pool))
        adj = config.HH_SIZE_ADJ[size]
        if not (config.INCOME_LIMITS_4P["extremely_low"] * adj <= income <= config.INCOME_LIMITS_4P["low"] * adj):
            continue
        i = len(fams)
        f = sus.Family(
            income=income,
            household_size=size,
            savings=float(np.round(rng.lognormal(np.log(5_000), 0.7), -2)),       # assumption
            monthly_debts=float(np.round(rng.uniform(100, 700), -1)),             # assumption
            income_volatility=float(rng.choice([1.0, 1.3, 1.7], p=[.5, .3, .2])),  # assumption
        )
        name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}"
        fams.append((name, f))
    return fams


def _encode(arr):
    return "".join(map(str, arr.tolist()))


def run(n=100):
    home = sus.Home()
    fams = build_portfolio(n)
    out = {"months": 120, "scenarios": SCENARIOS, "families": [], "summary": {}}
    counts = {k: {"still_own": 0, "ever_90": 0, "steward_contacts": 0, "families_cured": 0, "homes_lost": 0} for k in SCENARIOS}
    for i, (name, f) in enumerate(fams):
        best = sus.optimize(f, home, n_paths=300)["best"]["design_params"]
        designs = {
            "market": sus.Design(rate=config.MARKET_30Y_RATE, payment_cap=0.45, stewardship=False, restricted_assessment=False),
            "standard": sus.Design(rate=0.0, term_years=30, payment_cap=0.30, stewardship=False),
            "keystone": sus.Design(**best),
        }
        rec = {"name": name, "income": round(f.income), "household_size": f.household_size, "savings": f.savings,
               "volatility": f.income_volatility, "design": designs["keystone"].label(),
               "pct_ami": round(f.income / (config.OC_AMI_4P * config.HH_SIZE_ADJ[f.household_size]) * 100)}
        for k, d in designs.items():
            r = sus.simulate(f, home, d, n_paths=1, seed=1000 + i, record=True)
            st, ev = r["states"][:, 0], r["events"][:, 0]
            rec[k] = {"states": _encode(st), "events": [int(e) for e in ev], "payment": round(r["underwriting"]["piti_hoa"]),
                      "buffer": [int(b) for b in r["buffers"][::3, 0]]}
            c = counts[k]
            c["still_own"] += int(st[-1] != 4)
            c["ever_90"] += int((st >= 3).any())
            c["steward_contacts"] += int(((ev & sus.EV_STEWARD) > 0).sum())
            c["families_cured"] += int(((ev & sus.EV_CURED) > 0).any())
            c["homes_lost"] += int(st[-1] == 4)
        out["families"].append(rec)
        if i % 20 == 19:
            print(f"{i + 1} families simulated")
    out["summary"] = counts
    (OUT / "portfolio.json").write_text(json.dumps(out))
    print(json.dumps(counts, indent=2))
    return out


ACTIONS = [
    (sus.EV_JOB_LOSS, "Job loss", "Re-certify income and reset the payment to the cap; refer to CA EDD unemployment insurance"),
    (sus.EV_INSURANCE, "Insurance premium spike", "Re-shop the policy; draw on the escrow reserve for the premium increase"),
    (sus.EV_REPAIR, "Major repair", "Route to Habitat home repair; draw on the repair reserve"),
]


def watchlist(month: int, scenario: str = "keystone", limit: int = 12):
    """Families in trouble at `month`, the shocks behind it, and the Steward's recommended action."""
    data = json.loads((OUT / "portfolio.json").read_text())
    rows = []
    for f in data["families"]:
        s = f[scenario]
        st = int(s["states"][month])
        if st in (1, 2, 3):
            recent = 0
            for e in s["events"][max(0, month - 12): month + 1]:
                recent |= e
            causes = [(lbl, act) for bit, lbl, act in ACTIONS if recent & bit]
            rows.append({"name": f["name"], "state": ["current", "stressed", "missed payment", "90+ days late"][st],
                         "severity": st, "income": f["income"], "payment": s["payment"],
                         "causes": [c[0] for c in causes] or ["Thin cash buffer"],
                         "action": causes[0][1] if causes else "Budget coaching; set up an automatic reserve deposit",
                         "contacted": bool(s["events"][month] & sus.EV_STEWARD)})
    rows.sort(key=lambda r: -r["severity"])
    return {"month": month, "scenario": scenario, "n_at_risk": len(rows), "families": rows[:limit]}


if __name__ == "__main__":
    run()
