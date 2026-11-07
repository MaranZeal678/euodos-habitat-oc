"""The desktop app's child-process plumbing. (The packaged app itself is smoke-tested end to end by
packaging/build_macos.sh, locally and in the desktop CI workflow.)"""
import sys

from keystone import launch


def test_from_source_children_are_plain_python():
    assert launch.python_code_cmd("print(1)") == [sys.executable, "-I", "-c", "print(1)"]
    assert launch.mcp_server_cmd() == (sys.executable, ["-m", "keystone.mcp_server.server"])


def test_packaged_app_reinvokes_itself_in_a_child_mode(monkeypatch):
    monkeypatch.setattr(launch, "FROZEN", True)
    assert launch.python_code_cmd("print(1)") == [sys.executable, launch.PYTHON_MODE, "print(1)"]
    assert launch.mcp_server_cmd() == (sys.executable, [launch.MCP_MODE])


def test_dispatch_runs_child_code_and_ignores_normal_launches(capsys):
    assert launch.dispatch(["Euodos", launch.PYTHON_MODE, "print('child ran')"])
    assert "child ran" in capsys.readouterr().out
    assert not launch.dispatch(["Euodos"])
    assert not launch.dispatch(["Euodos", "--smoke"])
