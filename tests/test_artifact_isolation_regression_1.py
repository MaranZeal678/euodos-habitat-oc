# Regression: ISSUE-002 — test runs wrote mock agent runs into the real artifacts/ directory
# Found by /qa on 2026-11-01
# Report: .gstack/qa-reports/run-20261101T040942Z/qa-report-localhost-2026-11-01.md
from keystone import config, skills
from keystone.agents import memory, runtime
from keystone.sandbox import runner

REAL_ARTIFACTS = config.ROOT / "artifacts"


def test_tests_never_write_to_real_artifacts():
    for path in (runtime.RUNS, runner.AUDIT, skills.DIR, memory.DIR):
        assert REAL_ARTIFACTS not in path.resolve().parents and path.resolve() != REAL_ARTIFACTS, path
