import pytest
from fastapi.testclient import TestClient

from keystone import skills
from keystone.agents import memory, runtime
from keystone.sandbox import runner


@pytest.fixture(autouse=True)
def isolated_artifacts(tmp_path, monkeypatch):
    """Every test writes runs, audit logs, skills and agent memory under its own tmp dir, never the product's artifacts/."""
    art = tmp_path / "artifacts"
    for sub in ("runs", "skills", "memory"):
        (art / sub).mkdir(parents=True)
    monkeypatch.setenv("KEYSTONE_STATE_DIR", str(art))  # child processes (the stdio MCP server) compute their paths from this
    monkeypatch.setattr(runtime, "RUNS", art / "runs")
    monkeypatch.setattr(runner, "AUDIT", art / "sandbox_audit.jsonl")
    monkeypatch.setattr(skills, "DIR", art / "skills")
    monkeypatch.setattr(skills, "INDEX", art / "skills" / "index.json")
    monkeypatch.setattr(memory, "DIR", art / "memory")
    monkeypatch.setattr(memory, "LESSONS", art / "memory" / "lessons.json")
    monkeypatch.setattr(memory, "PLAYBOOKS", art / "memory" / "playbooks.json")
    return art


@pytest.fixture(scope="session")
def client():
    """One app lifespan per test process, exactly like a uvicorn worker: MCP's session manager can only start once.
    Server errors come back as 500 responses (not raised) so tests assert on what a real client would see."""
    from keystone.app import server
    with TestClient(server.app, raise_server_exceptions=False) as c:
        yield c
