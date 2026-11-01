# Regression: ISSUE-003 — demo hung on "Loading…" forever when WebGL was unavailable
# Found by /qa on 2026-11-01
# Report: .gstack/qa-reports/run-20261101T040942Z/qa-report-localhost-2026-11-01.md
from fastapi.testclient import TestClient

from keystone.app import server


def test_demo_has_a_working_no_webgl_fallback():
    c = TestClient(server.app)  # no lifespan needed for static routes
    page = c.get("/demo")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    assert "webglAvailable()" in page.text and "fallback(" in page.text
    video = c.get("/static/demo/keystone_demo_720p.mp4", headers={"Range": "bytes=0-15"})
    assert video.status_code in (200, 206) and video.headers["content-type"] == "video/mp4"
