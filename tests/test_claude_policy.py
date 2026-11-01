"""Exercise the Claude policy's agent loop against a scripted fake Messages API (no credentials needed)."""
import asyncio
import json
from types import SimpleNamespace as NS

from keystone.agents import runtime


class FakeMessages:
    """Director delegates to two leads in parallel; leads call one MCP tool then answer."""

    def __init__(self):
        self.requests = []

    async def create(self, **kw):
        self.requests.append(kw)
        system, msgs, tools = kw["system"], kw["messages"], {t["name"] for t in kw["tools"]}
        last = msgs[-1]["content"]
        usage = NS(input_tokens=10, output_tokens=5)
        first_turn = isinstance(last, str)
        if "Director" in system and first_turn:
            return NS(stop_reason="tool_use", usage=usage, content=[
                NS(type="tool_use", id="d1", name="delegate", input={"agent": "land_lead", "task": "find sites"}),
                NS(type="tool_use", id="d2", name="delegate", input={"agent": "capital_lead", "task": "size gap"})])
        if "Land acquisition" in system and first_turn:
            return NS(stop_reason="tool_use", usage=usage, content=[
                NS(type="tool_use", id="l1", name="sites_search", input={"limit": 2})])
        if "Capital lead" in system and first_turn:
            return NS(stop_reason="tool_use", usage=usage, content=[
                NS(type="tool_use", id="c1", name="market_gap_report", input={"year": 2024})])
        results = [b for b in last if isinstance(b, dict) and b.get("type") == "tool_result"] if not first_turn else []
        assert tools  # every agent got a tool list
        return NS(stop_reason="end_turn", usage=usage,
                  content=[NS(type="text", text=f"done with {len(results)} results: " + " | ".join(r["content"][:40] for r in results))])


def test_claude_policy_loop(monkeypatch):
    fake = FakeMessages()

    class FakeClient:
        beta = NS(messages=fake)

    async def go():
        monkeypatch.setattr(runtime, "_has_credentials", lambda: True)
        async with runtime.Hierarchy(policy="claude") as h:
            h.policy.client = FakeClient()
            out = await h.mission("Plan 10 homes")
            return out, h

    out, h = asyncio.run(go())
    assert out.startswith("done with 2 results")
    agents = [json.loads(l) for l in h.trace.path.read_text().splitlines()]
    started = {e["agent"] for e in agents if e["type"] == "agent_start"}
    assert {"director", "land_lead", "capital_lead"} <= started
    tools_called = {e["tool"] for e in agents if e["type"] == "tool"}
    assert {"sites_search", "market_gap_report"} <= tools_called
    req = fake.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["thinking"] == {"type": "adaptive"}
    assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
    director_tools = {t["name"] for t in req["tools"]}
    assert director_tools == {"research_lookup", "models_registry", "delegate", "ledger_update"}  # least privilege
