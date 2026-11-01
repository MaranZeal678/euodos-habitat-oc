"""Champion/challenger model registry with deterministic promotion gates.

Agents may *recommend* retraining, but only this code decides promotion (pattern from
Lim et al. 2026, arXiv:2606.03321): a challenger is promoted only if it beats the champion's
primary metric on the same frozen holdout by at least `min_gain`, and passes any guardrails
(e.g. a fairness gap that must not widen).
"""
import json
import time
from datetime import datetime, timezone

from keystone.config import ARTIFACTS

REG = ARTIFACTS / "registry.json"


def _load():
    return json.loads(REG.read_text()) if REG.exists() else {}


def _save(r):
    REG.write_text(json.dumps(r, indent=2))


def new_version():
    return time.strftime("%Y%m%d_%H%M%S")


def champion(name):
    entries = _load().get(name, [])
    champs = [e for e in entries if e["status"] == "champion"]
    return champs[-1] if champs else None


def history(name=None):
    r = _load()
    return r if name is None else r.get(name, [])


def propose(name, path, metrics, params, primary, higher_is_better=True, min_gain=0.0,
            guardrails=None, data_version=None):
    """guardrails: {metric: max_allowed_increase} checked against the champion (lower is better for those)."""
    r = _load()
    entries = r.setdefault(name, [])
    champs = [e for e in entries if e["status"] == "champion"]
    champ = champs[-1] if champs else None  # same object as in `entries`, so retiring it persists
    entry = {"version": new_version(), "path": path, "metrics": metrics, "params": params,
             "primary": primary, "data_version": data_version,
             "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    reasons = []
    if champ is None:
        decision = True
        reasons.append("no champion yet")
    else:
        cm, nm = champ["metrics"][primary], metrics[primary]
        gain = (nm - cm) if higher_is_better else (cm - nm)
        decision = gain > min_gain
        reasons.append(f"{primary}: challenger {nm} vs champion {cm} (gain {gain:+.4f}, need > {min_gain})")
        for g, tol in (guardrails or {}).items():
            if g in metrics and g in champ["metrics"]:
                ok = metrics[g] <= champ["metrics"][g] + tol
                reasons.append(f"guardrail {g}: {metrics[g]} vs {champ['metrics'][g]} (+{tol} allowed) -> {'ok' if ok else 'FAIL'}")
                decision = decision and ok
    entry["status"] = "champion" if decision else "rejected"
    entry["decision_reasons"] = reasons
    if decision and champ is not None:
        champ["status"] = "retired"
    entries.append(entry)
    _save(r)
    return entry
