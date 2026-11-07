"""Record the 30-second Keystone demo from the live app: sign-in, then short zoomed shots, captions, a voiceover.

Everything on screen is the running app (the Crossline scenario, signed in as the demo persona). A live camera
(a CSS transform on the app, so text stays sharp) pushes into the part of the screen each shot is about. Each
caption is one short headline plus a small technical line. The session is recorded in real time, every shot's
start and end are marked, and ffmpeg cuts the shots to their slots. Only the agent run (and the typing) is sped
up, and the caption says so. The voiceover is the Mac's built-in voice (`say`), one line per act.

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
ACTS = [  # (start s, length s, voiceover): four lines laid over the shots
    (0.0, 6.5, "Knowing if Habitat can build on a land offer takes years of legal triage. Until now."),
    (6.5, 5.5, "Meet Keystone. A hierarchy of Claude agents and live models works the parcel."),
    (12.0, 9.5, "It tests seven legal paths, flags SB 4 as the fastest fit with what's left to verify, and cuts the timeline from over four years to two point four."),
    (21.5, 8.5, "It models whether families keep their homes and sizes the capital gap. Months of triage, in one session. Keys to one hundred starts here."),
]

OVERLAY = """
(() => {
  const BAND = __BAND__;
  const add = () => {
    const st = document.createElement("style");
    st.textContent = `html, body { overflow: hidden !important; }
      #stage { height: calc(100vh - ${BAND}px) !important; } #toasts { display: none !important; }
      #summary { bottom: ${BAND}px !important; }
      #__band { position: fixed; left: 0; right: 0; bottom: 0; height: ${BAND}px; z-index: 2147483646; background: #000;
        display: grid; place-content: center; gap: 4px; padding: 0 60px; border-top: 2px solid #2ee6be; text-align: center; }
      #__band .m { font: 800 30px/1.1 Sora, system-ui, sans-serif; color: #fff; letter-spacing: -.01em; }
      #__band .m b { color: #2ee6be; font-weight: 800; }
      #__band .t { font: 500 15px/1.2 "JetBrains Mono", ui-monospace, monospace; color: #8aa7a0; letter-spacing: .02em; }
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
    window.__caption = (main, tech) => { band.innerHTML = `<div class="m">${main}</div><div class="t">${tech || ""}</div>`; };
    // the camera: scale and move a full-screen root (#stage, #login or #summary) so `target` fills the frame.
    // target: a selector, a list of selectors (their union), or [x, y, w, h] in the #viz viewBox (1600 x 760).
    window.__cam = (rootSel, target, opts = {}) => {
      const root = document.querySelector(rootSel), pad = opts.pad ?? .05, dur = opts.dur ?? 600, max = opts.max ?? 2.4;
      const prev = root.style.transform;
      root.style.transition = "none"; root.style.transformOrigin = "0 0"; root.style.transform = "none";
      let r = null;
      if (Array.isArray(target) && typeof target[0] === "number") {
        const v = document.querySelector("#viz").getBoundingClientRect(), s = Math.min(v.width / 1600, v.height / 760);
        const ox = v.x + (v.width - 1600 * s) / 2, oy = v.y + (v.height - 760 * s) / 2;
        r = {x: ox + target[0] * s, y: oy + target[1] * s, width: target[2] * s, height: target[3] * s};
      } else if (target) {
        const rs = [].concat(target).map(sel => document.querySelector(sel).getBoundingClientRect());
        const x0 = Math.min(...rs.map(q => q.x)), y0 = Math.min(...rs.map(q => q.y));
        r = {x: x0, y: y0, width: Math.max(...rs.map(q => q.x + q.width)) - x0, height: Math.max(...rs.map(q => q.y + q.height)) - y0};
      }
      root.style.transform = prev; root.getBoundingClientRect();
      root.style.transition = `transform ${dur}ms cubic-bezier(.22,.7,.2,1)`;
      if (!r) { root.style.transform = "translate(0px, 0px) scale(1)"; return; }
      const W = innerWidth, H = innerHeight - BAND;
      if (opts.k) {  // a fixed zoom anchored at the target's top-left (for full-width pages like the summary)
        root.style.transform = `translate(${40 - opts.k * r.x}px, ${24 - opts.k * r.y}px) scale(${opts.k})`;
        return;
      }
      const k = Math.max(1, Math.min(max, W / (r.width * (1 + 2 * pad)), H / (r.height * (1 + 2 * pad))));
      root.style.transform = `translate(${W / 2 - k * (r.x + r.width / 2)}px, ${H / 2 - k * (r.y + r.height / 2)}px) scale(${k})`;
    };
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
        mouse = {"x": 900, "y": 600}
        cuts = []

        def now():
            return time.monotonic() - t_open

        def click(sel, steps=12):
            box = page.locator(sel).first.bounding_box()
            assert box, sel
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.mouse.move(mouse["x"], mouse["y"])
            page.mouse.move(x, y, steps=steps)
            mouse.update(x=x, y=y)
            page.mouse.down(); page.wait_for_timeout(40); page.mouse.up()

        def park():  # the cursor leaves the frame for shots without interaction
            page.mouse.move(1530, 760)
            mouse.update(x=1530, y=760)

        def js(code, arg=None):
            return page.evaluate(code, arg)

        def cam(root, target=None, **opts):
            js("([r, t, o]) => window.__cam(r, t, o)", [root, target, opts])

        def caption(main, tech):
            js("([m, t]) => window.__caption(m, t)", [main, tech])

        def shot(slot, setup, real=None):
            a = now()
            setup()
            page.wait_for_timeout(max(0, (a + (real or slot) - now()) * 1000))
            cuts.append((a, now(), slot))

        page.goto(url + "/scenario")
        page.wait_for_selector("#password", state="visible")
        page.wait_for_timeout(1200)  # fonts settle off camera

        # 1. sign in (3.0 s)
        a = now()
        caption("Maria, Habitat OC real estate, <b>signs in</b>", "scrypt-hashed accounts · a private copy of the scenario per session")
        cam("#login", "#loginForm", max=1.6, dur=500)
        page.wait_for_timeout(450)
        click("#password", steps=8)
        page.keyboard.type("keys-to-100", delay=70)
        page.wait_for_timeout(max(0, (a + 2.3 - now()) * 1000))  # real-time pace: the click lands at 2.3 s
        click("#loginForm button[type=submit]", steps=6)
        page.wait_for_selector("#stage:not([hidden])")
        cuts.append((a, now(), 3.0))

        # 2. the CNN scan (3.5 s)
        park()
        shot(3.5, lambda: (js("showBeat(0)"), cam("#stage", [50, 15, 1200, 730]),
                           caption("A church offers its lot: <b>45,450 m² of parking</b> found",
                                   "U-Net CNN · NAIP 0.6 m RGB + near-infrared · OpenStreetMap weak labels")))

        # 3. ask the agents: typing (1.0 s), then the run (4.5 s, sped up)
        js("showBeat(1, {animate: false}); document.querySelector('#askQ').scrollIntoView({block: 'center'})")
        cam("#stage", ["#askQ", "#runAgents"], max=2.3, pad=.12, dur=0)  # framed before the cut, so the shot opens steady
        caption("She asks the <b>Claude agents</b>", "Opus 5.5 director · Sonnet 5.5 workers · tools over MCP")
        page.wait_for_timeout(150)
        a = now()
        click("#askQ", steps=6)
        page.keyboard.type("Evaluate SB 4 and SB 35 compliance for this parcel.", delay=8)
        click("#runAgents", steps=5)
        b = now()
        cuts.append((a, b, 1.0))
        page.wait_for_selector("#agentTree:not([hidden])")
        park()
        cam("#stage", ["#agentTree .tq", "#treeSvg"], pad=.04, dur=500)
        caption("Agents fan out <b>in parallel</b> (sped up)", "least-privilege tools · OS sandbox for agent code · code graders check the brief")
        page.wait_for_function("/graded|failed/.test(document.querySelector('#treeFoot')?.textContent || '')", timeout=120_000)
        page.wait_for_timeout(1000)
        cuts.append((b, now(), 4.5))

        # 4. the legal paths (2.5 s), then SB 4's open checks (2.0 s)
        page.keyboard.press("Escape")
        shot(2.5, lambda: (js("showBeat(1)"), cam("#stage", [40, 20, 1530, 720], dur=450),
                           caption("<b>7 legal paths</b> tested against this parcel",
                                   "Gov Code 65913.16 · 65913.4 · 66499.41 · 66314 (formerly 65852.2) · checked 2026-11-07")))
        shot(2.0, lambda: (js("document.querySelector('#panel .checks').scrollIntoView({block: 'center'})"),
                           cam("#stage", "#panel .checks", max=2.3, pad=.08, dur=450),
                           caption("SB 4 fits, with <b>3 facts still to verify</b>",
                                   "missing facts are never assumed: an OpenStreetMap tag is not a title record")))

        # 5. the clock (5.0 s)
        shot(5.0, lambda: (js("showBeat(2)"), cam("#stage", [90, 55, 1430, 625], dur=450),
                           caption("Critical path: <b>4.2 years → 2.4</b>",
                                   "a dependency graph · every duration sourced or labelled an estimate")))

        # 6. capital (2.5 s) and 7. families (2.5 s)
        shot(2.5, lambda: (js("showBeat(4)"), cam("#stage", [100, 70, 1300, 450], dur=400),
                           caption("<b>$5.4M gap</b>, summed home by home",
                                   "mortgage notes at present value · standard 0% loans need $6.8M")))
        shot(2.5, lambda: (js("showBeat(3)"), cam("#stage", [110, 115, 1440, 420], dur=400),
                           caption("<b>22 of 30 families</b> expected to keep their homes",
                                   "10-year Monte Carlo · the same shocks under three loan designs")))

        # 8. the one-page summary (3.5 s)
        shot(3.5, lambda: (cam("#stage", None, dur=0), js("summary()"),
                           cam("#summary", "#summary .wordmark", k=1.1, dur=700),
                           caption("<b>KEYSTONE</b> · one page for the board",
                                   "every number links to its formula, inputs and source")))

        video = page.video
        assert video
        t_close = now()
        ctx.close()  # the video file is finalised when its context closes
        raw = Path(video.path())
        browser.close()
    # the video starts a moment after the page opens; measure that lag from the file and shift the cuts by it
    lag = max(0.0, t_close - duration(raw))
    return raw, [(a - lag, b - lag, slot) for a, b, slot in cuts]


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def voiceover(workdir):
    """One clip per act, sped up only as much as needed to fit its slot, laid on the act's start."""
    inputs, filters = [], []
    for i, (start, slot, line) in enumerate(ACTS):
        clip = workdir / f"vo{i}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", "205", "-o", str(clip), line], check=True)
        dur = duration(clip)
        tempo = min(max(dur / (slot - 0.3), 1.0), 1.4)
        inputs += ["-i", str(clip)]
        filters.append(f"[{i + 1}:a]atempo={tempo:.3f},adelay={int((start + 0.1) * 1000)}:all=1[v{i}]")
        print(f"voiceover {i}: {dur:.2f}s in a {slot}s slot, tempo {tempo:.2f}")
    mix = "".join(f"[v{i}]" for i in range(len(ACTS))) + f"amix=inputs={len(ACTS)}:normalize=0[vo]"
    return inputs, filters + [mix]


def cut(raw, cuts, workdir, out):
    if duration(raw) < cuts[-1][1] - 0.2:  # a stalled screencast drops the tail; never ship a short cut
        raise SystemExit(f"raw recording is {duration(raw):.1f}s but the cuts end at {cuts[-1][1]:.1f}s: re-run")
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
    print("cuts:", [(round(x, 2), round(y, 2), s) for x, y, s in cuts], "total", sum(c[2] for c in cuts))
    cut(raw, cuts, work, a.out)
    shutil.rmtree(work, ignore_errors=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
