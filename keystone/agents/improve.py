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
import statistics

from keystone.agents import evals, memory
from keystone.agents.runtime import Hierarchy, _has_credentials
from keystone.config import ARTIFACTS
from keystone.models import registry

LOG = ARTIFACTS / "improve_log.json"


async def run_suite(policy, overrides=None, tag="", use_lessons=True, repeats=1):
    """Mean grade over the eval missions (and over `repeats` runs, for a stochastic policy) plus its standard error."""
    scores, runs = [], []
    for _ in range(repeats):
        for m in evals.MISSIONS:
            async with Hierarchy(policy=policy, playbook_overrides=overrides, use_lessons=use_lessons) as h:
                report = await h.mission(evals.mission_text(m))
                res = evals.grade(report, h.tool_results, m)
                (h.trace.dir / "grade.json").write_text(json.dumps(res, indent=2))
                scores.append(res["score"]); runs.append((h.run_id, m, res))
                print(f"  {tag}{m['name']:<36} score {res['score']:.2f}  failing: {[k for k, v in res['checks'].items() if not v]}")
    mean = sum(scores) / len(scores)
    per_rep = [sum(scores[i:i + len(evals.MISSIONS)]) / len(evals.MISSIONS) for i in range(0, len(scores), len(evals.MISSIONS))]
    se = statistics.stdev(per_rep) / len(per_rep) ** 0.5 if len(per_rep) > 1 else 0.0
    return mean, se, runs


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
    """Two kinds of learning, measured separately so neither gets credit for the other:
      - lessons (Reflexion memory) from failing graders; their effect is the champion re-run with the new lessons
      - playbook promotion (consolidation): each implicated agent's rewritten playbook is tested alone, with lessons
        OFF, against the champion playbooks also with lessons off, so it is promoted only if its text carries the
        improvement by itself (what a fresh deploy with no lesson memory relies on)
    A stochastic policy (Claude) repeats every suite and must beat the champion by more than twice the standard error."""
    if policy == "auto":
        policy = "claude" if _has_credentials() else "scripted"
    repeats = 3 if policy == "claude" else 1  # the scripted policy is deterministic: one run is the exact score
    log = json.loads(LOG.read_text()) if LOG.exists() else []
    print(f"policy={policy} repeats={repeats}")
    base, _, runs = await run_suite(policy, tag="[system] ", repeats=repeats)
    for gen in range(generations):
        implicated = set()
        for run_id, m, res in runs:
            for agent, lesson, grader in evals.lessons_from(res):
                memory.add_lesson(agent, lesson, run_id, grader)
                implicated.add(agent)
        if not implicated:
            print(f"gen {gen}: all graders pass (score {base:.3f}); nothing to improve")
            break
        after_lessons, _, runs = await run_suite(policy, tag="[+lessons] ", repeats=repeats)
        ref, ref_se, _ = await run_suite(policy, tag="[champion, no lessons] ", use_lessons=False, repeats=repeats)
        ref_start = ref
        decisions, challengers, version = {}, {}, registry.new_version()
        for a in sorted(implicated):
            text = await rewrite_playbook(a, policy)
            chal, chal_se, _ = await run_suite(policy, {a: text}, tag=f"[{a} challenger, no lessons] ", use_lessons=False,
                                               repeats=repeats)
            challengers[a] = round(chal, 4)
            registry.rescore(f"playbook:{a}", {"eval_score": round(ref, 4)})
            entry = registry.propose(f"playbook:{a}", text, {"eval_score": round(chal, 4)},
                                     {"lessons": len(memory.lessons(a)), "policy": policy, "tested_without_lessons": True},
                                     primary="eval_score", min_gain=2 * max(ref_se, chal_se))
            if entry["status"] == "champion":
                memory.set_playbook(a, text, f"v{gen + 1}-{version}")
                ref, ref_se = chal, chal_se  # the next agent must beat the team that now includes this playbook
            decisions[a] = entry["status"]
        print(f"gen {gen}: system {base:.3f} -> {after_lessons:.3f} with lessons; playbooks alone {ref_start:.3f}, then "
              f"challengers in turn {challengers}; decisions {decisions}")
        log.append({"generation": len(log), "policy": policy, "baseline": round(base, 4), "challenger": round(after_lessons, 4),
                    "lesson_gain": round(after_lessons - base, 4), "playbook_only_champion": round(ref_start, 4), "playbook_only_after": round(ref, 4),
                    "playbook_challengers": challengers, "implicated": sorted(implicated), "decisions": decisions,
                    "promoted": any(d == "champion" for d in decisions.values())})
        LOG.write_text(json.dumps(log, indent=2))
        base = after_lessons
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
            base, _, _ = await run_suite(pol, tag="[seed] ", use_lessons=False)
            seed_baseline_scores(base)
        await main(args.generations, pol)

    asyncio.run(go())
