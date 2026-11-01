"""How Keystone starts its own child processes, whether it runs from source or as the packaged desktop app.

From source, children are ordinary `python -I -c` / `python -m` invocations. Inside the PyInstaller bundle there is no
Python interpreter to call, only the app binary, so the app re-invokes itself in a child mode that `dispatch` handles
before any UI starts.
"""
import sys

FROZEN = bool(getattr(sys, "frozen", False))
PYTHON_MODE, MCP_MODE = "--keystone-python", "--keystone-mcp"


def python_code_cmd(code):
    """argv that runs a snippet of Python in a fresh, isolated process."""
    return [sys.executable, PYTHON_MODE, code] if FROZEN else [sys.executable, "-I", "-c", code]


def mcp_server_cmd():
    """(command, args) that serve the Keystone MCP server over stdio."""
    return (sys.executable, [MCP_MODE]) if FROZEN else (sys.executable, ["-m", "keystone.mcp_server.server"])


def dispatch(argv):
    """Run a child mode of the packaged app if argv asks for one; returns True when it did."""
    if len(argv) > 2 and argv[1] == PYTHON_MODE:
        exec(compile(argv[2], "<keystone-child>", "exec"), {"__name__": "__main__"})  # noqa: S102 - the sandbox's own launcher code
        return True
    if len(argv) > 1 and argv[1] == MCP_MODE:
        from keystone.mcp_server.server import app
        app.run("stdio")
        return True
    return False
