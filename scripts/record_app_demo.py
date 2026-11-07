"""Record the 30-second Keystone demo from the live app: four scenes, bottom captions, a voiceover.

Everything on screen is the running app (the Crossline scenario, signed in as the demo persona). The session is
recorded in real time; each scene's start and end are marked, then ffmpeg cuts the scenes to their slots
(5 + 7 + 10 + 8 s). Only the agent run is sped up, and its caption says so. The voiceover is the Mac's built-in
voice (`say`), one line per scene, laid on the scene's start.

  KEYSTONE_DEMO_LOGIN=1 .venv/bin/uvicorn keystone.app.server:app --port 8010
  .venv/bin/python scripts/record_app_demo.py --url http://localhost:8010 --out docs/keystone_30s.mp4
"""
import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BAND = 96  # CSS px of caption band under the app (120 px in the 1.25x-scaled video)
VOICE = "Reed (English (US))"
SCENES = [  # (slot start s, slot length s, voiceover)
    (0.0, 5.0, "Knowing if Habitat can build on a land offer takes years of legal triage. Until now."),
    (5.0, 7.0, "Meet Keystone. A hierarchy of Claude agents and live models tests the parcel against seven legal paths."),
    (12.0, 10.0, "In seconds, Keystone flags SB 4 as the fastest fit, maps the critical path, and cuts the timeline from over four years to two point four."),
    (22.0, 8.0, "It models whether families keep their homes and sizes the capital gap. Months of triage, in one session. Keys to one hundred starts here."),
]

OVERLAY = """
(() => {
  const add = () => {
    const st = document.createElement("style");
    st.textContent = `#stage { height: calc(100vh - __BAND__px) !important; } #toasts { display: none !important; }
      #__band { position: fixed; left: 0; right: 0; bottom: 0; height: __BAND__px; z-index: 2147483646; background: #000;
        display: flex; align-items: center; justify-content: center; padding: 0 60px; border-top: 2px solid #2ee6be;
        font: 800 31px/1.15 Sora, system-ui, sans-serif; color: #fff; text-align: center; letter-spacing: -.01em; }
      #__band b { color: #2ee6be; font-weight: 800; }
      #__cursor { position: fixed; left: 0; top: 0; width: 28px; height: 28px; z-index: 2147483647; pointer-events: none;
        transform: translate(-4px, -2px); background: no-repeat center/contain url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M3 2l7 19 2.6-7.4L20 11z' fill='white' stroke='black' stroke-width='1.4'/></svg>"); }`;
    document.head.appendChild(st);
    const band = document.createElement("div"); band.id = "__band"; document.body.appendChild(band);
    const c = document.createElement("div"); c.id = "__cursor"; document.body.appendChild(c);
    addEventListener("mousemove", e => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
    addEventListener("mousedown", e => {
      const r = document.createElement("div");
      r.style.cssText = `position:fixed;left:${e.clientX - 18}px;top:${e.clientY - 18}px;width:36px;height:36px;border-radius:50%;` +
        "border:3px solid #2ee6be;z-index:2147483646;pointer-events:none;transition:transform .45s,opacity .45s";
      document.body.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = "scale(1.9)"; r.style.opacity = "0"; });
      setTimeout(() => r.remove(), 500);
    }, true);
    window.__caption = html => { band.innerHTML = `<span>${html}</span>`; };  // one inline box keeps the spaces around <b>
  };
  document.readyState === "loading" ? addEventListener("DOMContentLoaded", add) : add();
})();
""".replace("__BAND__", str(BAND))


def record(url, workdir):
    """Drive the app in real time. Returns the raw video path and the cut list [(start, end, slot seconds)]."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # a 1536x864 layout drawn at 1.25x: the 1080p video reads like the Mac app on a laptop screen
        ctx = browser.new_context(viewport={"width": 1536, "height": 864}, device_scale_factor=1.25, record_video_dir=str(workdir),
                                  record_video_size={"width": 1920, "height": 1080})
        t_open = time.monotonic()  # Playwright starts the video when the page opens
        page = ctx.new_page()
        page.add_init_script(OVERLAY)
        mouse = {"x": 768, "y": 560}

        def now():
            return time.monotonic() - t_open

        def move_to(sel, steps=14):
            loc = page.locator(sel).first
            loc.scroll_into_view_if_needed()
            box = loc.bounding_box()
            assert box, sel
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.mouse.move(mouse["x"], mouse["y"])
            page.mouse.move(x, y, steps=steps)
            mouse.update(x=x, y=y)

        def click(sel, steps=14):
            move_to(sel, steps)
            page.mouse.down(); page.wait_for_timeout(50); page.mouse.up()

        def caption(html):
            page.evaluate("t => window.__caption(t)", html)

        def hold(t_end):
            page.wait_for_timeout(max(0, (t_end - now()) * 1000))

        # off camera: sign in as the demo persona
        page.goto(url + "/scenario")
        page.wait_for_selector("#password", state="visible")
        page.fill("#password", "keys-to-100")
        page.click("#loginForm button[type=submit]")
        page.wait_for_selector("#stage:not([hidden])")
        page.wait_for_timeout(1500)
        cuts = []

        # 1. the hook (5 s): the CNN scans the church parking lot
        caption("A church offers its parking lot. <b>A U-Net CNN scans 45,450 m²</b> from aerial imagery.")
        a = now()
        click("#beats button[data-i='0']", steps=2)
        hold(a + 5.0)
        cuts.append((a, now(), 5.0))

        # 2. ask the agents (7 s): type the prompt (real time), then the run (sped up)
        caption("Ask the <b>Claude agents</b>")
        a = now()
        click("#beats button[data-i='1']", steps=10)
        click("#askQ", steps=10)
        page.keyboard.type("Evaluate SB 4 and SB 35 compliance for this parcel.", delay=12)
        click("#runAgents", steps=6)
        b = now()
        cuts.append((a, b, 1.8))
        caption("Director (Opus 5.5) → Land, Family, Capital leads → workers, <b>in parallel</b> · run sped up")
        page.wait_for_function("/graded|failed/.test(document.querySelector('#treeFoot')?.textContent || '')", timeout=120_000)
        page.wait_for_timeout(900)
        cuts.append((b, now(), 5.2))

        # 3. the reveal and the clock (10 s)
        page.keyboard.press("Escape")
        caption("<b>7 legal paths tested:</b> SB 4 is the fastest fit, 3 checks to verify, 4 ruled out")
        a = now()
        click("#beats button[data-i='1']", steps=4)
        hold(a + 4.6)
        caption("Critical path: <b>4.2 years → 2.4 years</b> from offer to move-in")
        click("#beats button[data-i='2']", steps=12)
        hold(a + 10.0)
        cuts.append((a, now(), 10.0))

        # 4. capital, families, the one-page summary (8 s)
        caption("Capital stack, home by home: <b>$5.4M gap</b> (standard loans: $6.8M)")
        a = now()
        click("#beats button[data-i='4']", steps=10)
        hold(a + 2.7)
        caption("<b>22 of 30 families</b> expected to keep their homes for 10 years")
        click("#beats button[data-i='3']", steps=10)
        hold(a + 5.3)
        caption("<b>KEYSTONE</b> · one-page summary for the board")
        click("#summaryBtn", steps=10)
        hold(a + 8.0)
        cuts.append((a, now(), 8.0))

        video = page.video
        assert video
        ctx.close()  # the video file is finalised when its context closes
        raw = Path(video.path())
        browser.close()
    return raw, cuts


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def voiceover(workdir):
    """One clip per scene, sped up only as much as needed to fit its slot, laid on the scene's start."""
    inputs, filters = [], []
    for i, (start, slot, line) in enumerate(SCENES):
        clip = workdir / f"vo{i}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", "205", "-o", str(clip), line], check=True)
        dur = duration(clip)
        tempo = min(max(dur / (slot - 0.3), 1.0), 1.4)
        inputs += ["-i", str(clip)]
        filters.append(f"[{i + 1}:a]atempo={tempo:.3f},adelay={int((start + 0.1) * 1000)}:all=1[v{i}]")
        print(f"voiceover {i}: {dur:.2f}s in a {slot}s slot, tempo {tempo:.2f}")
    mix = "".join(f"[v{i}]" for i in range(len(SCENES))) + f"amix=inputs={len(SCENES)}:normalize=0[vo]"
    return inputs, filters + [mix]


def cut(raw, cuts, workdir, out):
    vf = [f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)*{slot / (b - a):.5f},fps=30[s{i}]"
          for i, (a, b, slot) in enumerate(cuts)]
    vf.append("".join(f"[s{i}]" for i in range(len(cuts))) + f"concat=n={len(cuts)}:v=1:a=0,tpad=stop_mode=clone:stop_duration=1[v]")
    a_inputs, af = voiceover(workdir)
    subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), *a_inputs,
                    "-filter_complex", ";".join(vf + af), "-map", "[v]", "-map", "[vo]", "-t", "30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8010")
    ap.add_argument("--out", default="docs/keystone_30s.mp4")
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="keystone_rec_"))
    raw, cuts = record(a.url, work)
    print("cuts:", [(round(x, 2), round(y, 2), s) for x, y, s in cuts])
    cut(raw, cuts, work, a.out)
    shutil.rmtree(work, ignore_errors=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
