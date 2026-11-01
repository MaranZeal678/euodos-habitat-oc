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


def test_child_processes_never_write_to_real_artifacts(isolated_artifacts):
    # Agent missions start the MCP server as a subprocess; in-process monkeypatching never reached it, so its sandbox
    # audit and skills writes landed in the real artifacts/. The state dir is an env var the child inherits.
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-c", ("from keystone import skills; from keystone.agents import memory, runtime; "
                          "from keystone.sandbox import runner; print(runtime.RUNS, runner.AUDIT, skills.DIR, memory.DIR)")],
                         capture_output=True, text=True, check=True, cwd=config.ROOT).stdout.split()
    assert len(out) == 4
    for p in out:
        assert str(isolated_artifacts) in p, p
