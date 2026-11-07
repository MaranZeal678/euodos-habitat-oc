"""Record the 30-second app demo: a real user signing in and running the Crossline scenario, in real time.

Everything on screen is the live app: typing, clicks, server recomputes. A visible cursor and short step captions
are drawn on top (the browser's own cursor never appears in a recording). The result is trimmed to exactly 30 s.

  # server with the demo login: KEYSTONE_DEMO_LOGIN=1 uvicorn keystone.app.server:app --port 8010
  .venv/bin/python scripts/record_app_demo.py --url http://localhost:8010 --out docs/keystone_30s.mp4
"""
import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OVERLAY = """
(() => {
  const add = () => {
    const c = document.createElement("div"); c.id = "__cursor";
    c.style.cssText = "position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;" +
      "transform:translate(-4px,-2px);background:no-repeat center/contain url(\\"data:image/svg+xml;utf8," +
      "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M3 2l7 19 2.6-7.4L20 11z' fill='white' stroke='black' stroke-width='1.4'/></svg>\\")";
    document.body.appendChild(c);
    const cap = document.createElement("div"); cap.id = "__caption";
    cap.style.cssText = "position:fixed;left:50%;top:18px;transform:translateX(-50%);z-index:2147483646;pointer-events:none;" +
      "font:600 26px Sora,system-ui,sans-serif;color:#061012;background:#2ee6be;padding:10px 22px;border-radius:999px;" +
      "box-shadow:0 8px 30px rgba(0,0,0,.45);opacity:0;transition:opacity .25s";
    document.body.appendChild(cap);
    addEventListener("mousemove", e => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
    addEventListener("mousedown", e => {
      const r = document.createElement("div");
      r.style.cssText = `position:fixed;left:${e.clientX - 18}px;top:${e.clientY - 18}px;width:36px;height:36px;border-radius:50%;` +
        "border:3px solid #2ee6be;z-index:2147483646;pointer-events:none;transition:transform .45s,opacity .45s";
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = "scale(1.9)"; r.style.opacity = "0"; });
      setTimeout(() => r.remove(), 500);
    }, true);
    window.__caption = text => { cap.textContent = text; cap.style.opacity = text ? 1 : 0; };
  };
  document.readyState === "loading" ? addEventListener("DOMContentLoaded", add) : add();
})();
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8010")
    ap.add_argument("--out", default="docs/keystone_30s.mp4")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="keystone_rec_"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(tmp),
                                  record_video_size={"width": 1920, "height": 1080})
        t_open = time.monotonic()  # Playwright starts the video when the page opens
        page = ctx.new_page()
        page.add_init_script(OVERLAY)
        page.goto(a.url + "/scenario")
        page.wait_for_selector("#password", state="visible")
        page.wait_for_timeout(400)
        t0 = time.monotonic()  # the 30 s cut starts here
        mouse = {"x": 960, "y": 900}

        def move_to(sel, steps=18):
            box = page.locator(sel).first.bounding_box()
            assert box, sel
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.mouse.move(mouse["x"], mouse["y"])
            page.mouse.move(x, y, steps=steps)
            mouse.update(x=x, y=y)

        def click(sel, steps=18):
            move_to(sel, steps)
            page.mouse.down(); page.wait_for_timeout(60); page.mouse.up()

        def caption(text):
            page.evaluate("t => window.__caption(t)", text)

        # 1. the use case: one person, one problem; she signs in to answer it
        caption("Maria runs real estate at Habitat OC. A church just offered its parking lot.")
        click("#email")
        page.fill("#email", "")
        page.keyboard.type("maria@habitat-oc.demo", delay=28)
        caption("Can 30 families move in within two years? She signs in to find out.")
        click("#password", steps=8)
        page.keyboard.type("keys-to-100", delay=40)
        click("#loginForm button[type=submit]", steps=10)
        page.wait_for_selector("#stage:not([hidden])")
        # 2. the offer
        caption("Keystone scans the lot from aerial imagery: room for 30 homes")
        page.wait_for_timeout(2800)
        # 3. the legal path for this address (Lane 2: Clear it)
        caption("Seven legal paths tested: SB 4 by right fits; four are ruled out")
        click("#beats button[data-i='1']", steps=14)
        page.wait_for_timeout(2600)
        # 4. the clock
        caption("Clear it: offer to move-in in 2.4 years, not 4.2")
        click("#beats button[data-i='2']", steps=14)
        page.wait_for_timeout(2900)
        caption("Switch off SB 4 by-right approval: the project slips")
        click("[data-lever=sb4_ministerial]", steps=14)
        page.wait_for_timeout(1500)
        click("[data-lever=sb4_ministerial]", steps=4)
        page.wait_for_timeout(900)
        # 5. families: edit one live
        caption("30 families banks turn away. She edits one family's income: live recompute")
        click("#beats button[data-i='3']", steps=12)
        page.wait_for_timeout(1300)
        click("#hhSel", steps=12)
        page.select_option("#hhSel", "1")
        click("#hhIncome", steps=8)
        page.fill("#hhIncome", "")
        page.keyboard.type("104000", delay=30)
        click("#hhGo", steps=8)
        page.wait_for_function("document.querySelector('#status')?.textContent.includes('updated')", timeout=15_000)
        page.wait_for_timeout(700)
        # 6. who pays
        caption("Who closes the gap, home by home")
        click("#beats button[data-i='4']", steps=12)
        page.wait_for_timeout(2600)
        # 7. ten years
        caption("Ten years later: who still owns their home")
        click("#beats button[data-i='5']", steps=12)
        remaining = 30.0 - (time.monotonic() - t0)
        page.wait_for_timeout(max(remaining, 0) * 1000 + 300)
        video = page.video
        assert video
        ctx.close()  # the video file is finalised when its context closes
        raw = Path(video.path())
        browser.close()
    start = round(t0 - t_open, 3)  # skip the page load; the cut begins at the sign-in screen
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", str(max(start, 0)), "-i", str(raw), "-t", "30", "-r", "30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "20", "-movflags", "+faststart", "-an", a.out],
                   check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
