"""Clear it: how long from a land offer to families moving in, and which levers shorten it.

A project is a small dependency graph of phases. The clock is its critical path (the longest chain of dependent
phases). Keystone's levers change the graph, not the laws of physics:

  instant_screen   the site is already CNN-scored and SB 4-screened, so screening takes days, not months
  sb4_ministerial  SB 4's streamlined ministerial approval replaces discretionary entitlement and CEQA review
  parallel_funding the capital package (gap, sources, applications) is drafted on day one, so funding runs during
                   the land deal and approval instead of after them

Every duration carries a source or an "estimate" label. Estimates are planning inputs a user can edit.
"""
from dataclasses import dataclass

SOURCES = {
    "lab": {"label": "Impact Lab brief, Lane 2: 'How do we turn four years into two?'", "url": None},
    "hcd_sb4": {"label": "HCD SB 4 fact sheet: ministerial approval, no discretionary or CEQA review",
                "url": "https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/aff-hsg-faith-higher-ed-sb-4.pdf"},
    "sf_sb4": {"label": "SF Planning, SB 4 streamlined approval: roughly 90-180 days",
               "url": "https://sfplanning.org/node/3069"},
    "pew": {"label": "Pew 2024: discretionary approval median 6 months (Oakland) to 25+ months (San Francisco)",
            "url": "https://pewtrusts.org/it/research-and-analysis/issue-briefs/2024/08/reforms-spur-faster-housing-approvals-in-california"},
    "terner_finance": {"label": "Terner Center 2025: 10+ months from first funding application to award with a second public source",
                       "url": "https://davisvanguard.org/2025/05/california-affordable-housing-finance/"},
}


@dataclass(frozen=True)
class Phase:
    key: str
    name: str
    months: float
    after: tuple = ()
    source: str | None = None  # a SOURCES key; None means the duration is an estimate
    lever: str | None = None   # the lever that produced this version of the phase, if any


ESTIMATES = {  # editable planning inputs (months), labelled as estimates wherever they appear
    "screen": 6.0, "land_deal": 4.0, "entitlement": 12.0, "permits": 4.0, "construction": 14.0, "families": 6.0,
}


def phases(levers=None, estimates=None, approval=None):
    """The project graph for a lever setting. Baseline = every lever off. `approval` names the ministerial path
    (from models.pathways) when it is not SB 4; its 6-month duration is then an estimate, not SF Planning's SB 4 range."""
    lv = {"instant_screen": False, "sb4_ministerial": False, "parallel_funding": False} | (levers or {})
    est = ESTIMATES | (estimates or {})
    screen = Phase("screen", "Find and screen a site", 0.25, (), None, "instant_screen") if lv["instant_screen"] \
        else Phase("screen", "Find and screen a site", est["screen"])
    land = Phase("land_deal", "Agreement with the congregation", est["land_deal"], ("screen",))
    named = approval if approval and approval != "SB 4 ministerial approval" else None
    approval = Phase("entitlement", named or "SB 4 ministerial approval", 6.0, ("land_deal",),
                     None if named else "sf_sb4", "sb4_ministerial") if lv["sb4_ministerial"] \
        else Phase("entitlement", "Discretionary entitlement + CEQA", est["entitlement"], ("land_deal",), "pew")
    funding = Phase("funding", "CalHome + AHP applications to award", 10.0,
                    ("screen",) if lv["parallel_funding"] else ("entitlement",), "terner_finance",
                    "parallel_funding" if lv["parallel_funding"] else None)
    permits = Phase("permits", "Building permits", est["permits"], ("entitlement", "funding"))
    build = Phase("construction", "Construction", est["construction"], ("permits",))
    families = Phase("families", "Select and pre-qualify 30 families", est["families"],
                     ("screen",) if lv["parallel_funding"] else ("permits",))
    return [screen, land, approval, funding, permits, build, families]


def schedule(levers=None, estimates=None, approval=None):
    """Earliest start/finish per phase and the critical path (the chain that sets the finish date)."""
    ps = {p.key: p for p in phases(levers, estimates, approval)}
    finish, start, prev = {}, {}, {}

    def fin(k):
        if k not in finish:
            p = ps[k]
            deps = [(fin(d), d) for d in p.after]
            s, prev[k] = max(deps) if deps else (0.0, None)
            start[k], finish[k] = s, s + p.months
        return finish[k]

    for k in ps:
        fin(k)
    end_key = max(finish, key=lambda k: finish[k])
    path, k = [], end_key
    while k:
        path.append(k)
        k = prev[k]
    rows = [{"key": p.key, "name": p.name, "start": round(start[p.key], 2), "months": p.months,
             "critical": p.key in path, "lever": p.lever,
             "source": SOURCES[p.source] if p.source else {"label": "estimate (editable planning input)", "url": None}}
            for p in ps.values()]
    return {"months": round(finish[end_key], 1), "years": round(finish[end_key] / 12, 1), "critical_path": path[::-1], "phases": rows}


def compare(levers=None, estimates=None, approval=None):
    """Baseline (no levers) against the chosen lever setting, plus what each lever saves on its own."""
    on = {"instant_screen": True, "sb4_ministerial": True, "parallel_funding": True} | (levers or {})
    base, keystone = schedule({}, estimates), schedule(on, estimates, approval)
    alone = {k: round(base["months"] - schedule({k: True}, estimates)["months"], 1) for k in on}
    return {"baseline": base, "keystone": keystone, "saved_months": round(base["months"] - keystone["months"], 1),
            "lever_savings_alone": alone, "levers": on, "estimates": ESTIMATES | (estimates or {}),
            "baseline_source": SOURCES["lab"]}
