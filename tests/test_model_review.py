"""Regressions for the independent model review: each test pins a finding that made Keystone report a wrong or
flattering number."""
import numpy as np
import pytest

from keystone import tools
from keystone.agents import evals, memory
from keystone.models import capital, registry
from keystone.models import sustainability as s


def test_missed_payments_are_carried_as_arrears_not_forgiven():
    # a family that cannot cover the payment must owe it: the cash buffer goes negative instead of resetting to 0
    f = s.Family(income=40_000, savings=0, monthly_debts=600)
    r = s.simulate(f, s.Home(), s.Design(rate=0.0686, payment_cap=0.45, stewardship=False, restricted_assessment=False),
                   n_paths=200, record=True)
    assert (r["buffers"] < 0).any()
    late = (r["states"] >= 2).sum(0)
    assert late.max() >= 3  # a run of months behind accumulates instead of being wiped each month


def test_down_payment_comes_out_of_savings():
    f = s.Family(savings=6_000)
    small, big = (s.simulate(f, s.Home(), s.Design(down_payment_share=x), n_paths=500) for x in (0.0, 0.2))
    # 20% down on $750k is $150k the family does not have: Habitat must cover it, and it shows up as subsidy
    assert big["subsidy_cost"] - small["subsidy_cost"] > 50_000  # +$144k assistance, partly offset by a smaller silent second
    assert s.underwrite(f, s.Home(), s.Design(down_payment_share=0.2))["down_payment_from_savings"] == 6_000


def test_income_indexed_deferrals_are_not_free():
    f = s.Family(income=80_000, income_volatility=2.0)
    plain = s.simulate(f, s.Home(), s.Design(payment_cap=0.35))
    indexed = s.simulate(f, s.Home(), s.Design(payment_cap=0.35, income_indexed=True))
    assert indexed["mean_deferred_balance"] > 0
    assert indexed["subsidy_cost"] > plain["subsidy_cost"]


def test_short_loans_stop_charging_after_their_term():
    assert s._balance(100_000, 0.0, 60, 120) == 0
    assert s._balance(100_000, 0.04, 60, 120) == pytest.approx(0, abs=1e-6)
    r = s.simulate(s.Family(), s.Home(), s.Design(term_years=5, payment_cap=0.8), n_paths=300)
    assert r["median_owner_equity_10y"] < s.Home().value  # equity is bounded by what was actually paid and earned


def test_zero_discount_rate_is_finite():
    p = capital.plan(10, note_discount_rate=0.0)
    assert np.isfinite(p["first_mortgage_pv"]) and p["first_mortgage_pv"] == p["first_mortgage_face"]


def test_capital_counts_only_the_down_payment_a_family_can_pay():
    rich, broke = (capital.plan(10, family=s.Family(savings=x)) for x in (50_000, 0))
    assert rich["capital_recovered_per_unit"] - broke["capital_recovered_per_unit"] == pytest.approx(7_500, abs=1)


def test_reserve_fund_raises_the_capital_gap():
    a, b = tools.capital_plan(target_homes=10), tools.capital_plan(target_homes=10, reserve_fund=5_000)
    assert b["per_unit_gap_after_public_sources"] - a["per_unit_gap_after_public_sources"] == 5_000


def test_a_keyword_brief_cannot_pass_the_graders():
    urls = "\n".join(sorted(evals.KNOWN_URLS)[:5])
    cheat = f"120 units vs target. assumption. fairness.\n| x | 1.0 | 5 |\n{urls}\n"
    for m in evals.MISSIONS:
        g = evals.grade(cheat, [], m)
        assert g["score"] < 0.3, g
        assert not g["checks"]["reaches_target"] and not g["checks"]["families_sustainable"]


def test_brief_with_no_urls_is_not_hallucination_free():
    assert not evals.grade("No citations here.", [], evals.MISSIONS[0])["checks"]["no_hallucinated_urls"]


def test_bare_unknown_domains_are_caught():
    g = evals.grade("See madeup-housing-stats.org for details.", [], evals.MISSIONS[0])
    assert "madeup-housing-stats.org" in g["bad_urls"]


def test_families_must_match_the_missions_own_families():
    m = evals.MISSIONS[0]
    other = [{"tool": "mortgage_optimize", "agent": "underwriter", "args": {"income": 1_000_000},
              "result": {"best": {"p_sustained_10y": 1.0}}}] * 5
    assert not evals.grade("", other, m)["checks"]["families_sustainable"]


def test_lessons_can_be_switched_off_to_test_a_playbook_alone():
    from keystone.agents.runtime import Hierarchy, ScriptedPolicy
    memory.add_lesson("land_lead", "Shortlist a 20% buffer above the target.", "r1", "target_buffer_20pct")
    on, off = Hierarchy(policy="scripted"), Hierarchy(policy="scripted", use_lessons=False)
    assert ScriptedPolicy(on)._lesson_on("land_lead", "buffer")
    assert not ScriptedPolicy(off)._lesson_on("land_lead", "buffer")
    assert "20% buffer" not in memory.system_prompt("land_lead", use_lessons=False)


def test_fairness_measures_every_sizeable_group():
    groups = registry.champion("market_gap")["metrics"]["fairness_by_group"]
    assert "Black or African American" in groups  # n~120 a year in OC; the old 300 minimum silently dropped it
    assert "Race Not Available" in groups and any(k.startswith("ethnicity:") for k in groups)


def test_promotion_requires_the_gain_to_clear_the_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REG", tmp_path / "registry.json")
    registry.propose("m", "a", {"auc": 0.70}, {}, primary="auc")
    noisy = registry.propose("m", "b", {"auc": 0.71}, {}, primary="auc", min_gain=0.002,
                             checks=[(False, "AUC gain 95% CI [-0.003, +0.012]")])
    assert noisy["status"] == "rejected"
    clear = registry.propose("m", "c", {"auc": 0.72}, {}, primary="auc", min_gain=0.002, checks=[(True, "CI clears")])
    assert clear["status"] == "champion"


def test_rescore_keeps_the_gate_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REG", tmp_path / "registry.json")
    registry.propose("playbook:x", "old", {"eval_score": 0.667}, {}, primary="eval_score")
    registry.rescore("playbook:x", {"eval_score": 1.0})  # today's suite says the champion already scores 1.0
    assert registry.propose("playbook:x", "worse", {"eval_score": 0.9}, {}, primary="eval_score")["status"] == "rejected"
