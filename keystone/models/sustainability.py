"""Two-layer simulate-and-optimize model of whether a family can *keep* a home (Ardon et al. 2024, ICAIF).

Inner layer: vectorized monthly Monte Carlo of household cash flow over 10 years.
  - job loss is the adverse trigger, moderated by the liquid buffer (Tian, Quercia & Riley 2016)
  - payment size, not equity, drives delinquency (Ganong & Noel 2020; Fuster & Willen 2017)
  - insurance premium shocks hit constrained owners (Ge, Johnson & Tzur-Ilan, Dallas Fed WP 2505)
  - stewardship (early detection + workout) cures most serious delinquencies (Thaden 2011: 82% kept or sold with help)
Outer layer: search over mortgage designs for the one that maximizes 10-year sustained ownership per subsidy dollar.

All hazard parameters are labelled assumptions (no public Habitat loan-performance data exists);
they are exposed so agents can run sensitivity analyses in the sandbox.
"""
from dataclasses import asdict, dataclass
from itertools import product

import numpy as np

from keystone import config

ASSUMPTIONS = {
    "annual_job_loss_prob": 0.06,         # low-wage workers; assumption
    "mean_unemployment_months": 4.0,
    "ui_replacement": 0.45,               # CA UI replaces roughly half of wages up to a cap; assumption
    "income_growth_mu": 0.03, "income_growth_sd": 0.03,
    "essentials_base": 1_400, "essentials_per_person": 700,   # non-housing essentials, monthly; assumption
    "surplus_saved": 0.30,
    "repair_annual_prob": 0.25, "repair_mean": 4_000,
    "insurance_shock_prob": 0.05, "insurance_shock_size": 0.40,
    "steward_cure_prob": 0.82,            # Thaden 2011
    "no_steward_cure_prob": 0.35,
    "home_appreciation_mu": 0.035, "home_appreciation_sd": 0.06,
    "effective_tax_rate_exempt": 0.003,   # RTC 214.15 welfare exemption during nonprofit ownership; residual bonds
    "tax_rate_owner": config.COST_ASSUMPTIONS["property_tax_rate"],
}


def _require(ok, msg):
    if not ok:
        raise ValueError(msg)


@dataclass
class Family:
    income: float = 95_000
    household_size: int = 4
    savings: float = 6_000
    monthly_debts: float = 300.0
    income_volatility: float = 1.0     # multiplier on job-loss risk (gig/seasonal work > 1)

    def __post_init__(self):
        _require(0 < self.income <= 2_000_000, f"income must be in (0, 2,000,000], got {self.income}")
        _require(1 <= self.household_size <= 8, f"household_size must be 1-8 (HUD scale), got {self.household_size}")
        _require(self.savings >= 0, f"savings must be >= 0, got {self.savings}")
        _require(self.monthly_debts >= 0, f"monthly_debts must be >= 0, got {self.monthly_debts}")
        _require(0 <= self.income_volatility <= 5, f"income_volatility must be 0-5, got {self.income_volatility}")


@dataclass
class Design:
    rate: float = 0.0
    term_years: int = 30
    payment_cap: float = 0.30          # first-mortgage PITI share of gross income at closing
    reserve_fund: float = 0.0          # grant-funded escrow reserve at closing
    income_indexed: bool = False       # payment re-set to cap*income annually (deferred balance accrues)
    stewardship: bool = True
    down_payment_share: float = 0.01
    restricted_assessment: bool = True  # deed-restricted homes assessed at restricted price (RTC 402.1-style); assumption

    def __post_init__(self):
        _require(0 <= self.rate <= 0.2, f"rate must be 0-0.20, got {self.rate}")
        _require(5 <= self.term_years <= 50, f"term_years must be 5-50, got {self.term_years}")
        _require(0.05 <= self.payment_cap <= 0.8, f"payment_cap must be 0.05-0.80, got {self.payment_cap}")
        _require(self.reserve_fund >= 0, f"reserve_fund must be >= 0, got {self.reserve_fund}")
        _require(0 <= self.down_payment_share < 1, f"down_payment_share must be in [0, 1), got {self.down_payment_share}")

    def label(self):
        return (f"{self.rate:.0%} / {self.term_years}y / cap {self.payment_cap:.0%} / reserve ${self.reserve_fund:,.0f}"
                f"{' / income-indexed' if self.income_indexed else ''}{'' if self.stewardship else ' / no steward'}")


@dataclass
class Home:
    value: float = 750_000           # appraised value of the Habitat townhome
    hoa: float = config.COST_ASSUMPTIONS["hoa_monthly"]
    insurance: float = config.COST_ASSUMPTIONS["insurance_annual"]
    insurance_growth: float = config.COST_ASSUMPTIONS["insurance_annual_growth"]

    def __post_init__(self):
        _require(10_000 <= self.value <= 20_000_000, f"home value must be $10k-$20M, got {self.value}")
        _require(self.hoa >= 0 and self.insurance >= 0, "hoa and insurance must be >= 0")


def _pmt(principal, rate, n):
    if rate == 0:
        return principal / n
    r = rate / 12
    return principal * r / (1 - (1 + r) ** -n)


def underwrite(family: Family, home: Home, design: Design, a=ASSUMPTIONS):
    """Size the first mortgage so PITI+HOA = cap * income; the rest is a deferred silent second."""
    monthly_income = family.income / 12
    budget = design.payment_cap * monthly_income
    n = design.term_years * 12
    k = _pmt(1.0, design.rate, n)                       # P&I per dollar borrowed
    down = home.value * design.down_payment_share
    other = home.insurance / 12 + home.hoa
    t = a["tax_rate_owner"] / 12
    if design.restricted_assessment:                    # tax base = first mortgage + down payment
        max_first = max(budget - other - t * down, 0) / (k + t)
    else:
        max_first = max(budget - other - t * home.value, 0) / k
    first = min(max_first, home.value - down)
    second = max(home.value - down - first, 0)
    tax_base = first + down if design.restricted_assessment else home.value
    piti = first * k + tax_base * t + other
    return {"first_mortgage": first, "silent_second": second, "down_payment": down, "tax_base": tax_base,
            "piti_hoa": piti, "front_end_ratio": piti / monthly_income}


# event bits recorded per month when simulate(record=True)
EV_JOB_LOSS, EV_INSURANCE, EV_REPAIR, EV_STEWARD, EV_CURED, EV_LOST = 1, 2, 4, 8, 16, 32
# states: 0 current, 1 stressed (cash buffer under one payment), 2 missed a payment, 3 90+ days late, 4 home lost


def simulate(family: Family, home: Home, design: Design, n_paths=2000, years=10, seed=0, a=ASSUMPTIONS, record=False):
    """Same seed => same life shocks in the same months whatever the design (common random numbers), so designs and
    scenarios can be compared family by family."""
    rng = np.random.default_rng(seed)
    uw = underwrite(family, home, design, a)
    T = years * 12
    n = design.term_years * 12
    pi = _pmt(uw["first_mortgage"], design.rate, n)
    income = np.full(n_paths, family.income / 12)
    buffer = np.full(n_paths, family.savings + design.reserve_fund)
    insurance = np.full(n_paths, home.insurance / 12)
    tax = uw["tax_base"] * a["tax_rate_owner"] / 12
    unemployed = np.zeros(n_paths, dtype=int)
    missed = np.zeros(n_paths, dtype=int)
    ever90 = np.zeros(n_paths, dtype=bool)
    lost = np.zeros(n_paths, dtype=bool)
    deferred = np.zeros(n_paths)
    p_loss = 1 - (1 - a["annual_job_loss_prob"] * family.income_volatility) ** (1 / 12)
    p_reemploy = 1 / a["mean_unemployment_months"]
    essentials = a["essentials_base"] + a["essentials_per_person"] * (family.household_size - 1)
    cure = a["steward_cure_prob"] if design.stewardship else a["no_steward_cure_prob"]
    min_buffer = np.full(n_paths, np.inf)
    rec_T = T if record else 0  # recording arrays are empty unless asked for
    states = np.zeros((rec_T, n_paths), np.int8)
    events = np.zeros((rec_T, n_paths), np.int8)
    buffers = np.zeros((rec_T, n_paths), np.float32)
    last_contact = np.full(n_paths, -99)

    for t in range(T):
        shock = np.zeros(n_paths, bool)
        if t % 12 == 0 and t > 0:
            income *= np.exp(rng.normal(a["income_growth_mu"], a["income_growth_sd"], n_paths))
            shock = rng.random(n_paths) < a["insurance_shock_prob"]
            insurance *= (1 + home.insurance_growth) * np.where(shock, 1 + a["insurance_shock_size"], 1)
        newly = (unemployed == 0) & (rng.random(n_paths) < p_loss)
        unemployed = np.where(newly, 1, unemployed)
        back = (unemployed > 0) & (rng.random(n_paths) < p_reemploy) & ~newly
        unemployed = np.where(back, 0, unemployed)
        earned = np.where(unemployed > 0, income * a["ui_replacement"], income)
        payment = pi + tax + insurance + home.hoa
        if design.income_indexed:
            # payment capped at cap*current income; shortfall accrues as deferred (Ganong & Noel: liquidity first)
            cap_pay = design.payment_cap * earned
            deferred += np.maximum(payment - cap_pay, 0)
            payment = np.minimum(payment, cap_pay)
        repair = np.where(rng.random(n_paths) < a["repair_annual_prob"] / 12, rng.exponential(a["repair_mean"], n_paths), 0)
        surplus = earned - payment - essentials - family.monthly_debts - repair
        buffer = buffer + np.where(surplus > 0, surplus * a["surplus_saved"], surplus)
        short = (buffer < 0) & ~lost
        missed = np.where(short, missed + 1, 0)
        buffer = np.maximum(buffer, 0)
        hit90 = missed >= 3
        ever90 |= hit90
        resolved = hit90 & (rng.random(n_paths) < cure)
        newly_lost = hit90 & ~resolved & ~lost
        lost |= hit90 & ~resolved
        missed = np.where(resolved, 0, missed)
        min_buffer = np.minimum(min_buffer, buffer)
        if record:
            stressed = buffer < payment
            st = np.where(lost, 4, np.where(hit90, 3, np.where(missed > 0, 2, np.where(stressed, 1, 0))))
            states[t] = st
            # the steward reaches out when the cash buffer drops under one payment (at most once a quarter)
            contact = design.stewardship & (stressed | (missed > 0)) & ~lost & (t - last_contact >= 3)
            last_contact = np.where(contact, t, last_contact)
            events[t] = (newly * EV_JOB_LOSS) | (shock * EV_INSURANCE) | ((repair > 0) * EV_REPAIR) | \
                        (contact * EV_STEWARD) | (resolved * EV_CURED) | (newly_lost * EV_LOST)
            buffers[t] = buffer

    years_arr = rng.normal(a["home_appreciation_mu"], a["home_appreciation_sd"], (n_paths, years)).sum(1)
    value_T = home.value * np.exp(years_arr)
    paid_principal = uw["first_mortgage"] - _balance(uw["first_mortgage"], design.rate, n, T)
    equity = paid_principal + uw["down_payment"] + 0.25 * np.maximum(value_T - home.value, 0)  # 25% appreciation share (resale formula)
    sustained = ~lost
    return {
        "design": design.label(), "underwriting": {k: round(v, 2) for k, v in uw.items()},
        "p_sustained_10y": round(float(sustained.mean()), 4),
        "p_ever_90dpd": round(float(ever90.mean()), 4),
        "median_buffer_low": round(float(np.median(min_buffer))),
        "median_owner_equity_10y": round(float(np.median(equity[sustained]))) if sustained.any() else 0,
        "mean_deferred_balance": round(float(deferred.mean())),
        "subsidy_cost": round(subsidy_cost(uw, design, home)),
        "n_paths": n_paths,
        **({"states": states, "events": events, "buffers": buffers} if record else {}),
    }


def _balance(principal, rate, n, k):
    if rate == 0:
        return principal * (1 - k / n)
    r = rate / 12
    pmt = _pmt(principal, rate, n)
    return principal * (1 + r) ** k - pmt * ((1 + r) ** k - 1) / r


def subsidy_cost(uw, design, home, discount=0.04):
    """PV cost to Habitat: below-market interest on the first, the silent second (assume 50% recaptured at resale), reserve."""
    n = design.term_years * 12
    market = _pmt(uw["first_mortgage"], discount, n)
    actual = _pmt(uw["first_mortgage"], design.rate, n)
    r = discount / 12
    pv_interest_gap = (market - actual) * (1 - (1 + r) ** -n) / r
    return max(pv_interest_gap, 0) + 0.5 * uw["silent_second"] + design.reserve_fund


DESIGN_SPACE = {
    "rate": [0.0, 0.02, 0.04],
    "term_years": [30, 40],
    "payment_cap": [0.25, 0.30, 0.35],
    "reserve_fund": [0, 5_000, 10_000],
    "income_indexed": [False, True],
}


def optimize(family: Family, home: Home, min_sustain=0.95, n_paths=1500, space=DESIGN_SPACE):
    """Outer layer: cheapest design meeting the sustainability target (else the most sustainable)."""
    results = []
    keys = list(space)
    for vals in product(*space.values()):
        d = Design(**dict(zip(keys, vals)))
        r = simulate(family, home, d, n_paths=n_paths)
        r["design_params"] = asdict(d)
        results.append(r)
    ok = [r for r in results if r["p_sustained_10y"] >= min_sustain]
    best = min(ok, key=lambda r: (r["subsidy_cost"], -r["p_sustained_10y"])) if ok else max(results, key=lambda r: r["p_sustained_10y"])
    # Counterfactual: same home and silent-second structure but a market-rate first sized to a 45% DTI,
    # no stewardship, no restricted assessment -- i.e. what "affordable" looks like without Habitat's levers
    baseline = simulate(family, home, Design(rate=config.MARKET_30Y_RATE, payment_cap=0.45, stewardship=False,
                                             restricted_assessment=False), n_paths=n_paths)
    frontier = sorted(results, key=lambda r: (r["subsidy_cost"], -r["p_sustained_10y"]))
    pareto, best_p = [], -1
    for r in frontier:
        if r["p_sustained_10y"] > best_p:
            pareto.append(r); best_p = r["p_sustained_10y"]
    return {"best": best, "meets_target": bool(ok), "target": min_sustain,
            "market_rate_baseline": baseline, "pareto_frontier": pareto, "n_designs": len(results)}


if __name__ == "__main__":
    import json
    f = Family()
    h = Home()
    out = optimize(f, h)
    print(json.dumps({k: v for k, v in out.items() if k != "pareto_frontier"}, indent=2))
    for p in out["pareto_frontier"]:
        print(f"{p['subsidy_cost']:>10,.0f}  {p['p_sustained_10y']:.3f}  {p['design']}")
