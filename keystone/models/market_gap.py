"""Market-gap model on real HMDA loan-level data for Orange County (2022-2024 home purchases).

Two jobs:
1. Size the gap: how many low-income OC families apply for a purchase mortgage and are denied, and why.
2. Score a family: P(conventional lender denies) given income, price, LTV and DTI. Families the market
   would approve don't need Habitat; families it would deny are the ones Habitat exists for.

Protected attributes are excluded from features (Fuster et al. 2022, J. Finance) but kept for the
fairness guardrail: the denial-rate calibration gap across race groups must not widen when a
challenger is promoted.

  python -m keystone.models.market_gap            # temporal champion/challenger: 2022 -> 2023 -> 2024
"""
import json
import pickle
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score

from keystone import config
from keystone.config import ARTIFACTS, DATA, DATA_RAW
from keystone.models import registry

FEATURES = ["income_k", "loan_k", "value_k", "ltv", "dti", "loan_type", "age_band", "pti_proxy",
            "tract_income_pct", "units"]
DTI_MAP = {"<20%": 15, "20%-<30%": 25, "30%-<36%": 33, "50%-60%": 55, ">60%": 65}
AGE_MAP = {"<25": 0, "25-34": 1, "35-44": 2, "45-54": 3, "55-64": 4, "65-74": 5, ">74": 6}
DENIAL_REASONS = {1: "Debt-to-income ratio", 2: "Employment history", 3: "Credit history", 4: "Collateral",
                  5: "Insufficient cash", 6: "Unverifiable information", 7: "Credit application incomplete",
                  8: "Mortgage insurance denied", 9: "Other"}


def _dti(v):
    if pd.isna(v):
        return np.nan
    if v in DTI_MAP:
        return DTI_MAP[v]
    try:
        return float(v)
    except ValueError:
        return np.nan


def load(year):
    d = pd.read_csv(DATA_RAW / f"hmda_oc_{year}.csv", low_memory=False)
    d = d.loc[(d.occupancy_type == 1) & (d.lien_status == 1) & d.action_taken.isin([1, 2, 3])].copy()
    d["denied"] = (d.action_taken == 3).astype(int)
    d["income_k"] = pd.to_numeric(d.income, errors="coerce")
    d = d.loc[d.income_k > 0].copy()
    d["loan_k"] = d.loan_amount / 1000
    d["value_k"] = pd.Series(pd.to_numeric(d.property_value, errors="coerce"), index=d.index) / 1000
    d["ltv"] = pd.to_numeric(d.loan_to_value_ratio, errors="coerce")
    d["dti"] = d.debt_to_income_ratio.map(_dti)
    d["loan_type"] = d.loan_type
    d["age_band"] = d.applicant_age.map(AGE_MAP)
    d["pti_proxy"] = d.loan_k / d.income_k
    d["tract_income_pct"] = d.tract_to_msa_income_percentage
    d["units"] = pd.to_numeric(d.total_units, errors="coerce")
    d["ami_k"] = d.ffiec_msa_md_median_family_income / 1000
    d["income_pct_ami"] = d.income_k / d.ami_k * 100
    d["race"] = d.derived_race
    d["year"] = year
    return d


def gap_report(d):
    low = d[d.income_pct_ami <= 80]
    den = low[low.denied == 1]
    reasons = den["denial_reason-1"].map(DENIAL_REASONS).value_counts()
    return {
        "year": int(d.year.iloc[0]),
        "applications": len(d),
        "low_income_applications": len(low),
        "low_income_share_of_applications": round(len(low) / len(d), 3),
        "low_income_denial_rate": round(float(low.denied.mean()), 3),
        "all_denial_rate": round(float(d.denied.mean()), 3),
        "low_income_denied": len(den),
        "low_income_denial_reasons": {k: int(v) for k, v in reasons.items()},
        "median_price_low_income_approved_k": float(low[low.denied == 0].value_k.median()),
        "median_income_low_income_applicants_k": float(low.income_k.median()),
    }


MIN_GROUP = 100  # small enough to measure Black applicants in OC (n~120 a year), large enough for a stable mean


def fairness_gap(d, p):
    """Max calibration gap |mean predicted - observed denial rate| over every race and ethnicity group with at least
    MIN_GROUP applicants (including applicants whose race was not reported, who are a real population of denials)."""
    gaps = {}
    d = d.assign(p=p)
    for col, prefix in (("race", ""), ("derived_ethnicity", "ethnicity: ")):
        if col not in d:
            continue
        for g, sub in d.groupby(col):
            if len(sub) >= MIN_GROUP and g != "Free Form Text Only":
                gaps[f"{prefix}{g}"] = abs(sub.p.mean() - sub.denied.mean())
    return round(float(max(gaps.values())), 4), {k: round(float(v), 4) for k, v in gaps.items()}


def paired_bootstrap(champ_model, chal_model, test_df, n_boot=400, seed=0):
    """95% intervals, over the same resampled test applicants, of the challenger's AUC gain and of how much wider its
    fairness gap is. Small groups (Black applicants are ~120 a year in OC) make the fairness gap noisy, so a
    challenger is judged on whether it is *significantly* less fair, not on a point difference inside the noise."""
    y = test_df.denied.to_numpy()
    pc, pn = champ_model.predict_proba(test_df[FEATURES])[:, 1], chal_model.predict_proba(test_df[FEATURES])[:, 1]
    rng = np.random.default_rng(seed)
    auc, fair = [], []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() == y[i].max():
            continue
        sub = test_df.iloc[i]
        auc.append(roc_auc_score(y[i], pn[i]) - roc_auc_score(y[i], pc[i]))
        fair.append(fairness_gap(sub, pn[i])[0] - fairness_gap(sub, pc[i])[0])
    ci = lambda v: [round(float(x), 4) for x in np.percentile(v, [2.5, 97.5])]
    return ci(auc), ci(fair)


def fit(train_df, seed=0, **hp):
    params: dict[str, Any] = {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 31, "l2_regularization": 1.0} | hp
    m = HistGradientBoostingClassifier(random_state=seed,
                                       categorical_features=[FEATURES.index("loan_type")],  # pyright: ignore[reportArgumentType]  # sklearn accepts index lists; bundled stub says str
                                       **params)
    m.fit(train_df[FEATURES], train_df.denied)
    return m, params


def evaluate(m, test_df):
    p = m.predict_proba(test_df[FEATURES])[:, 1]
    fg, groups = fairness_gap(test_df, p)
    return {"auc": round(float(roc_auc_score(test_df.denied, p)), 4),
            "brier": round(float(brier_score_loss(test_df.denied, p)), 4),
            "fairness_gap": fg, "fairness_by_group": groups, "n_test": len(test_df)}


MIN_AUC_GAIN = 0.002


def propose(train_years, test_year, frames, **hp):
    tr = pd.concat([frames[y] for y in train_years])
    m, params = fit(tr, **hp)
    # A challenger only counts if it is compared on the newest year, so re-score the champion there too
    champ = registry.champion("market_gap")
    cm = None
    if champ is not None:
        with open(registry.model_file(champ), "rb") as f:
            cm = pickle.load(f)
        champ["metrics"] = evaluate(cm, frames[test_year])
        r = json.loads(registry.REG.read_text())
        for e in r["market_gap"]:
            if e["version"] == champ["version"]:
                e["metrics"] = champ["metrics"]; e["rescored_on"] = test_year
        registry.REG.write_text(json.dumps(r, indent=2))
    metrics = evaluate(m, frames[test_year])
    checks = []
    if cm is not None:
        (lo, hi), (flo, fhi) = paired_bootstrap(cm, m, frames[test_year])
        metrics["auc_gain_ci95"], metrics["fairness_widening_ci95"] = [lo, hi], [flo, fhi]
        # a gain inside the noise is not a gain; a fairness gap that is significantly wider blocks promotion outright
        checks.append((lo > MIN_AUC_GAIN, f"AUC gain 95% CI [{lo:+.4f}, {hi:+.4f}]; lower bound must exceed {MIN_AUC_GAIN}"))
        checks.append((flo <= 0, f"fairness gap widening 95% CI [{flo:+.4f}, {fhi:+.4f}]; must not be significantly above 0"))
    path = ARTIFACTS / f"market_gap_{'_'.join(map(str, train_years))}.pkl"
    with open(path, "wb") as f:
        pickle.dump(m, f)
    return registry.propose("market_gap", registry.relative(path), metrics, params | {"train_years": train_years, "test_year": test_year},
                            primary="auc", min_gain=MIN_AUC_GAIN, checks=checks,
                            data_version=f"HMDA OC {train_years}->{test_year}")


_MODEL = {}


def champion_model():
    c = registry.champion("market_gap")
    if c is None:
        raise RuntimeError("No market_gap champion yet: run `python -m keystone.models.market_gap`")
    if c["path"] not in _MODEL:
        with open(registry.model_file(c), "rb") as f:
            _MODEL.clear(); _MODEL[c["path"]] = pickle.load(f)
    return _MODEL[c["path"]], c


def score_family(income, price, down_payment_share=0.05, monthly_debts=0.0, rate=0.0686, loan_type=1, age_band=2):
    """P(conventional denial) for a family buying at `price` with a market-rate 30-yr loan."""
    if not (income >= 1_000 and price > 0 and 0 <= down_payment_share < 1 and monthly_debts >= 0 and 0 < rate < 0.25):
        raise ValueError("score_family needs income >= 1,000, price > 0, 0 <= down_payment_share < 1, monthly_debts >= 0, 0 < rate < 0.25")
    loan = price * (1 - down_payment_share)
    r = rate / 12
    pmt = loan * r / (1 - (1 + r) ** -360)
    housing = pmt + price * 0.011 / 12 + 200  # tax + insurance
    dti = (housing + monthly_debts) / (income / 12) * 100
    row = pd.DataFrame([{"income_k": income / 1000, "loan_k": loan / 1000, "value_k": price / 1000,
                         "ltv": (1 - down_payment_share) * 100, "dti": min(dti, 70), "loan_type": loan_type,
                         "age_band": age_band, "pti_proxy": loan / income, "tract_income_pct": 100, "units": 1}])
    m, c = champion_model()
    return {"p_denied": round(float(m.predict_proba(row[FEATURES])[0, 1]), 3), "implied_dti": round(dti, 1),
            "market_payment": round(housing), "model_version": c["version"]}


def main():
    years = sorted(config.REGION["hmda_years"])
    frames = {y: load(y) for y in years}
    gaps = [gap_report(frames[y]) for y in frames]
    (DATA / "market_gap.json").write_text(json.dumps(gaps, indent=2))
    for g in gaps:
        print(g)
    # temporal champion/challenger: each new year is the holdout for a model trained on everything before it
    for i in range(1, len(years)):
        print(propose(years[:i], years[i], frames))
    if len(years) > 2:
        print(propose([years[-2]], years[-1], frames, max_leaf_nodes=15))  # an alternative challenger, same gate


if __name__ == "__main__":
    main()
