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


URL = re.compile(r"https?://[^\s)\]|>,]+")
BARE_DOMAIN = re.compile(r"(?<![\w./@-])(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:gov|org|com|edu|net|io)\b(?:/[^\s)\]|>,]*)?", re.IGNORECASE)
SITE_ROW = re.compile(r"^\| [^|\n]+ \| [^|\n]* \| ([0-9A-Za-z-]+) \| [\d.]+ \| (\d+) \|$", re.MULTILINE)
ASSUMED = r"(hard cost|discount|calhome|ahp|job[- ]loss|hazard|appreciation|insurance|land|per-unit|funding)"


def _host(u):
    return re.sub(r"^(https?://)?(www\.)?", "", u.lower()).split("/")[0]


def grade(report, tool_results, mission):
    """Outcome checks that must be backed by the run's own tool results, so a brief cannot pass on keywords alone."""
    g = {}
    by_tool = lambda name: [t for t in tool_results if t["tool"] == name]
    target = mission["target_homes"]
    # land: every shortlisted unit must trace to a site the CNN search actually returned, at no more than its capacity
    found = {s["apn"]: s["units_townhome"] for t in by_tool("sites_search") for s in t["result"].get("sites", [])}
    rows = [(apn, int(u)) for apn, u in SITE_ROW.findall(report)]
    verified = sum(min(u, found[apn]) for apn, u in rows if apn in found)
    claimed = max([int(n.replace(",", "")) for n in re.findall(r"(\d[\d,]*) units vs target", report)] + [0])
    g["reaches_target"] = verified >= target and claimed <= verified
    g["target_buffer_20pct"] = g["reaches_target"] and verified >= 1.2 * target
    g["diversified_sites"] = len(rows) >= 2 and all(u <= 30 for _, u in rows)  # with the cap, reaching N needs N/30 sites
    # families: each mission family needs its own optimizer result at the sustainability bar
    opts = {round(t["args"].get("income", -1)): t["result"]["best"] for t in by_tool("mortgage_optimize")}
    g["families_sustainable"] = all(round(f["income"]) in opts and opts[round(f["income"])]["p_sustained_10y"] >= 0.95
                                    for f in mission["families"])
    # citations: real, distinct, known sources; bare domains count as citations too
    urls = {u.rstrip(".;") for u in URL.findall(report)}
    bare = {b.rstrip(".;") for b in BARE_DOMAIN.findall(URL.sub(" ", report))}
    known_hosts = {_host(u) for u in KNOWN_URLS}
    bad = sorted({u for u in urls if u not in KNOWN_URLS} | {b for b in bare if _host(b) not in known_hosts})
    g["citations_present"] = len(urls & KNOWN_URLS) >= 5
    g["no_hallucinated_urls"] = bool(urls) and not bad
    g["assumptions_disclosed"] = bool(re.search(rf"assumption.{{0,160}}{ASSUMED}|{ASSUMED}.{{0,160}}assumption", report, re.IGNORECASE | re.DOTALL))
    # capital: a sweep that actually varies hard cost, run by the capital lead, with a table of results
    g["sensitivity_run"] = any(t["agent"] == "capital_lead" and t["result"].get("ok") and "hard_cost" in t["args"].get("code", "")
                               and len(t["result"].get("stdout", "").strip().splitlines()) >= 3
                               for t in by_tool("sandbox_run_python"))
    # governance: the registry was consulted and its measured fairness gap is quoted
    gaps = {str(e["metrics"].get("fairness_gap")) for t in by_tool("models_registry") for e in t["result"].get("history", [])
            if e.get("status") == "champion"}
    g["fairness_reported"] = "fairness" in report.lower() and any(gp in report for gp in gaps if gp != "None")
    score = sum(g.values()) / len(g)
    return {"score": round(score, 3), "checks": g, "bad_urls": bad}


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
