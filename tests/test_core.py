import pytest

from keystone import tools
from keystone.agents import evals
from keystone.models import registry
from keystone.models import sustainability as sus
from keystone.sandbox.runner import run_python


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "REG", tmp_path / "registry.json")


def test_gate_promotes_retires_and_rejects(tmp_registry):
    registry.propose("m", "a", {"auc": 0.70, "fair": 0.02}, {}, primary="auc")
    registry.propose("m", "b", {"auc": 0.72, "fair": 0.02}, {}, primary="auc", guardrails={"fair": 0.005})
    c = registry.propose("m", "c", {"auc": 0.80, "fair": 0.09}, {}, primary="auc", guardrails={"fair": 0.005})
    registry.propose("m", "d", {"auc": 0.721, "fair": 0.02}, {}, primary="auc", min_gain=0.01)
    statuses = [e["status"] for e in registry.history("m")]
    assert statuses == ["retired", "champion", "rejected", "rejected"]
    assert registry.champion("m")["path"] == "b"
    assert "FAIL" in " ".join(c["decision_reasons"])


def test_sandbox_blocks_network_and_host_writes(tmp_path):
    assert run_python("import socket")["blocked"]
    r = run_python("import importlib\ns = importlib.import_module('soc' + 'ket')\ns.create_connection(('example.com', 80), timeout=3)")
    assert not r["ok"]
    target = tmp_path.parent / "keystone_escape_test.txt"
    r = run_python(f"open({str(target)!r}, 'w').write('x')")
    assert not r["ok"] and not target.exists()
    r = run_python("import os\nprint(os.environ.get('ANTHROPIC_API_KEY'))")
    assert r["ok"] and r["stdout"].strip() == "None"


def test_sandbox_can_use_keystone():
    r = run_python("from keystone.models import sustainability as s\n"
                   "print(s.simulate(s.Family(), s.Home(), s.Design(), n_paths=200)['p_sustained_10y'] > 0.5)")
    assert r["ok"] and r["stdout"].strip() == "True"


def test_underwriting_respects_payment_cap():
    f = sus.Family(income=90_000)
    uw = sus.underwrite(f, sus.Home(), sus.Design(payment_cap=0.30))
    assert abs(uw["front_end_ratio"] - 0.30) < 1e-6
    assert uw["first_mortgage"] + uw["silent_second"] + uw["down_payment"] == pytest.approx(750_000)


def test_stewardship_and_payment_matter():
    f = sus.Family(income=85_000, savings=2_000, income_volatility=1.5)
    good = sus.simulate(f, sus.Home(), sus.Design(), n_paths=1500)
    no_steward = sus.simulate(f, sus.Home(), sus.Design(stewardship=False), n_paths=1500)
    heavy = sus.simulate(f, sus.Home(), sus.Design(payment_cap=0.45), n_paths=1500)
    assert good["p_sustained_10y"] > no_steward["p_sustained_10y"]
    assert good["p_ever_90dpd"] < heavy["p_ever_90dpd"]


def test_grader_catches_hallucinated_urls():
    report = "assumption fairness " + " ".join(f"https://example.com/{i}" for i in range(6))
    g = evals.grade(report, [], evals.MISSIONS[0])
    assert not g["checks"]["no_hallucinated_urls"] and len(g["bad_urls"]) == 6


def test_income_limits_classify():
    r = tools.income_limits(4, 90_000)
    assert r["category"] == "very_low" and r["habitat_oc_eligible_band"]


def test_site_search_uses_cnn_scores():
    r = tools.sites_search(limit=5)
    assert r["total_matches"] > 50 and all(s["units_townhome"] >= 4 for s in r["sites"])


def test_parking_cnn_champion_runs_inference():
    import numpy as np

    from keystone.models import cnn
    arr = np.random.default_rng(0).integers(0, 255, (4, 61, 77), dtype=np.uint8)  # odd sizes exercise the padding
    p = cnn.segment(arr)
    assert p.shape == (61, 77) and np.isfinite(p).all() and 0 <= p.min() and p.max() <= 1
