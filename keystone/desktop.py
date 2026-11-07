"""Euodos desktop app: the whole product (dashboard, demo, agents, MCP) in a native macOS window.

  python -m keystone.desktop                              # from source
  open Euodos.app                                       # packaged (packaging/build_macos.sh)
  Euodos.app/Contents/MacOS/Euodos --smoke            # start headless, prove the critical paths work, exit

The app runs Euodos's own server on a private localhost port and shows it in a WebKit window. Runs, skills and agent
lessons live in ~/Library/Application Support/Euodos, so they survive app updates.
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

# launch imports nothing else from keystone: child modes must start before config is read
from keystone import launch

_HTTP = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())  # keeps the scenario's session cookie


def _get(url, timeout=120):
    with _HTTP.open(url, timeout=timeout) as r:
        return r.read()


def _post(url, body, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with _HTTP.open(req, timeout=timeout) as r:
        return json.loads(r.read())


def smoke(url):
    """The paths a packaged app can break (bundled data, sandbox child, MCP child, agent mission), checked end to end."""
    checks = {}
    h = json.loads(_get(url + "/healthz"))
    checks["healthz"] = h["ok"]
    checks["sandbox"] = h["sandbox"]["ok"]
    checks["dashboard"] = b"Euodos" in _get(url + "/")
    checks["demo"] = b"Euodos" in _get(url + "/demo")
    checks["optimize"] = _post(url + "/api/optimize", {"income": 92_000})["best"]["p_sustained_10y"] > 0.5
    # the scenario: sign in, load the seed, pull a lever
    from keystone.app.server import DEMO_LOGIN
    _post(url + "/api/session", {"email": DEMO_LOGIN["email"], "password": DEMO_LOGIN["password"]})
    scn = json.loads(_get(url + "/api/scenario"))
    moved = _post(url + "/api/scenario/levers", {"levers": {"sb4_ministerial": False}})
    checks["scenario"] = scn["headlines"]["clock"]["value"] == "2.4 years" and moved["timeline"]["keystone"]["months"] > 28.2
    checks["film"] = b"startFilm" in _get(url + "/scenario")
    rid = _post(url + "/api/mission", {"policy": "scripted"})["run_id"]
    run = {}
    for _ in range(360):  # the mission starts the MCP server as a child of the app binary
        run = json.loads(_get(f"{url}/api/runs/{rid}"))
        if run.get("grade") or run.get("error"):
            break
        time.sleep(0.5)
    checks["mission"] = (run.get("grade") or {}).get("score", 0) == 1.0
    print(json.dumps({"checks": checks, "mission_error": run.get("error")}, indent=2))
    return 0 if all(checks.values()) else 1


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if launch.dispatch(argv):  # a child process of the app (sandboxed Python, stdio MCP server), not the UI
        return 0
    os.environ.setdefault("KEYSTONE_STATE_DIR", str(Path.home() / "Library" / "Application Support" / "Euodos"))
    os.environ["KEYSTONE_HOST"] = "127.0.0.1"  # a desktop app is never a network service
    os.environ.setdefault("KEYSTONE_DEMO_LOGIN", "1")  # the seeded demo account (sessions are private; nothing persists)
    import uvicorn

    from keystone.app import server
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(600):
        if srv.started:
            break
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    if "--smoke" in argv:
        code = smoke(url)
    else:
        import webview
        from webview.menu import Menu, MenuAction, MenuSeparator

        windows = []  # filled once the window exists; menu actions run later, on the UI thread

        def go(path):
            return lambda: windows[0].load_url(url + path)
        # a desktop window has no address bar or Back button, so navigation lives in a native menu
        menu = [Menu("Go", [MenuAction("Crossline scenario", go("/scenario")), MenuAction("Dashboard", go("/")),
                            MenuAction("30-second film", go("/scenario?film&play")),
                            MenuAction("Mission-control demo", go("/demo")), MenuSeparator(),
                            MenuAction("Reload", lambda: windows[0].evaluate_js("location.reload()"))])]
        windows.append(webview.create_window("Euodos", url + "/scenario", width=1440, height=920, min_size=(1000, 680), menu=menu))
        state = Path(os.environ["KEYSTONE_STATE_DIR"])
        webview.start(private_mode=False, storage_path=str(state / "webview"))  # remembers the last tab between launches
        code = 0
    srv.should_exit = True
    t.join(10)
    return code


if __name__ == "__main__":
    sys.exit(main())
