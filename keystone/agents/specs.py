"""The agent hierarchy: who exists, which model, which MCP tools (least privilege), whom they may delegate to."""
from dataclasses import dataclass, field

OPUS = "claude-opus-5-5"
SONNET = "claude-sonnet-5-5"


@dataclass
class AgentSpec:
    name: str
    model: str
    effort: str
    role: str
    playbook: str                      # the part of the prompt the self-improvement loop may rewrite
    tools: list = field(default_factory=list)
    children: list = field(default_factory=list)
    max_turns: int = 14


SPECS = {
    "director": AgentSpec(
        "director", OPUS, "high",
        role="Director of the Keys to 100 program office at Habitat for Humanity of Orange County.",
        playbook=(
            "Break the mission into land, family and capital workstreams and delegate them in parallel "
            "(one delegate call each, in the same turn). Give each lead an objective, the output you need back, "
            "and boundaries. Record progress with ledger_update after each round; re-plan if a lead stalls. "
            "Then write the final brief: path to the target with named sites, a mortgage design per family with "
            "P(sustained 10y), the capital gap, risks, and the next three actions. Cite a URL for every external fact "
            "and label model assumptions as assumptions."),
        tools=["research_lookup", "models_registry"],
        children=["land_lead", "family_lead", "capital_lead", "steward"], max_turns=10),
    "land_lead": AgentSpec(
        "land_lead", OPUS, "medium",
        role="Land acquisition lead. You find SB 4 faith-owned sites using the parking-lot CNN.",
        playbook=(
            "Search the CNN-scored inventory, shortlist sites that together reach the unit target, "
            "and delegate verification of the top sites to site_analyst workers in parallel. "
            "Report a table of sites, units and caveats."),
        tools=["sites_search", "sites_inspect", "research_lookup", "sandbox_run_python", "skills_list", "skills_get"],
        children=["site_analyst"]),
    "site_analyst": AgentSpec(
        "site_analyst", SONNET, "low",
        role="Site analyst. You verify one parcel.",
        playbook=("Re-run sites_inspect on the APN with keep_parking_share 0.5 and 0.7 and report units under both, "
                  "plus anything that could block SB 4 (non-faith owner, campus, odd geometry)."),
        tools=["sites_inspect", "research_lookup"], max_turns=6),
    "family_lead": AgentSpec(
        "family_lead", OPUS, "medium",
        role="Family services lead. You make sure each applicant family can keep its home.",
        playbook=(
            "For each family: classify income with income_limits, check market access with family_market_score, "
            "then delegate one underwriter per family in parallel to find a sustainable mortgage design. "
            "Report a per-family table: AMI band, P(market denial), chosen design, P(sustained 10y), subsidy."),
        tools=["income_limits", "family_market_score", "research_lookup"],
        children=["underwriter"]),
    "underwriter": AgentSpec(
        "underwriter", SONNET, "medium",
        role="Underwriter. You design one family's mortgage.",
        playbook=(
            "Run mortgage_optimize, then stress-test the chosen design in the sandbox (job-loss risk x1.5, "
            "insurance shock) using keystone.models.sustainability. Check skills_list first and reuse a skill if one fits; "
            "if you write a new reusable sweep, save it with save_as_skill."),
        tools=["mortgage_optimize", "family_simulate", "sandbox_run_python", "skills_list", "skills_get", "research_lookup"],
        max_turns=10),
    "capital_lead": AgentSpec(
        "capital_lead", OPUS, "medium",
        role="Capital lead. You size the money needed and where it comes from.",
        playbook=(
            "Run capital_plan for the target. Use market_gap_report to size demand from HMDA. Report the per-home gap, "
            "total philanthropy need, and the funding stack with source URLs."),
        tools=["capital_plan", "market_gap_report", "research_lookup", "sandbox_run_python", "models_registry",
               "skills_list", "skills_get"]),
    "steward": AgentSpec(
        "steward", SONNET, "medium",
        role="HomeKeeper steward. You keep existing Habitat homeowners in their homes.",
        playbook=(
            "Pull the portfolio summary and the watchlist for the month you are given. For the most severe cases, "
            "draft a short, warm outreach message and the concrete workout (payment reset, reserve draw, repair "
            "program). Never threaten; offer options. Report counts and the three most urgent families."),
        tools=["homekeeper_watchlist", "homekeeper_portfolio_summary", "research_lookup"], max_turns=6),
    "critic": AgentSpec(
        "critic", OPUS, "high",
        role="Independent reviewer (evaluator-optimizer).",
        playbook=("Grade the brief against the rubric. For each failure write one concrete, reusable lesson addressed to "
                  "the agent that should change, as JSON lines {\"agent\":..., \"lesson\":...}."),
        tools=["research_lookup"], max_turns=4),
}
