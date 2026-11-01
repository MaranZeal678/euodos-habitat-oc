# Keystone

Agentic operating system for Habitat for Humanity of Orange County's Keys to 100. Python 3.13 in `.venv` (uv).
Run tests with `make test`, serve with `make serve` (dashboard `/`, demo `/demo`, MCP `/mcp`).

## Health Stack

- lint: .venv/bin/ruff check keystone tests scripts
- typecheck: .venv/bin/pyright keystone
- test: .venv/bin/python -m pytest -q tests
- deadcode: .venv/bin/vulture keystone --min-confidence 80
