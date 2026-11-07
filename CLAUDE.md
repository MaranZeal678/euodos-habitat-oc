# Euodos

Agentic operating system for Habitat for Humanity of Orange County's Keys to 100. Python 3.13 in `.venv` (uv).
Run tests with `make test`, serve with `make serve` (dashboard `/`, demo `/demo`, MCP `/mcp`).

## Health Stack

- lint: .venv/bin/ruff check keystone tests scripts
- typecheck: .venv/bin/pyright keystone
- test: .venv/bin/python -m pytest -q tests
- deadcode: .venv/bin/vulture keystone --min-confidence 80

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. Route only to skills in the session's available-skills list; answer directly for quick questions or small scoped edits.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate, unless one read-only check confirms the cause and a narrow fix (then fix it and run the focused test)
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
