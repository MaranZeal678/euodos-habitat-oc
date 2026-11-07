"""Clear it: which legal path fits one address, and what each costs in time.

Seven paths to housing in California, each with its own statute, review type, clock and tests. A path is
evaluated against a project (homes, tenure, owner, zoning, city streamlining status). Every test returns
met / to verify / fails; a missing fact is "to verify", never assumed. Clocks are quoted only where a source
was read; otherwise the clock is "unknown" and says which section to read.

Statute numbers use the current numbering (ADU law moved from Gov Code 65852.2 to 66310-66342 in 2024).
Sources were read on CHECKED via the Impact Lab's Lane 2 DATA-SOURCES list and HCD's own documents.
"""
CHECKED = "2026-11-07"

LEGINFO = "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=GOV&sectionNum="
SOURCES = {
    "sb4_fact": {"label": "HCD Housing Law Fact Sheet, SB 4 (Gov 65913.16), April 2026",
                 "url": "https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/aff-hsg-faith-higher-ed-sb-4.pdf"},
    "sb35_guide": {"label": "HCD Streamlined Ministerial Approval (SB 35) Guidelines, Section 301(b)",
                   "url": "https://www.hcd.ca.gov/policy-research/docs/SB-35-Guidelines-Update-Final.pdf"},
    "smap": {"label": "HCD SB 35 / SB 423 determination dashboard (is streamlining available in this city?)",
             "url": "https://www.hcd.ca.gov/planning-and-community-development/streamlined-ministerial-approval-process-dashboard"},
    "sb9_fact": {"label": "HCD SB 9 Fact Sheet (lot splits and duplexes)",
                 "url": "https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/sb-9-fact-sheet.pdf"},
    "adu_handbook": {"label": "HCD ADU Handbook, March 2026", "url": "https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/adu-handbook-update.pdf"},
    "gov66314": {"label": "Gov Code 66314 (ADU approvals: ministerial, 60 days)", "url": LEGINFO + "66314"},
    "gov66411_7": {"label": "Gov Code 66411.7 (SB 9 urban lot split: 60-day clock)", "url": LEGINFO + "66411.7"},
    "gov66499_41": {"label": "Gov Code 66499.41 (SB 684 / SB 1123: ministerial map, 10 or fewer parcels)", "url": LEGINFO + "66499.41"},
    "lab_timeline": {"label": "Impact Lab Lane 2 timeline.json: rezoning about 1 year, entitlements about 1 year (ASSUMPTION)",
                     "url": "https://github.com/travcjohnson/claude-impact-lab-uci/blob/main/lanes/2-clear-it/data/timeline.json"},
}

PROJECT = {  # the Crossline defaults; any field may be "unknown"
    "homes": 30, "tenure": "ownership", "lower_income_share": 1.0,
    "faith_owner_since_2024": "unknown",   # OSM says place of worship; a title record would settle it
    "zoning": "unknown",                    # unknown | single_family | multifamily | nonresidential
    "city_streamlining": "unknown",         # unknown | yes | no (HCD SB 35 determination)
    "hazards_clear": "unknown",             # fire, flood, fault, wetland screens
    "existing_home_on_lot": False,
}

ZONES = {"unknown": "unknown", "single_family": "single-family residential", "multifamily": "multifamily residential",
         "nonresidential": "non-residential (e.g. institutional)"}


def _t(test, status, note, source=None):
    return {"test": test, "status": status, "note": note, "source": SOURCES[source] if source else None}


def _known(v, yes, no=None):
    """Map a yes/no/unknown fact to a test status."""
    return "verify" if v in (None, "unknown") else ("met" if v == yes or (no is not None and v != no) else "fails")


def _sb4(p):
    return [
        _t("Owned by a religious institution as of January 1, 2024", _known(p["faith_owner_since_2024"], "yes"),
           "OpenStreetMap tags a place of worship; a title record confirms ownership and date", "sb4_fact"),
        _t("100% lower-income homes (up to 20% moderate)", "met" if p["lower_income_share"] >= 0.8 else "fails",
           "Habitat sells to households at or under 80% of AMI", "sb4_fact"),
        _t("Allowed in every zone, including non-residential", "met", "zoning does not block SB 4", "sb4_fact"),
        _t("Not in a very high fire hazard zone, flood hazard area, fault zone or wetland", _known(p["hazards_clear"], "yes"),
           "screens not run here", "sb4_fact"),
        _t("Phase I environmental site assessment", "verify", "required before ministerial approval", "sb4_fact"),
    ]


def _sb35(p):
    zone = p["zoning"]
    return [
        _t("City is subject to SB 35 / SB 423 streamlining", _known(p["city_streamlining"], "yes"),
           "look the city up on HCD's determination dashboard", "smap"),
        _t("Zoned for residential or mixed use", "verify" if zone == "unknown" else ("fails" if zone == "nonresidential" else "met"),
           f"zoning: {ZONES[zone]}", "sb35_guide"),
        _t("Multifamily: two or more homes", "met" if p["homes"] >= 2 else "fails", f"{p['homes']} homes", "sb35_guide"),
        _t("Meets the city's required affordable share", "met" if p["lower_income_share"] >= 0.5 else "verify",
           "100% affordable meets any required share", "sb35_guide"),
        _t("Not on an excluded site (fire, flood, fault, wetland and others)", _known(p["hazards_clear"], "yes"),
           "screens not run here", "sb35_guide"),
    ]


def _sb684(p):
    n = p["homes"]
    return [
        _t("10 or fewer parcels", "met" if n <= 10 else "fails",
           f"{n} for-sale homes need {n} lots or condo units" if n > 10 else f"{n} homes", "gov66499_41"),
        _t("Other eligibility tests (zone, lot size)", "verify", "not read in detail here: read 66499.41 before relying on it", "gov66499_41"),
    ]


def _sb9(p, split):
    zone, n = p["zoning"], p["homes"]
    cap = 4 if split else 2
    return [
        _t("Single-family residential zone", "verify" if zone == "unknown" else ("met" if zone == "single_family" else "fails"),
           f"zoning: {ZONES[zone]}", "sb9_fact"),
        _t(f"At most {cap} homes" + (" (two lots, two homes each)" if split else " on the lot"), "met" if n <= cap else "fails",
           f"{n} homes", "sb9_fact"),
    ]


def _adu(p):
    return [
        _t("An existing or planned primary home on the lot", "met" if p["existing_home_on_lot"] else "fails",
           "ADUs are accessory to a main home, not a for-sale subdivision", "adu_handbook"),
        _t("Units accessory to that home, not separate for-sale homes", "fails" if p["tenure"] == "ownership" and p["homes"] > 2 else "verify",
           f"{p['homes']} for-sale homes", "adu_handbook"),
    ]


def _discretionary(p):
    return [_t("Rezoning or plan amendment, entitlement and CEQA review", "met", "always available; slowest and can be denied", "lab_timeline")]


PATHS = [
    {"key": "sb4", "short": "SB 4", "name": "SB 4 faith-land by right", "law": "SB 4 (2023)", "statute": "Gov Code 65913.16", "review": "ministerial",
     "tests": _sb4, "clock": "City must flag conflicts within 60 days and finish design review within 90 (150 homes or fewer)",
     "days": 90, "clock_source": "sb4_fact", "phase": "SB 4 ministerial approval",
     "note": "Subdivisions consistent with the local subdivision ordinance are CEQA-exempt, which helps the condo map. Prevailing wage applies."},
    {"key": "sb35", "short": "SB 35 / 423", "name": "SB 35 / SB 423 streamlined", "law": "SB 35 (2017), SB 423 (2023)", "statute": "Gov Code 65913.4", "review": "ministerial",
     "tests": _sb35, "clock": "Consistency within 60 days, approval within 90 days of submittal (150 homes or fewer)",
     "days": 90, "clock_source": "sb35_guide", "phase": "SB 35 / SB 423 streamlined approval", "note": ""},
    {"key": "sb684", "short": "SB 684", "name": "SB 684 small-lot map", "law": "SB 684 (2023), SB 1123 (2024)", "statute": "Gov Code 66499.41", "review": "ministerial",
     "tests": _sb684, "clock": "Unknown here: read 66499.41 (companion permit rule 65913.4.5 allows a building permit before the final map)",
     "days": None, "clock_source": "gov66499_41", "phase": "SB 684 ministerial map", "note": "Fits a first phase of 10 or fewer homes."},
    {"key": "sb9_units", "short": "SB 9 duplex", "name": "SB 9 two-unit", "law": "SB 9 (2021)", "statute": "Gov Code 65852.21", "review": "ministerial",
     "tests": lambda p: _sb9(p, split=False), "clock": "Ministerial; 30-day completeness check", "days": None, "clock_source": "sb9_fact",
     "phase": "SB 9 two-unit approval", "note": ""},
    {"key": "sb9_split", "short": "SB 9 split", "name": "SB 9 lot split", "law": "SB 9 (2021)", "statute": "Gov Code 66411.7", "review": "ministerial",
     "tests": lambda p: _sb9(p, split=True), "clock": "60 days", "days": 60, "clock_source": "gov66411_7",
     "phase": "SB 9 lot split approval", "note": "Requires a three-year owner-occupancy affidavit."},
    {"key": "adu", "short": "ADU", "name": "ADU", "law": "ADU law", "statute": "Gov Code 66314", "formerly": "65852.2", "review": "ministerial",
     "tests": _adu, "clock": "60 days from a complete application", "days": 60, "clock_source": "gov66314",
     "phase": "ADU permit", "note": "Old number 65852.2 still appears in some city checklists."},
    {"key": "discretionary", "short": "Rezone", "name": "Rezone + entitlement", "law": "Local zoning, CEQA", "statute": "local code", "review": "discretionary",
     "tests": _discretionary, "clock": "About 2 years: rezoning about 1, entitlements about 1 (ASSUMPTION)", "days": 730,
     "clock_source": "lab_timeline", "phase": "Discretionary entitlement + CEQA", "note": "Hearings, discretion, appeals."},
]
BY_KEY = {p["key"]: p for p in PATHS}


def evaluate(project=None):
    """Every path's verdict for a project, fastest viable first, plus the recommended path."""
    p = PROJECT | (project or {})
    out = []
    for path in PATHS:
        checks = path["tests"](p)
        statuses = [c["status"] for c in checks]
        verdict = "no" if "fails" in statuses else ("verify" if "verify" in statuses else "fits")
        out.append({k: path[k] for k in ("key", "short", "name", "law", "statute", "review", "clock", "days", "phase", "note")}
                   | {"formerly": path.get("formerly"), "statute_url": LEGINFO + path["statute"].split()[-1] if path["statute"].startswith("Gov") else None,
                      "clock_source": SOURCES[path["clock_source"]], "checks": checks, "verdict": verdict,
                      "to_verify": statuses.count("verify"), "failing": [c["test"] for c in checks if c["status"] == "fails"]})
    rank = {"fits": 0, "verify": 1, "no": 2}
    # viable before ruled out; ministerial (no hearing, no discretion) before discretionary; then fewer open checks, faster clock
    out.sort(key=lambda r: (r["verdict"] == "no", r["review"] != "ministerial", rank[r["verdict"]], r["days"] or 10_000, r["to_verify"]))
    recommended = next(r["key"] for r in out if r["verdict"] != "no")
    return {"project": p, "paths": out, "recommended": recommended, "checked": CHECKED}
