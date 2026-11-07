"""Record the mission-control demo to MP4, frame-exact, regardless of how fast the machine renders.

The page's clock (performance.now, Date.now, requestAnimationFrame, setTimeout) is replaced by a virtual clock that
advances exactly 1/fps per frame; each frame waits for map tiles before it is captured and piped into ffmpeg.

  .venv/bin/python scripts/record_demo.py --out hackathon-info/keystone_demo.mp4            # server must be running on :8000
  .venv/bin/python scripts/record_demo.py --seconds 5 --out /tmp/test.mp4         # quick test
"""
import argparse
import shutil
import subprocess
import time

from playwright.sync_api import sync_playwright

VIRTUAL_CLOCK = """
(() => {
  let now = 0;
  const epoch = Date.now();
  const raf = new Map(); let rafId = 0;
  const timers = new Map(); let timerId = 0;
  performance.now = () => now;
  const RealDate = Date;
  Date.now = () => epoch + now;
  window.requestAnimationFrame = cb => { raf.set(++rafId, cb); return rafId; };
  window.cancelAnimationFrame = id => raf.delete(id);
  window.setTimeout = (fn, ms = 0, ...args) => { const id = ++timerId; timers.set(id, { at: now + (ms || 0), fn, args }); return id; };
  window.clearTimeout = id => timers.delete(id);
  window.__virtualNow = () => now;
  window.__advance = (dt) => {
    const target = now + dt;
    // fire due timers in time order (timers may schedule more timers)
    for (let guard = 0; guard < 10000; guard++) {
      let next = null;
      for (const [id, t] of timers) if (t.at <= target && (!next || t.at < next[1].at)) next = [id, t];
      if (!next) break;
      timers.delete(next[0]); now = Math.max(now, next[1].at);
      try { typeof next[1].fn === "function" ? next[1].fn(...next[1].args) : eval(next[1].fn); } catch (e) { console.error(e); }
    }
    now = target;
    const cbs = [...raf.values()]; raf.clear();
    for (const cb of cbs) { try { cb(now); } catch (e) { console.error(e); } }
  };
  // a second frame pass lets libraries that render on the frame after a state change catch up
  window.__flush = () => { const cbs = [...raf.values()]; raf.clear(); for (const cb of cbs) { try { cb(now); } catch (e) { console.error(e); } } };
})();
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/demo")
    ap.add_argument("--out", default="hackathon-info/keystone_demo.mp4")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--seconds", type=float, default=None, help="stop early (default: whole demo)")
    ap.add_argument("--start-step", type=int, default=0)
    a = ap.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    enc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(a.fps), "-c:v", "mjpeg",
                            "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "18",
                            "-movflags", "+faststart", a.out], stdin=subprocess.PIPE)
    dt = 1000 / a.fps
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=metal", "--enable-gpu-rasterization", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": a.width, "height": a.height}, device_scale_factor=1)
        page.on("console", lambda m: m.type == "error" and print("console:", m.text[:200]))
        page.add_init_script(VIRTUAL_CLOCK)
        page.goto(a.url)
        # wait_for_function polls with requestAnimationFrame, which the virtual clock owns, so poll from here instead
        ready = "typeof STEPS !== 'undefined' && !!STEPS && typeof map !== 'undefined' && map.loaded() && map.areTilesLoaded()"
        for _ in range(1200):
            page.evaluate(f"typeof __advance === 'function' && __advance({dt})")
            if page.evaluate(ready):
                break
            time.sleep(0.1)
        else:
            raise SystemExit("demo page never became ready (is the server on :8000 running?)")
        page.add_style_tag(content="#controls { display: none !important; }")  # no playback buttons in the video
        page.evaluate(f"document.querySelector('#start')?.remove(); {'goto(0)' if a.start_step == 0 else f'jumpTo({a.start_step})'}; play();")
        total = page.evaluate(f"STEPS.slice({a.start_step}).reduce((s, x) => s + x.dur, 0)") + 1500
        if a.seconds:
            total = min(total, a.seconds * 1000)
        n = int(total / dt)
        t0 = time.time()
        for i in range(n):
            page.evaluate(f"__advance({dt})")
            for _ in range(30):  # wait (real time) for tiles the new camera position needs
                if page.evaluate("map.areTilesLoaded()"):
                    break
                time.sleep(0.05)
                page.evaluate("__flush()")
            page.evaluate("__flush()")
            enc.stdin.write(page.screenshot(type="jpeg", quality=92, timeout=120_000))  # generous: a busy machine is slow, not wrong
            if i % (a.fps * 5) == 0:
                el = time.time() - t0
                print(f"frame {i}/{n} · demo t={i * dt / 1000:.1f}s · step {page.evaluate('si')} · {el:.0f}s elapsed, ~{el / max(i, 1) * (n - i):.0f}s left", flush=True)
        browser.close()
    enc.stdin.close()
    enc.wait()
    print("wrote", a.out)


if __name__ == "__main__":
    main()
