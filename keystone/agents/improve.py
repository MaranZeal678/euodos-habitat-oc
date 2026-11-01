"""Self-improvement loop for the agent hierarchy.

Each generation:
  1. run every eval mission through the hierarchy (current playbooks + lesson memory)
  2. grade final state with code graders; failing checks become Reflexion lessons for the responsible agent
  3. propose a challenger playbook per implicated agent (Claude rewrites it from its lessons when credentials exist;
     offline, lessons are folded in as rules) and re-run the evals with the challenger
  4. promote through the same deterministic gate as the ML models (registry.propose), never on the LLM's say-so

  python -m keystone.agents.improve --generations 2
"""
import argparse
import asyncio
import json

from keystone.agents import evals, memory
from keystone.agents.runtime import Hierarchy, _has_credentials
from keystone.config import ARTIFACTS
from keystone.models import registry

LOG = ARTIFACTS / "improve_log.json"


async def run_suite(policy, overrides=None, tag=""):
    scores, runs = [], []
    for m in evals.MISSIONS:
        async with Hierarchy(policy=policy, playbook_overrides=overrides) as h:
            report = await h.mission(evals.mission_text(m))
            res = evals.grade(report, h.tool_results, m)
            (h.trace.dir / "grade.json").write_text(json.dumps(res, indent=2))
            scores.append(res["score"]); runs.append((h.run_id, m, res))
            print(f"  {tag}{m['name']:<36} score {res['score']:.2f}  failing: {[k for k, v in res['checks'].items() if not v]}")
    return sum(scores) / len(scores), runs


async def rewrite_playbook(agent, policy):
    current = memory.playbook(agent)["text"]
    ls = [l["lesson"] for l in memory.lessons(agent)]
    if policy == "claude":
        import anthropic
        client = anthropic.AsyncAnthropic()
        resp = await client.messages.create(
            model="claude-opus-5-5", max_tokens=4000, thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            messages=[{"role": "user", "content":
                       f"Rewrite this agent playbook so it permanently incorporates the lessons. Keep it under 150 words, "
                       f"imperative voice, no preamble.\n\nPLAYBOOK:\n{current}\n\nLESSONS:\n" + "\n".join(ls)}])
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    return current + " Rules learned: " + " ".join(ls)


async def main(generations=2, policy="auto"):
    if policy == "auto":
        policy = "claude" if _has_credentials() else "scripted"
    log = json.loads(LOG.read_text()) if LOG.exists() else []
    print(f"policy={policy}")
    base, runs = await run_suite(policy, tag="[champion] ")
    for gen in range(generations):
        implicated = set()
        for run_id, m, res in runs:
            for agent, lesson, grader in evals.lessons_from(res):
                memory.add_lesson(agent, lesson, run_id, grader)
                implicated.add(agent)
        if not implicated:
            print(f"gen {gen}: all graders pass (score {base:.3f}); nothing to improve")
            break
        overrides = {a: await rewrite_playbook(a, policy) for a in implicated}
        chal, chal_runs = await run_suite(policy, overrides, tag="[challenger] ")
        version = registry.new_version()
        decisions = {}
        for a, text in overrides.items():
            entry = registry.propose(f"playbook:{a}", text, {"eval_score": round(chal, 4)},
                                     {"lessons": len(memory.lessons(a)), "policy": policy},
                                     primary="eval_score", min_gain=0.0)
            # registry compares against the previous champion score; seed it with the baseline on first use
            if entry["status"] == "champion":
                memory.set_playbook(a, text, f"v{gen + 1}-{version}")
            decisions[a] = entry["status"]
        promoted = chal > base
        print(f"gen {gen}: baseline {base:.3f} -> challenger {chal:.3f}; decisions {decisions}")
        log.append({"generation": len(log), "policy": policy, "baseline": round(base, 4), "challenger": round(chal, 4),
                    "implicated": sorted(implicated), "decisions": decisions, "promoted": promoted})
        LOG.write_text(json.dumps(log, indent=2))
        if promoted:
            base, runs = chal, chal_runs
    return log


def seed_baseline_scores(score):
    """Register the v0 playbooks as champions with the baseline score so challengers must beat it."""
    for a in ("director", "land_lead", "capital_lead", "underwriter", "family_lead", "site_analyst"):
        if registry.champion(f"playbook:{a}") is None:
            registry.propose(f"playbook:{a}", memory.playbook(a)["text"], {"eval_score": round(score, 4)},
                             {"seed": True}, primary="eval_score")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=2)
    ap.add_argument("--policy", default="auto")
    args = ap.parse_args()

    async def go():
        pol = args.policy if args.policy != "auto" else ("claude" if _has_credentials() else "scripted")
        if registry.champion("playbook:director") is None:
            base, _ = await run_suite(pol, tag="[seed] ")
            seed_baseline_scores(base)
        await main(args.generations, pol)

    asyncio.run(go())
