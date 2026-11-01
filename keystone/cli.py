"""python -m keystone.cli [--mission N] [--policy auto|claude|scripted]"""
import argparse
import asyncio
import json

from keystone.agents import evals
from keystone.agents.runtime import Hierarchy


async def main(i, policy):
    m = evals.MISSIONS[i]
    async with Hierarchy(policy=policy) as h:
        print(f"run {h.run_id} · policy {h.policy_name} · mission: {m['name']}")
        report = await h.mission(evals.mission_text(m))
        res = evals.grade(report, h.tool_results, m)
        (h.trace.dir / "grade.json").write_text(json.dumps(res, indent=2))
        print(report)
        print("\nGRADE", json.dumps(res, indent=2))
        print(f"\ntrace: {h.trace.path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mission", type=int, default=0)
    ap.add_argument("--policy", default="auto")
    a = ap.parse_args()
    asyncio.run(main(a.mission, a.policy))
