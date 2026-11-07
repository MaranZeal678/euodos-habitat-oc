# The 30-second demo video

File: [`euodos_30s.mp4`](euodos_30s.mp4). It is 30.0 s, 1920×1080, recorded from the live app (not a mock-up) by [`scripts/record_app_demo.py`](../scripts/record_app_demo.py).

## Shot list

| Time (s) | Shot | Spotlight label |
|---|---|---|
| 0.0–2.5 | Maria signs in | Demo persona · each session gets its own private copy |
| 2.5–5.5 | CNN scan: 45,450 m² | A U-Net CNN reads parking from 0.6 m aerial imagery |
| 5.5–7.5 | Public data list | No personal information · every source is free to download |
| 7.5–9.5 | CNN model card | Scored on held-out chips · a +0.003 "win" was rejected as noise |
| 9.5–10.5 | She types a question to the agents | — |
| 10.5–14.5 | Live agent hierarchy (sped up) | Run sped up · the brief is graded by code |
| 14.5–17.0 | Seven legal paths | Fastest path that fits: SB 4, a 90-day statutory clock |
| 17.0–19.0 | SB 4's checks | Never assumed: a map tag is not a title record |
| 19.0–23.0 | Clock: red 4.2 years shrinks to green 2.4 | Pre-screened site · SB 4 by right · funding from day one |
| 23.0–25.0 | Capital stack | Only real per-home shortfalls need philanthropy |
| 25.0–27.5 | Families keeping their homes | Expected value over 1,500 simulated decades per family |
| 27.5–30.0 | One-page summary | Every number links to its formula and source |

## Voiceover and subtitles

| Starts at (s) | Line |
|---|---|
| 0.0 | "Knowing if Habitat can build takes years. Until now." |
| 4.5 | "Public data only. A CNN reads parking lots from aerial photos." |
| 9.5 | "Meet Euodos: Claude agents and live models, working the parcel." |
| 14.5 | "Seven legal paths. SB 4 is the fastest fit, with three facts to verify. Four years becomes two point four." |
| 23.0 | "Families who keep their homes, and the capital gap, home by home. Keys to one hundred starts here." |

The voice is the Mac's built-in "Reed" at 180 words per minute. Subtitles show each line phrase by phrase in the bottom band.

## Re-record

```bash
KEYSTONE_DEMO_LOGIN=1 .venv/bin/uvicorn keystone.app.server:app --port 8010
```

```bash
.venv/bin/python scripts/record_app_demo.py --url http://localhost:8010 --out hackathon-info/euodos_30s.mp4
```
