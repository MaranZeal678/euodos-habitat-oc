"""Hierarchical agent runtime over MCP.

One stdio MCP connection to the Keystone server is shared by every agent; each agent only sees the tools its spec
allows. Agents with children get a `delegate` tool; parallel delegate calls in one turn fan out concurrently
(orchestrator-workers, Anthropic 2025). Every event goes to a JSONL trace the dashboard renders as a tree.

Two policies drive the same hierarchy:
  - ClaudePolicy: Claude Opus 5.5 (leads) / Sonnet 5.5 (workers) via the Messages API with adaptive thinking
  - ScriptedPolicy: deterministic offline stand-in (no credentials needed) that makes the same kinds of tool calls,
    so the pipeline, trace, graders and self-improvement loop can be demonstrated anywhere.
"""
import asyncio
import contextvars
import json
import os
import sys
import time
import uuid
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from keystone.agents import memory
from keystone.agents.specs import SPECS
from keystone.config import ARTIFACTS, ROOT

RUNS = ARTIFACTS / "runs"
RUNS.mkdir(exist_ok=True)
MAX_DEPTH = 3
CURRENT_NODE = contextvars.ContextVar("node", default=None)  # asyncio tasks inherit it, so tool calls know their agent node


class Trace:
    def __init__(self, run_id):
        self.dir = RUNS / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "trace.jsonl"
        self.tokens = {"input": 0, "output": 0}

    def log(self, **ev):
        ev["ts"] = round(time.time(), 3)
        with open(self.path, "a") as f:
            f.write(json.dumps(ev, default=str) + "\n")


class Hierarchy:
    def __init__(self, policy="auto", run_id=None, playbook_overrides=None):
        self.run_id = run_id or time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        self.trace = Trace(self.run_id)
        self.overrides = playbook_overrides or {}
        self.policy_name = policy
        self.sem = asyncio.Semaphore(6)
        self.tool_results = []   # structured results for graders/dashboard

    # ------------------------------------------------------------ MCP plumbing
    async def __aenter__(self):
        self.stack = AsyncExitStack()
        params = StdioServerParameters(command=sys.executable, args=["-m", "keystone.mcp_server.server"], cwd=str(ROOT),
                                       env={**os.environ, "PYTHONPATH": str(ROOT)})
        r, w = await self.stack.enter_async_context(stdio_client(params))
        self.mcp = await self.stack.enter_async_context(ClientSession(r, w))
        await self.mcp.initialize()
        listed = await self.mcp.list_tools()
        self.mcp_tools = {t.name: t for t in listed.tools}
        if self.policy_name == "auto":
            self.policy_name = "claude" if _has_credentials() else "scripted"
        self.policy = ClaudePolicy(self) if self.policy_name == "claude" else ScriptedPolicy(self)
        self.trace.log(type="run_start", run_id=self.run_id, policy=self.policy_name, tools=list(self.mcp_tools))
        return self

    async def __aexit__(self, *exc):
        await self.stack.aclose()

    async def call_tool(self, agent, name, args, depth):
        if name not in SPECS[agent].tools:
            return {"error": f"{agent} is not permitted to call {name}"}
        t0 = time.time()
        res = await self.mcp.call_tool(name, args)
        text = "".join(getattr(c, "text", "") for c in res.content)
        try:
            data = json.loads(text)
        except ValueError:
            data = {"text": text}
        self.tool_results.append({"agent": agent, "tool": name, "args": args, "result": data})
        self.trace.log(type="tool", agent=agent, node=CURRENT_NODE.get(), depth=depth, tool=name, args=args, secs=round(time.time() - t0, 2),
                       error=bool(res.is_error), summary=_summarize(data))
        return data

    # ------------------------------------------------------------ agents
    async def run_agent(self, agent, task, depth=0, parent=None):
        node = f"{agent}#{uuid.uuid4().hex[:5]}"
        self.trace.log(type="agent_start", agent=agent, node=node, parent=parent, depth=depth, task=task,
                       model=SPECS[agent].model, playbook_version=memory.playbook(agent)["version"])
        token = CURRENT_NODE.set(node)
        try:
            async with self.sem if not SPECS[agent].children else _null():  # only leaf workers are throttled, so no deadlock
                out = await self.policy.run(agent, task, depth, node)
        finally:
            CURRENT_NODE.reset(token)
        self.trace.log(type="agent_end", agent=agent, node=node, parent=parent, depth=depth, output=out[:6000])
        return out

    async def delegate(self, parent_agent, parent_node, child, task, depth):
        if child not in SPECS[parent_agent].children:
            return f"error: {parent_agent} cannot delegate to {child}"
        if depth + 1 > MAX_DEPTH:
            return "error: max delegation depth reached"
        return await self.run_agent(child, task, depth + 1, parent_node)

    async def mission(self, text):
        report = await self.run_agent("director", text)
        (self.trace.dir / "report.md").write_text(report)
        (self.trace.dir / "tool_results.json").write_text(json.dumps(self.tool_results, default=str))
        self.trace.log(type="run_end", tokens=self.trace.tokens)
        return report


class _null:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _has_credentials():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.path.exists(os.path.expanduser("~/.config/anthropic")))


def _summarize(d):
    s = json.dumps(d, default=str)
    return s[:400] + ("..." if len(s) > 400 else "")


# ====================================================================== Claude policy
class ClaudePolicy:
    def __init__(self, h: Hierarchy):
        import anthropic
        self.h = h
        self.client = anthropic.AsyncAnthropic()
        self.anthropic = anthropic

    def _tools(self, agent):
        spec = SPECS[agent]
        tools = []
        for name in spec.tools:
            t = self.h.mcp_tools[name]
            tools.append({"name": t.name, "description": (t.description or "")[:1000], "input_schema": t.input_schema})
        if spec.children:
            tools.append({"name": "delegate", "description":
                          "Hand a self-contained sub-task to a subordinate agent. Call several in one turn to run them in "
                          "parallel. The subordinate sees only `task`, so include objective, inputs, output format, limits.",
                          "input_schema": {"type": "object", "properties": {
                              "agent": {"type": "string", "enum": spec.children},
                              "task": {"type": "string"}}, "required": ["agent", "task"]}})
        if agent == "director":
            tools.append({"name": "ledger_update", "description": "Record the progress ledger: facts, plan, done, blockers.",
                          "input_schema": {"type": "object", "properties": {
                              "facts": {"type": "array", "items": {"type": "string"}},
                              "plan": {"type": "array", "items": {"type": "string"}},
                              "done": {"type": "array", "items": {"type": "string"}},
                              "blockers": {"type": "array", "items": {"type": "string"}}}}})
        return tools

    async def run(self, agent, task, depth, node):
        spec = SPECS[agent]
        system = memory.system_prompt(agent, self.h.overrides.get(agent))
        messages = [{"role": "user", "content": task}]
        tools = self._tools(agent)
        for turn in range(spec.max_turns):
            resp = await self.client.beta.messages.create(
                model=spec.model, max_tokens=16000, system=system, messages=messages, tools=tools,
                thinking={"type": "adaptive"}, output_config={"effort": spec.effort},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            self.h.trace.tokens["input"] += resp.usage.input_tokens
            self.h.trace.tokens["output"] += resp.usage.output_tokens
            if resp.stop_reason == "refusal":
                return f"[{agent} declined: {getattr(resp, 'stop_details', None)}]"
            messages.append({"role": "assistant", "content": resp.content})
            calls = [b for b in resp.content if b.type == "tool_use"]
            text = "".join(b.text for b in resp.content if b.type == "text")
            if text.strip():
                self.h.trace.log(type="thought", agent=agent, node=node, depth=depth, text=text[:2000])
            if resp.stop_reason != "tool_use" or not calls:
                return text

            async def run_call(b):
                try:
                    if b.name == "delegate":
                        out = await self.h.delegate(agent, node, b.input["agent"], b.input["task"], depth)
                    elif b.name == "ledger_update":
                        self.h.trace.log(type="ledger", agent=agent, node=node, **b.input)
                        out = "ledger recorded"
                    else:
                        out = json.dumps(await self.h.call_tool(agent, b.name, b.input, depth), default=str)[:30000]
                    return {"type": "tool_result", "tool_use_id": b.id, "content": out}
                except Exception as e:  # noqa: BLE001 - any tool failure goes back to the model as an is_error result
                    return {"type": "tool_result", "tool_use_id": b.id, "content": f"error: {e}", "is_error": True}

            results = await asyncio.gather(*(run_call(b) for b in calls))
            messages.append({"role": "user", "content": list(results)})
        return f"[{agent} hit max_turns]"


# ====================================================================== offline scripted policy
class ScriptedPolicy:
    """Deterministic stand-in for Claude so the system runs without credentials. Reads the same playbooks and
    lessons (a few lesson keywords switch behaviours on), calls the same MCP tools, delegates the same way."""

    def __init__(self, h: Hierarchy):
        self.h = h

    def _lesson_on(self, agent, *words):
        txt = " ".join(l["lesson"].lower() for l in memory.lessons(agent))
        txt += " " + (self.h.overrides.get(agent) or memory.playbook(agent)["text"]).lower()
        return any(w in txt for w in words)

    async def run(self, agent, task, depth, node):
        return await getattr(self, agent)(task, depth, node)

    async def director(self, task, depth, node):
        m = json.loads(task[task.index("{"):]) if "{" in task else {}
        target = m.get("target_homes", 100)
        families = m.get("families", [])
        self.h.trace.log(type="ledger", agent="director", node=node, facts=[f"target {target} homes", f"{len(families)} families"],
                         plan=["land_lead: shortlist SB4 sites", "family_lead: design mortgages", "capital_lead: size gap"],
                         done=[], blockers=[])
        land, fam, cap, stew = await asyncio.gather(
            self.h.delegate("director", node, "land_lead", json.dumps({"target_homes": target, "city": m.get("city")}), depth),
            self.h.delegate("director", node, "family_lead", json.dumps({"families": families}), depth),
            self.h.delegate("director", node, "capital_lead", json.dumps({"target_homes": target}), depth),
            self.h.delegate("director", node, "steward", json.dumps({"month": m.get("portfolio_month", 36)}), depth))
        self.h.trace.log(type="ledger", agent="director", node=node, facts=[], plan=[],
                         done=["land", "families", "capital"], blockers=[])
        cites = (await self.h.call_tool("director", "research_lookup", {"topic": "stewardship"}, depth))["citations"]
        cites += (await self.h.call_tool("director", "research_lookup", {"topic": "faith land"}, depth))["citations"]
        refs = "\n".join(f"- {c['cite']} {c['url']} — {c['finding']}" for c in cites)
        fair = ""
        if self._lesson_on("director", "fairness"):
            reg = await self.h.call_tool("director", "models_registry", {"name": "market_gap"}, depth)
            champ = [e for e in reg["history"] if e["status"] == "champion"][-1]
            fair = (f"\n## Model governance\nMarket-gap model {champ['version']} (AUC {champ['metrics']['auc']}), "
                    f"max race-group calibration gap {champ['metrics']['fairness_gap']}; protected attributes excluded "
                    f"from features and promotion is gated on fairness (Fuster et al. 2022, https://doi.org/10.1111/jofi.13090).\n")
        return (f"# Keys to {target}: program brief\n\n_Mission: {m.get('name', 'Keys to 100')}_ · policy: offline scripted\n\n"
                f"## 1. Land\n{land}\n\n## 2. Families\n{fam}\n\n## 3. Capital\n{cap}\n{fair}\n"
                f"## 4. Existing homeowners (HomeKeeper)\n{stew}\n\n"
                f"## Next three actions\n1. Title-check the shortlisted APNs and open SB 4 conversations with the top congregations.\n"
                f"2. Pre-qualify applicant families with the designs above; enrol all in post-purchase stewardship.\n"
                f"3. Submit CalHome + FHLBank SF AHP applications sized to the per-home gap.\n\n"
                f"Model inputs not drawn from a cited source are assumptions (see keystone://assumptions).\n\n## Evidence\n{refs}\n")

    async def land_lead(self, task, depth, node):
        m = json.loads(task)
        target = m.get("target_homes", 100)
        res = await self.h.call_tool("land_lead", "sites_search", {"city": m.get("city"), "limit": 25}, depth)
        buffer = 1.2 if self._lesson_on("land_lead", "buffer") else 1.0
        cap = 30 if self._lesson_on("land_lead", "diversif", "mid-size") else 200
        picked, units = [], 0
        for s in res["sites"]:
            if units >= target * buffer:
                break
            picked.append(s); units += min(s["units_townhome"], cap)
        checks = await asyncio.gather(*(self.h.delegate("land_lead", node, "site_analyst", json.dumps({"apn": s["apn"], "name": s["name"]}), depth)
                                        for s in picked[:4]))
        rows = "\n".join(f"| {s['name']} | {s['city']} | {s['apn']} | {s['developable_acres']} | {min(s['units_townhome'], cap)} |" for s in picked)
        return (f"{res['total_matches']} viable faith-owned parcels in the CNN inventory ({res['total_townhome_units']} townhome units). "
                f"Shortlist: {len(picked)} sites, {units} units vs target {target}.\n\n| Site | City | APN | Dev. acres | Units |\n|---|---|---|---|---|\n{rows}\n\n"
                f"Verification:\n" + "\n".join(f"- {c}" for c in checks) +
                f"\n\nMethod: {res['method']}. Source: SB 4 fact sheet https://www.hcd.ca.gov/sites/default/files/docs/planning-and-community/aff-hsg-faith-higher-ed-sb-4.pdf")

    async def site_analyst(self, task, depth, node):
        m = json.loads(task)
        a = await self.h.call_tool("site_analyst", "sites_inspect", {"apn": m["apn"], "keep_parking_share": 0.5}, depth)
        b = await self.h.call_tool("site_analyst", "sites_inspect", {"apn": m["apn"], "keep_parking_share": 0.7}, depth)
        if "error" in a:
            return f"{m['name']}: {a['error']}"
        flag = " (large campus: confirm ownership and SB 4 eligibility)" if a["parcel_sqm"] > 60000 else ""
        return (f"{m['name']} ({m['apn']}): {a['units_townhome']} units at 50% parking kept, {b['units_townhome']} at 70%; "
                f"CNN parking {a['parking_sqm']:,} m²{flag}")

    async def family_lead(self, task, depth, node):
        fams = json.loads(task)["families"]
        rows, briefs = [], []
        for f in fams:
            lim = await self.h.call_tool("family_lead", "income_limits", {"household_size": f["household_size"], "income": f["income"]}, depth)
            mk = await self.h.call_tool("family_lead", "family_market_score", {"income": f["income"], "price": 750000,
                                                                                "monthly_debts": f.get("monthly_debts", 300)}, depth)
            rows.append((f, lim, mk))
        outs = await asyncio.gather(*(self.h.delegate("family_lead", node, "underwriter", json.dumps(f), depth) for f, _, _ in rows))
        table = "| Family | Income | % AMI | Band | P(market denial) | Design | P(sustained 10y) | Subsidy PV |\n|---|---|---|---|---|---|---|---|\n"
        for (f, lim, mk), o in zip(rows, outs):
            d = json.loads(o)
            table += (f"| {f['name']} | ${f['income']:,} | {lim['pct_ami']}% | {lim['category']} | {mk['p_denied']:.0%} | "
                      f"{d['design']} | {d['p_sustained_10y']:.1%} | ${d['subsidy_cost']:,} |\n")
            briefs.append(f"- {f['name']}: stress test → {d.get('stress', 'n/a')}")
        return (table + "\nStress tests (sandbox):\n" + "\n".join(briefs) +
                "\n\nDesign logic: payment size and liquidity drive default (Ganong & Noel 2020, https://doi.org/10.1257/aer.20181243); "
                "stewardship cures most serious delinquencies (Thaden 2011). Income limits: CA HCD 2026 "
                "https://www.hcd.ca.gov/sites/default/files/docs/grants-and-funding/income-limits-2026.pdf")

    async def underwriter(self, task, depth, node):
        f = json.loads(task)
        args = {k: f[k] for k in ("income", "household_size", "savings", "monthly_debts", "income_volatility") if k in f}
        opt = await self.h.call_tool("underwriter", "mortgage_optimize", args, depth)
        best = opt["best"]
        dp = best["design_params"]
        skills = (await self.h.call_tool("underwriter", "skills_list", {}, depth))["skills"]
        if "stress_test_design" in skills:
            code = (await self.h.call_tool("underwriter", "skills_get", {"name": "stress_test_design"}, depth))["code"]
            save = None
        else:
            code = STRESS_SKILL
            save = "stress_test_design"
        header = f"FAMILY = {args!r}\nDESIGN = {({k: dp[k] for k in ('rate', 'term_years', 'payment_cap', 'reserve_fund', 'income_indexed')})!r}\n"
        run = await self.h.call_tool("underwriter", "sandbox_run_python",
                                     {"code": header + code, "save_as_skill": save, "skill_code": code,
                                      "skill_description": "Stress-test a mortgage design: job-loss x1.5 and insurance shocks"}, depth)
        stress = run["stdout"].strip() if run.get("ok") else f"sandbox error: {run.get('stderr', '')[:200]}"
        return json.dumps({"design": best["design"], "p_sustained_10y": best["p_sustained_10y"], "subsidy_cost": best["subsidy_cost"],
                           "stress": stress})

    async def capital_lead(self, task, depth, node):
        m = json.loads(task)
        plan = await self.h.call_tool("capital_lead", "capital_plan", {"target_homes": m.get("target_homes", 100)}, depth)
        gap = await self.h.call_tool("capital_lead", "market_gap_report", {"year": 2024}, depth)
        sens = ""
        if self._lesson_on("capital_lead", "sensitivity", "sweep"):
            run = await self.h.call_tool("capital_lead", "sandbox_run_python", {"code": CAPITAL_SWEEP}, depth)
            sens = "\n\nSensitivity (sandbox):\n```\n" + (run["stdout"] if run.get("ok") else run.get("stderr", "")) + "```"
        stack = "\n".join(f"- {s['name']}: {s['notes']} ({s['url']})" for s in plan["funding_sources"])
        return (f"Per-home cost ${plan['unit_cost']['total']:,} (hard ${plan['unit_cost']['hard']:,}, soft ${plan['unit_cost']['soft']:,}, land $0 via SB 4 ground lease — assumption). "
                f"Each 0% first mortgage has face value ${plan['first_mortgage_face']:,} but PV ${plan['first_mortgage_pv']:,} at 5%. "
                f"Gap after CalHome + AHP (assumed $100k/home): ${plan['per_unit_gap_after_public_sources']:,} per home → "
                f"${plan['philanthropy_needed_total']:,} philanthropy for {plan['target_homes']} homes.\n\n"
                f"Demand (HMDA 2024, real loan data): {gap['low_income_applications']:,} low-income OC purchase applications, "
                f"{gap['low_income_denial_rate']:.0%} denied, {gap['low_income_denial_reasons'].get('Debt-to-income ratio', 0)} for debt-to-income. "
                f"Source: https://ffiec.cfpb.gov/data-browser/\n\nFunding stack:\n{stack}{sens}")


    async def steward(self, task, depth, node):
        month = json.loads(task).get("month", 36)
        summ = await self.h.call_tool("steward", "homekeeper_portfolio_summary", {}, depth)
        wl = await self.h.call_tool("steward", "homekeeper_watchlist", {"month": month, "limit": 5}, depth)
        k, m = summ["summary"]["keystone"], summ["summary"]["market"]
        rows = "\n".join(f"- **{f['name']}** ({f['state']}; {', '.join(f['causes'])}): {f['action']}. Draft: "
                         f"\"Hi {f['name'].split()[0]}, this is your Habitat steward. We noticed things may be tight this month. "
                         f"We have options that can lower your payment for a while. Can we talk this week?\""
                         for f in wl["families"][:3])
        return (f"Portfolio of {summ['n_families']} homeowners ({summ['note']}). Over 10 years, {k['still_own']} keep their homes "
                f"with Keystone designs plus stewardship, against {m['still_own']} with market-rate loans. "
                f"The steward made {k['steward_contacts']} early contacts. At month {month}, {wl['n_at_risk']} families need attention. Most urgent:\n{rows}\n\n"
                f"Why stewardship: https://www.lincolninst.edu/publications/working-papers/stable-home-ownership-turbulent-economy/")


STRESS_SKILL = '''from keystone.models import sustainability as s
fam = s.Family(**FAMILY)
d = s.Design(**DESIGN)
base = s.simulate(fam, s.Home(), d, n_paths=1500)
risky = s.Family(**{**FAMILY, "income_volatility": FAMILY.get("income_volatility", 1.0) * 1.5})
a = dict(s.ASSUMPTIONS, insurance_shock_prob=0.15)
stressed = s.simulate(risky, s.Home(), d, n_paths=1500, a=a)
print(f"base {base['p_sustained_10y']:.1%} -> stressed {stressed['p_sustained_10y']:.1%} (job loss x1.5, insurance shock p=15%/yr)")
'''

CAPITAL_SWEEP = '''from keystone import config
from keystone.models import capital
from keystone.models.sustainability import Design, Family
base = dict(config.COST_ASSUMPTIONS)
print("hard$/sf  disc   gap/home   total(100)")
for hc in (325, 375, 425):
    for disc in (0.04, 0.05, 0.06):
        config.COST_ASSUMPTIONS["hard_cost_per_sqft"] = hc
        p = capital.plan(100, Family(), Design(), note_discount_rate=disc)
        print(f"{hc:>8} {disc:>5.0%} {p['per_unit_gap_after_public_sources']:>10,} {p['philanthropy_needed_total']:>12,}")
config.COST_ASSUMPTIONS.update(base)
'''
