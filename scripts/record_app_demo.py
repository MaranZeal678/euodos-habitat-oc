"""Record the 30-second Keystone demo from the live app: sign-in, short zoomed shots, a spotlight, subtitles, a voiceover.

Everything on screen is the running app (the Crossline scenario, signed in as the demo persona), recorded at its
native size and scaled to fill 1920x1080. A live camera (a CSS transform, so text stays sharp) pushes into the part
of the screen each shot is about, and a spotlight ring with one short label points at the exact thing being said.
The voiceover is the Mac's built-in voice (`say`); its words appear as subtitles in the bottom band, phrase by
phrase, timed to the audio. Shots are recorded in real time and cut to their slots; only the typing and the agent
run are sped up, and the spotlight label says so.

  KEYSTONE_DEMO_LOGIN=1 .venv/bin/uvicorn keystone.app.server:app --port 8010
  .venv/bin/python scripts/record_app_demo.py --url http://localhost:8010 --out docs/keystone_30s.mp4
"""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

W, H = 1536, 864           # the app's native layout, recorded 1:1
OUT_W, OUT_H = 1920, 1080  # scaled to fill the frame
BAND = 120                 # px of subtitle band under the app (150 px in the output)
VOICE = "Reed (English (US))"
FONT = ("/System/Library/Fonts/Avenir Next.ttc", 0)  # Avenir Next Bold, the app's fallback face for Sora
ACTS = [  # (start s, slot s, spoken line, subtitle phrases with **teal** words): short lines, spoken unhurried
    (0.0, 4.5, "Knowing if Habitat can build takes years. Until now.",
     ["Knowing if Habitat can build", "takes **years**. Until now."]),
    (4.5, 5.0, "Public data only. A CNN reads parking lots from aerial photos.",
     ["**Public data only.**", "A **CNN** reads parking lots from aerial photos."]),
    (9.5, 5.0, "Meet Keystone: Claude agents and live models, working the parcel.",
     ["Meet **Keystone**:", "**Claude agents** and live models, working the parcel."]),
    (14.5, 8.5, "Seven legal paths. SB 4 is the fastest fit, with three facts to verify. Four years becomes two point four.",
     ["**Seven legal paths**.", "**SB 4** is the fastest fit, with three facts to verify.", "Four years becomes **2.4**."]),
    (23.0, 7.0, "Families who keep their homes, and the capital gap, home by home. Keys to one hundred starts here.",
     ["Families who **keep their homes**,", "and the **capital gap**, home by home.", "**Keys to 100** starts here."]),
]

OVERLAY = """
(() => {
  const BAND = __BAND__;
  const add = () => {
    const st = document.createElement("style");
    st.textContent = `html, body { overflow: hidden !important; }
      #stage { height: calc(100vh - ${BAND}px) !important; } #toasts { display: none !important; }
      #summary { bottom: ${BAND}px !important; }
      #__band { position: fixed; left: 0; right: 0; bottom: 0; height: ${BAND}px; z-index: 2147483646; background: #000; border-top: 2px solid #2ee6be; }
      .__ring { position: fixed; z-index: 2147483640; pointer-events: none; border: 3px solid #2ee6be; border-radius: 14px;
        box-shadow: 0 0 0 100vmax rgba(0, 0, 0, .38), 0 0 26px rgba(46, 230, 190, .55); animation: __in .35s ease-out both; }
      .__tag { position: fixed; z-index: 2147483641; pointer-events: none; max-width: 470px; padding: 9px 14px; border-radius: 12px;
        background: #061012; border: 1.5px solid #2ee6be; color: #e9f5f2; font: 700 18px/1.3 Sora, "Avenir Next", system-ui, sans-serif;
        box-shadow: 0 10px 30px rgba(0, 0, 0, .55); animation: __in .35s ease-out .1s both; }
      .__tag b { color: #2ee6be; }
      @keyframes __in { from { opacity: 0; transform: scale(.96); } to { opacity: 1; transform: none; } }
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
    // a selector, a list of selectors (their union), or [x, y, w, h] in the #viz viewBox (1600 x 760), as a screen rect
    const rectOf = target => {
      if (Array.isArray(target) && typeof target[0] === "number") {
        const v = document.querySelector("#viz").getBoundingClientRect(), s = Math.min(v.width / 1600, v.height / 760);
        const ox = v.x + (v.width - 1600 * s) / 2, oy = v.y + (v.height - 760 * s) / 2;
        return {x: ox + target[0] * s, y: oy + target[1] * s, width: target[2] * s, height: target[3] * s};
      }
      const rs = [].concat(target).map(sel => document.querySelector(sel).getBoundingClientRect());
      const x0 = Math.min(...rs.map(q => q.x)), y0 = Math.min(...rs.map(q => q.y));
      return {x: x0, y: y0, width: Math.max(...rs.map(q => q.x + q.width)) - x0, height: Math.max(...rs.map(q => q.y + q.height)) - y0};
    };
    // the camera: scale and move a full-screen root (#stage, #login or #summary) so `target` fills the frame
    window.__cam = (rootSel, target, opts = {}) => {
      const root = document.querySelector(rootSel), pad = opts.pad ?? .05, dur = opts.dur ?? 850, max = opts.max ?? 2.4;
      const prev = root.style.transform;
      root.style.transition = "none"; root.style.transformOrigin = "0 0"; root.style.transform = "none";
      const r = target ? rectOf(target) : null;
      root.style.transform = prev; root.getBoundingClientRect();
      root.style.transition = `transform ${dur}ms cubic-bezier(.22,.7,.2,1)`;
      if (!r) { root.style.transform = "translate(0px, 0px) scale(1)"; return; }
      if (opts.k) {  // a fixed zoom anchored at the target's top-left (for full-width pages like the summary)
        root.style.transform = `translate(${40 - opts.k * r.x}px, ${24 - opts.k * r.y}px) scale(${opts.k})`;
        return;
      }
      const Wv = innerWidth, Hv = innerHeight - BAND;
      const k = Math.max(1, Math.min(max, Wv / (r.width * (1 + 2 * pad)), Hv / (r.height * (1 + 2 * pad))));
      root.style.transform = `translate(${Wv / 2 - k * (r.x + r.width / 2)}px, ${Hv / 2 - k * (r.y + r.height / 2)}px) scale(${k})`;
    };
    // the spotlight: a ring around `target` (measured after the camera settles) and one short label beside it
    window.__spot = (target, label, opts = {}) => {
      document.querySelectorAll(".__ring, .__tag").forEach(e => e.remove());
      clearTimeout(window.__spotT);
      if (!target) return;
      window.__spotT = setTimeout(() => {
        const r = rectOf(target), p = opts.pad ?? 8, Hv = innerHeight - BAND;
        const ring = document.createElement("div"); ring.className = "__ring";
        ring.style.cssText = `left:${r.x - p}px;top:${r.y - p}px;width:${r.width + 2 * p}px;height:${r.height + 2 * p}px`;
        const tag = document.createElement("div"); tag.className = "__tag"; tag.innerHTML = label;
        document.body.append(ring, tag);
        const tw = tag.offsetWidth, th = tag.offsetHeight;
        const above = r.y - p - 12 - th, below = r.y + r.height + p + 12;
        let top = opts.side === "above" && above >= 10 ? above : below;
        if (top + th > Hv - 10) top = above;
        if (top < 10) top = Math.min(Hv - th - 10, r.y + r.height + p - th);
        tag.style.left = `${Math.min(Math.max(14, r.x + r.width / 2 - tw / 2), innerWidth - tw - 14)}px`;
        tag.style.top = `${top}px`;
      }, opts.delay ?? 650);
    };
  };
  document.readyState === "loading" ? addEventListener("DOMContentLoaded", add) : add();
})();
""".replace("__BAND__", str(BAND))


def record(url, workdir):
    """Drive the app in real time. Returns the raw video path and the cut list [(start, end, slot seconds)]."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(workdir),
                                  record_video_size={"width": W, "height": H})
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
            page.mouse.move(W - 6, H - BAND - 6)
            mouse.update(x=W - 6, y=H - BAND - 6)

        def js(code, arg=None):
            return page.evaluate(code, arg)

        def cam(root, target=None, **opts):
            js("([r, t, o]) => window.__cam(r, t, o)", [root, target, opts])

        def spot(target=None, label="", **opts):
            js("([t, l, o]) => window.__spot(t, l, o)", [target, label, opts])

        def shot(slot, setup):
            a = now()
            spot()
            setup()
            page.wait_for_timeout(max(0, (a + slot - now()) * 1000))
            cuts.append((a, now(), slot))

        page.goto(url + "/scenario")
        page.wait_for_selector("#password", state="visible")
        page.wait_for_timeout(1200)  # fonts settle off camera

        # 1. sign in (2.5 s)
        a = now()
        cam("#login", "#loginForm", max=1.6, dur=500)
        spot("#loginForm button[type=submit]", "Demo persona · each session gets its <b>own private copy</b>", delay=500)
        page.wait_for_timeout(450)
        click("#password", steps=8)
        page.keyboard.type("keys-to-100", delay=70)
        page.wait_for_timeout(max(0, (a + 1.9 - now()) * 1000))
        click("#loginForm button[type=submit]", steps=6)
        page.wait_for_selector("#stage:not([hidden])")
        cuts.append((a, now(), 2.5))

        # 2. the CNN scan (3.0 s), the public data behind it (2.0 s) and the CNN's model card (2.0 s)
        park()
        shot(3.0, lambda: (js("showBeat(0)"), cam("#stage", [50, 15, 1200, 730]),
                           spot([715, 125, 370, 110], "A <b>U-Net CNN</b> reads parking from 0.6 m aerial imagery", delay=800)))
        shot(2.0, lambda: (js("document.querySelector('#dataList').scrollIntoView({block: 'center'})"),
                           cam("#stage", ["#dataH", "#dataList"], max=2.2, pad=.06, dur=500),
                           spot("#dataList", "<b>No personal information</b> · every source is free to download", delay=550, pad=6, side="above")))
        shot(2.0, lambda: (js("document.querySelector('#cnnCard').scrollIntoView({block: 'center'})"),
                           cam("#stage", ["#cnnH", "#cnnCard"], max=2.2, pad=.06, dur=500),
                           spot("#cnnCard", "Scored on held-out chips · a <b>+0.003 \u201cwin\u201d was rejected as noise</b>", delay=550, pad=6, side="above")))

        # 3. ask the agents: typing (1.0 s), then the run (4.0 s, sped up)
        spot()
        js("showBeat(1, {animate: false}); document.querySelector('#askQ').scrollIntoView({block: 'center'})")
        cam("#stage", ["#askQ", "#runAgents"], max=2.3, pad=.12, dur=0)  # framed before the cut, so the shot opens steady
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
        spot("#agentTree .tf", "Run sped up · the brief is <b>graded by code</b>: real links, stated assumptions", delay=700)
        page.wait_for_function("/graded|failed/.test(document.querySelector('#treeFoot')?.textContent || '')", timeout=120_000)
        page.wait_for_timeout(1000)
        cuts.append((b, now(), 4.0))

        # 4. the legal paths (2.5 s), then SB 4's open checks (2.0 s)
        page.keyboard.press("Escape")
        shot(2.5, lambda: (js("showBeat(1)"), cam("#stage", [40, 20, 1530, 720], dur=750),
                           spot([46, 118, 1518, 82], "Fastest path that fits: <b>SB 4</b>, a 90-day statutory clock", delay=850, side="above")))
        shot(2.0, lambda: (js("document.querySelector('#panel .checks').scrollIntoView({block: 'center'})"),
                           cam("#stage", "#panel .checks", max=2.3, pad=.08, dur=450),
                           spot("#panel .checks li", "<b>Never assumed:</b> a map tag is not a title record", delay=500)))

        # 5. the clock (4.0 s)
        shot(4.0, lambda: (js("showBeat(2)"), cam("#stage", [90, 55, 1430, 625], dur=750),
                           spot([366, 610, 1010, 68], "Pre-screened site · <b>SB 4</b> by right · funding from day one", delay=1600)))

        # 6. capital (2.0 s) and 7. families (2.5 s)
        shot(2.0, lambda: (js("showBeat(4)"), cam("#stage", [100, 70, 1300, 450], dur=750),
                           spot([112, 466, 660, 34], "Only <b>real per-home shortfalls</b> need philanthropy", delay=850)))
        shot(2.5, lambda: (js("showBeat(3)"), cam("#stage", [110, 115, 1440, 420], dur=750),
                           spot([1070, 282, 430, 100], "Expected value over <b>1,500 simulated decades</b> per family", delay=1200)))

        # 8. the one-page summary (2.5 s)
        shot(2.5, lambda: (cam("#stage", None, dur=0), js("summary()"),
                           cam("#summary", "#summary .wordmark", k=1.1, dur=700),
                           spot("#summary .grid", "Every number links to its <b>formula and source</b>", delay=750)))

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


def subtitle_png(text, path):
    """One phrase as a transparent band-sized PNG: white bold text, **marked** words in teal, centred."""
    band = round(BAND * OUT_H / H)
    img = Image.new("RGBA", (OUT_W, band), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    parts = [(seg, i % 2 == 1) for i, seg in enumerate(re.split(r"\*\*", text)) if seg]
    size = 56
    while True:  # one line, as large as fits
        font = ImageFont.truetype(FONT[0], size, index=FONT[1])
        widths = [draw.textlength(seg, font=font) for seg, _ in parts]
        if sum(widths) <= OUT_W - 160 or size <= 36:
            break
        size -= 2
    x = (OUT_W - sum(widths)) / 2
    for (seg, teal), w in zip(parts, widths, strict=True):
        draw.text((x, band / 2 + 2), seg, font=font, fill=(46, 230, 190) if teal else (255, 255, 255), anchor="lm")
        x += w
    img.save(path)


def voiceover(workdir):
    """Audio inputs and filters (one clip per act, sped up only as needed) plus the subtitle timeline."""
    inputs, filters, subs = [], [], []
    for i, (start, slot, line, phrases) in enumerate(ACTS):
        clip = workdir / f"vo{i}.aiff"
        subprocess.run(["say", "-v", VOICE, "-r", "180", "-o", str(clip), line], check=True)
        dur = duration(clip)
        tempo = min(max(dur / (slot - 0.3), 1.0), 1.4)
        inputs += ["-i", str(clip)]
        filters.append(f"[{i + 1}:a]atempo={tempo:.3f},adelay={int((start + 0.1) * 1000)}:all=1[v{i}]")
        spoken, t = dur / tempo, start + 0.1
        weights = [len(re.sub(r"\*", "", ph)) for ph in phrases]
        for j, ph in enumerate(phrases):  # each phrase on screen for its share of the spoken line
            d = spoken * weights[j] / sum(weights)
            end = t + d if j < len(phrases) - 1 else min(start + slot, t + d + 0.35)
            subs.append((ph, t, end))
            t += d
        print(f"voiceover {i}: {dur:.2f}s in a {slot}s slot, tempo {tempo:.2f}")
    mix = "".join(f"[v{i}]" for i in range(len(ACTS))) + f"amix=inputs={len(ACTS)}:normalize=0[vo]"
    return inputs, filters + [mix], subs


def cut(raw, cuts, workdir, out):
    if duration(raw) < cuts[-1][1] - 0.2:  # a stalled screencast drops the tail; never ship a short cut
        raise SystemExit(f"raw recording is {duration(raw):.1f}s but the cuts end at {cuts[-1][1]:.1f}s: re-run")
    vf = [f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)*{slot / (b - a):.5f},fps=30[s{i}]"
          for i, (a, b, slot) in enumerate(cuts)]
    vf.append("".join(f"[s{i}]" for i in range(len(cuts))) +
              f"concat=n={len(cuts)}:v=1:a=0,tpad=stop_mode=clone:stop_duration=1,scale={OUT_W}:{OUT_H}:flags=lanczos[base]")
    a_inputs, af, subs = voiceover(workdir)
    n_audio = len(ACTS)
    s_inputs, last = [], "base"
    for k, (text, t0, t1) in enumerate(subs):
        png = workdir / f"sub{k}.png"
        subtitle_png(text, png)
        s_inputs += ["-loop", "1", "-t", f"{t1 - t0:.3f}", "-i", str(png)]
        nxt = "v" if k == len(subs) - 1 else f"o{k}"
        vf.append(f"[{1 + n_audio + k}:v]format=rgba,fade=in:st=0:d=0.18:alpha=1,setpts=PTS+{t0:.3f}/TB[t{k}]")
        vf.append(f"[{last}][t{k}]overlay=0:{OUT_H - round(BAND * OUT_H / H)}:eof_action=pass[{nxt}]")
        last = nxt
    subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), *a_inputs, *s_inputs,
                    "-filter_complex", ";".join(vf + af), "-map", "[v]", "-map", "[vo]", "-t", "30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "slow", "-crf", "18",
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
