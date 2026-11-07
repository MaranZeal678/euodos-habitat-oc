"""Record the hard 30-second Euodos film (/scenario?film) to MP4, frame-exact.

The page's clock is virtual (the same clock scripts/record_demo.py uses), so every frame is rendered at exactly
1/fps of film time however slow the machine is.

  .venv/bin/python scripts/record_film.py --url http://localhost:8010/scenario?film --out docs/euodos_30s.mp4
  .venv/bin/python scripts/record_film.py --stills 1.5,6,13,20,25,28 --out /tmp/stills   # check shots as PNGs
"""
import argparse
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from record_demo import VIRTUAL_CLOCK

FILM_SECONDS = 30.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8010/scenario?film")
    ap.add_argument("--out", default="docs/euodos_30s.mp4")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--stills", default="", help="comma-separated film times (s) to save as PNG instead of a video")
    a = ap.parse_args()
    dt = 1000 / a.fps
    stills = sorted(float(x) for x in a.stills.split(",") if x)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": a.width, "height": a.height}, device_scale_factor=1)
        page.on("console", lambda m: m.type == "error" and print("console:", m.text[:200]))
        page.on("pageerror", lambda e: print("pageerror:", str(e)[:200]))
        page.add_init_script(VIRTUAL_CLOCK)
        page.goto(a.url)
        for _ in range(600):  # fetches and fonts resolve on real time; the page clock only moves when we advance it
            if page.evaluate("window.FILM_READY === true"):
                break
            time.sleep(0.05)
        else:
            raise SystemExit("film never became ready (is the server running?)")
        page.evaluate("window.startFilm()")
        page.evaluate("__flush()")
        if stills:
            out = Path(a.out)
            out.mkdir(parents=True, exist_ok=True)
            t = 0.0
            for s in stills:
                while t + dt / 1000 <= s:
                    page.evaluate(f"__advance({dt})")
                    t += dt / 1000
                page.evaluate("__flush()")
                page.screenshot(path=str(out / f"film_{s:05.1f}s.png"))
                print("still", s)
            browser.close()
            return
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        enc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(a.fps), "-c:v", "mjpeg",
                                "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "18",
                                "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
        assert enc.stdin
        frames = int(FILM_SECONDS * a.fps)
        for i in range(frames):
            page.evaluate("__flush()")
            enc.stdin.write(page.screenshot(type="jpeg", quality=92, timeout=120_000))
            page.evaluate(f"__advance({dt})")
            if i % (a.fps * 5) == 0:
                print(f"frame {i}/{frames}", flush=True)
        browser.close()
    enc.stdin.close()
    enc.wait()
    print("wrote", a.out)


if __name__ == "__main__":
    main()
