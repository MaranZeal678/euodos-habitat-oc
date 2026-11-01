"""Browser end-to-end: the real dashboard and demo in headless Chromium against a live server.

Every test also fails on any uncaught page error or console error, so a broken render cannot pass silently.
"""
import json
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

TABS = ["overview", "land", "families", "agents", "improve", "arch"]
# third-party basemap tiles are not the product; everything served by Keystone must load cleanly
IGNORED_CONSOLE = ("favicon.ico", "basemaps.cartocdn.com", "tile.openstreetmap", "tiles.openfreemap")


@pytest.fixture(scope="module")
def base_url():
    from keystone.app import server
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    # lifespan off: the session TestClient already owns MCP's once-per-process session manager; the UI never uses /mcp
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(10)


@pytest.fixture(scope="module")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.chromium.launch()
    yield b
    b.close()


def _open(browser, base_url, **ctx):
    c = browser.new_context(base_url=base_url, **({"viewport": {"width": 1280, "height": 900}} | ctx))
    pg = c.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: m.type == "error" and not any(i in m.text + str(m.location) for i in IGNORED_CONSOLE)
          and errors.append(f"console: {m.text} @ {m.location.get('url')}"))
    return c, pg, errors


@pytest.fixture
def page(browser, base_url):
    c, pg, errors = _open(browser, base_url)
    pg.expected_errors = []  # substrings a test provokes on purpose (the browser logs every 4xx it receives)
    yield pg
    c.close()
    errors = [e for e in errors if not any(x in e for x in pg.expected_errors)]
    assert errors == [], errors


def _run(runs, rid, events, **files):
    d = runs / rid
    d.mkdir()
    (d / "trace.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    for name, text in files.items():
        (d / name.replace("_", ".")).write_text(text)


START = {"type": "agent_start", "policy": "scripted", "node": "n1", "parent": None, "agent": "director",
         "model": "claude-opus-5-5", "playbook_version": 1, "task": "Plan 100 homes"}


def test_every_tab_renders(page):
    page.goto("/")
    for t in TABS:
        page.click(f"nav button[data-t={t}]")
        expect(page.locator(f"section#{t}")).to_have_class("on")
    page.click("nav button[data-t=overview]")
    expect(page.locator("#overview")).to_contain_text("Townhome capacity found")
    page.wait_for_timeout(1500)  # let the land map and charts finish async work, so late errors are caught


def test_family_designer_validates_then_designs(page):
    page.goto("/")
    page.click("nav button[data-t=families]")
    page.fill("#f_income", "-5")
    page.click("#famGo")
    expect(page.locator("#famStatus")).to_contain_text("Household income")
    expect(page.locator("#famStatus")).to_have_attribute("role", "alert")
    expect(page.locator("#f_income")).to_have_attribute("aria-invalid", "true")
    page.fill("#f_income", "92000")
    page.click("#famGo")
    expect(page.locator("#famOut .tile").first).to_be_visible(timeout=60_000)
    expect(page.locator("#famOut")).to_contain_text("P(keeps home 10 yrs)")
    expect(page.locator("#famStatus")).to_have_text("")


def test_family_designer_explains_a_busy_server(page):
    page.goto("/")
    page.click("nav button[data-t=families]")
    page.expected_errors.append("status of 429")
    page.route("**/api/optimize", lambda r: r.fulfill(status=429, headers={"Retry-After": "3", "Content-Type": "application/json"},
                                                       body='{"detail": "busy"}'))
    page.click("#famGo")
    expect(page.locator("#famStatus")).to_contain_text("Wait 3 seconds")
    expect(page.locator("#famGo")).to_be_enabled()


def test_mission_refusal_is_explained(page):
    page.goto("/")
    page.click("nav button[data-t=agents]")
    page.expected_errors.append("status of 401")
    page.route("**/api/mission", lambda r: r.fulfill(status=401, headers={"Content-Type": "application/json"}, body="{}"))
    page.click("#launch")
    expect(page.locator("#missionStatus")).to_contain_text("access token")


def test_scripted_mission_runs_end_to_end_from_the_ui(page):
    page.goto("/")
    page.click("nav button[data-t=agents]")
    page.select_option("#policySel", "scripted")
    page.click("#launch")
    expect(page.locator("#runTable")).to_contain_text("1.00", timeout=120_000)
    expect(page.locator("#grade")).to_contain_text("Grade 1.00")
    expect(page.locator("#trace .node").first).to_be_visible()
    expect(page.locator("#report")).not_to_contain_text("The brief appears")


def test_failed_run_says_failed_and_stops_polling(page, isolated_artifacts):
    _run(isolated_artifacts / "runs", "20261031_000000_dead", [START], error_json=json.dumps({"error": "RuntimeError: boom"}))
    polls = []
    page.on("request", lambda r: r.url.endswith("/api/runs") and polls.append(r.url))
    page.goto("/")
    page.click("nav button[data-t=agents]")
    expect(page.locator("#runTable")).to_contain_text("failed")
    page.click("#runTable tr[data-id]")
    expect(page.locator("#report")).to_contain_text("This mission failed: RuntimeError: boom")
    n = len(polls)
    page.wait_for_timeout(4500)  # the old UI re-polled every 2 s forever
    assert len(polls) == n


def test_agent_brief_cannot_run_script(page, isolated_artifacts):
    evil = ('# Brief\n<img src=x onerror="window.__xss=1">\n<script>window.__xss=2</script>\n'
            '[click me](javascript:window.__xss=3) and [ok](https://www.habitatoc.org)\n')
    _run(isolated_artifacts / "runs", "20261031_000000_beef", [START], report_md=evil,
         grade_json=json.dumps({"score": 1.0, "checks": {"x": True}}))
    page.goto("/")
    page.click("nav button[data-t=agents]")
    page.click("#runTable tr[data-id]")
    expect(page.locator("#report")).to_contain_text("Brief")
    page.click("#report >> text=click me", no_wait_after=True, timeout=2000) if page.locator("#report >> text=click me").count() else None
    assert page.evaluate("window.__xss") is None
    assert page.locator("#report img, #report script, #report a[href^='javascript']").count() == 0
    assert page.locator("#report a[href='https://www.habitatoc.org']").count() == 1


def test_demo_loads_live_with_the_reference_agent_rail(page):
    page.goto("/demo")
    expect(page.locator("#loading")).to_have_count(0, timeout=60_000)
    expect(page.locator("#railsub")).to_contain_text("Replaying run")
    expect(page.locator("#go")).to_be_visible()


def test_demo_without_webgl_plays_the_recording(pw, base_url):
    b = pw.chromium.launch(args=["--disable-webgl", "--disable-webgl2", "--disable-3d-apis"])
    c, pg, errors = _open(b, base_url)
    with pg.expect_response(lambda r: r.url.endswith(".mp4"), timeout=15_000) as resp:
        pg.goto("/demo")
    assert resp.value.status in (200, 206)
    expect(pg.locator("#loading")).to_contain_text("can't run in this browser")
    expect(pg.locator("#loading video")).to_be_visible()
    c.close()
    b.close()
    assert errors == [], errors


@pytest.mark.parametrize("tab", TABS)
def test_phone_width_has_no_sideways_scroll(browser, base_url, tab):
    c, pg, errors = _open(browser, base_url, viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    pg.goto("/")
    pg.click(f"nav button[data-t={tab}]")
    pg.wait_for_timeout(800)
    overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    c.close()
    assert overflow <= 0, f"{tab} scrolls sideways by {overflow}px at 375px"
    assert errors == [], errors


AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]


def _axe(pg):
    from pathlib import Path

    import axe_playwright_python
    pg.add_script_tag(path=str(Path(axe_playwright_python.__file__).parent / "axe.min.js"))
    res = pg.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']})", AXE_TAGS)
    # only what a user can see: hidden tabs are audited when they are shown
    return [f"{v['id']} ({v['impact']}): {n['target'][0]} | {n['failureSummary'].splitlines()[-1].strip()}"
            for v in res["violations"] if v["impact"] in ("serious", "critical") for n in v["nodes"]
            if pg.evaluate("t => !!document.querySelector(t)?.checkVisibility()", n["target"][0])]


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_dashboard_meets_wcag_aa(browser, base_url, scheme):
    c, pg, errors = _open(browser, base_url, color_scheme=scheme)
    pg.goto("/")
    found = []
    for tab in TABS:
        pg.click(f"nav button[data-t={tab}]")
        pg.wait_for_timeout(1000)
        if tab == "families":
            pg.click("#famGo")
            pg.wait_for_selector("#famOut .tile", timeout=60_000)
        found += [f"{tab}: {v}" for v in _axe(pg)]
    c.close()
    assert found == [], "\n".join(found)
    assert errors == [], errors


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_demo_meets_wcag_aa(browser, base_url, scheme):
    c, pg, errors = _open(browser, base_url, color_scheme=scheme)
    pg.goto("/demo")
    pg.wait_for_selector("#go", timeout=60_000)
    found = _axe(pg)
    c.close()
    assert found == [], "\n".join(found)
    assert errors == [], errors


def test_run_rows_work_from_the_keyboard(page, isolated_artifacts):
    _run(isolated_artifacts / "runs", "20261031_000000_a001", [START], report_md="# First brief\n",
         grade_json=json.dumps({"score": 1.0, "checks": {}}))
    _run(isolated_artifacts / "runs", "20261031_000001_a002", [START], report_md="# Second brief\n",
         grade_json=json.dumps({"score": 1.0, "checks": {}}))
    page.goto("/")
    page.click("nav button[data-t=agents]")
    expect(page.locator("#report")).to_contain_text("Second brief")  # newest first
    page.locator("#runTable tr[data-id='20261031_000000_a001']").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#report")).to_contain_text("First brief")
