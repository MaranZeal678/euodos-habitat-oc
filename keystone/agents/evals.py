"""Eval missions + code graders over the run's final state (tau-bench style) and the brief itself.

Graders check outcomes, not phrasing: did the plan reach the target, does every family have a design that meets
the sustainability bar, are all URLs real (no hallucinated citations), were assumptions disclosed, was a sensitivity
analysis actually executed in the sandbox, was model fairness reported. Each failing grader yields a lesson
addressed to the agent responsible, which becomes Reflexion memory.
"""
import json
import re

from keystone import config, research

KNOWN_URLS = set(config.SOURCES.values()) | {c["url"] for c in research.CITATIONS} | {
    "https://www.hcd.ca.gov/funding/hosn", "https://www.fhlbsf.com/products/community-programs-grants/ahp",
    "https://ffiec.cfpb.gov/data-browser/"}

FAMILIES = [
    {"name": "Garcia (4, warehouse + childcare)", "income": 92_000, "household_size": 4, "savings": 4_000, "monthly_debts": 350, "income_volatility": 1.2},
    {"name": "Nguyen (3, nurse aide)", "income": 71_000, "household_size": 3, "savings": 6_500, "monthly_debts": 200, "income_volatility": 1.0},
    {"name": "Okafor (5, rideshare + retail)", "income": 108_000, "household_size": 5, "savings": 2_500, "monthly_debts": 600, "income_volatility": 1.6},
]

MISSIONS = [
    {"name": "Keys to 100 — countywide", "target_homes": 100, "families": FAMILIES},
    {"name": "First 40 homes — North OC", "target_homes": 40, "city": "Anaheim", "families": FAMILIES[:2]},
    {"name": "Keys to 100 — higher-risk cohort", "target_homes": 100, "families": FAMILIES[2:]},
]


def mission_text(m):
    return ("Plan the next phase of Habitat for Humanity Orange County's Keys to 100 program. "
            "Return a program brief. Mission parameters (JSON): " + json.dumps(m))


def grade(report, tool_results, mission):
    g = {}
    plans = [t["result"] for t in tool_results if t["tool"] == "capital_plan"]
    sited = max([p.get("homes_sited", 0) for p in plans] + [0])
    nums = [int(n.replace(",", "")) for n in re.findall(r"(\d[\d,]*) units vs target", report)]
    shortlisted = max(nums + [0])
    g["reaches_target"] = (shortlisted >= mission["target_homes"] or
                           (sited >= mission["target_homes"] and not mission.get("city")))
    g["target_buffer_20pct"] = shortlisted >= 1.2 * mission["target_homes"]
    opts = [t["result"]["best"] for t in tool_results if t["tool"] == "mortgage_optimize"]
    g["families_sustainable"] = len(opts) >= len(mission["families"]) and all(o["p_sustained_10y"] >= 0.95 for o in opts)
    urls = set(re.findall(r"https?://[^\s)\]|>,]+", report))
    urls = {u.rstrip(".;") for u in urls}
    g["citations_present"] = len(urls) >= 5
    g["no_hallucinated_urls"] = all(u in KNOWN_URLS for u in urls)
    g["assumptions_disclosed"] = "assumption" in report.lower()
    g["sensitivity_run"] = any(t["tool"] == "sandbox_run_python" and t["result"].get("ok") and t["agent"] == "capital_lead"
                               for t in tool_results)
    g["fairness_reported"] = "fairness" in report.lower()
    g["diversified_sites"] = bool(re.search(r"\| (\d+) \|\n", report)) and not any(
        int(u) > 30 for u in re.findall(r"\| [\d.]+ \| (\d+) \|", report))
    score = sum(g.values()) / len(g)
    return {"score": round(score, 3), "checks": g, "bad_urls": sorted(u for u in urls if u not in KNOWN_URLS)}


LESSONS = {
    "target_buffer_20pct": ("land_lead", "Shortlist at least 20% more units than the target (buffer) because some congregations will decline."),
    "diversified_sites": ("land_lead", "Cap any single site at 30 units and diversify across mid-size sites to limit congregation risk."),
    "sensitivity_run": ("capital_lead", "Always run a sensitivity sweep in the sandbox over hard cost and note discount rate before reporting the gap."),
    "fairness_reported": ("director", "Report the market-gap model's fairness metrics (calibration gap by race group) from models_registry in the brief."),
    "no_hallucinated_urls": ("director", "Only cite URLs returned by research_lookup or tools; drop any other URL."),
    "assumptions_disclosed": ("director", "State explicitly which inputs are assumptions (costs, hazard rates, per-unit public funding)."),
    "families_sustainable": ("underwriter", "If no design reaches 95% sustained ownership, raise the reserve fund and use income-indexed payments before reporting."),
    "citations_present": ("director", "Cite at least five sources with URLs from research_lookup."),
    "reaches_target": ("land_lead", "Keep adding sites until the shortlist reaches the unit target; widen the city filter if needed."),
}


def lessons_from(result):
    return [(LESSONS[k][0], LESSONS[k][1], k) for k, ok in result["checks"].items() if not ok and k in LESSONS]
