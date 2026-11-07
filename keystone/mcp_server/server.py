"""Euodos MCP server: exposes the domain tools and sourced constants over the Model Context Protocol.

  python -m keystone.mcp_server.server                 # stdio (what the agent hierarchy uses)
  python -m keystone.mcp_server.server --http 8765     # Streamable HTTP (for Claude's MCP connector / other hosts)
"""
import json
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from keystone import config, tools
from keystone.models.sustainability import ASSUMPTIONS

app = MCPServer(
    "keystone",
    instructions="Orange County affordable-homeownership tools for Habitat for Humanity OC (Keys to 100). "
                 "Every number is sourced or labelled an assumption; cite sources in answers.",
)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
for fn in tools.TOOLS:
    app.tool(annotations=READ_ONLY if fn.__name__ != "sandbox_run_python" else
             ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))(fn)


@app.resource("keystone://sources")
def sources() -> str:
    """Source URLs for every constant used by the tools."""
    return json.dumps(config.SOURCES, indent=2)


@app.resource("keystone://assumptions")
def assumptions() -> str:
    """Labelled assumptions in the cost and sustainability models (agents should stress-test these)."""
    return json.dumps({"cost": config.COST_ASSUMPTIONS, "sustainability": ASSUMPTIONS,
                       "townhome_du_per_acre": config.TOWNHOME_DU_PER_ACRE}, indent=2)


if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--http") + 1])
        app.run("streamable-http", port=port)
    else:
        app.run("stdio")
