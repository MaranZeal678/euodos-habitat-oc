Euodos for Habitat for Humanity of Orange County's Keys to 100, as a Mac app. It opens on the **Crossline Church scenario** (Impact Lab Lane 2, Clear it): a congregation offers its parking lot, and Euodos shows how 30 families move in within 2.4 years instead of 4.2: the site screened in minutes, SB 4 by-right approval, and funding plus family pre-qualification starting on day one. The dashboard, the agent hierarchy, the mortgage designer and the MCP server are all included and run locally.

**Demo sign-in:** `maria@habitat-oc.demo` / `keys-to-100` (a demo persona; each session gets its own copy of the scenario, and nothing it changes is saved). The **Go** menu also plays the 30-second film.

**New in 0.4.0:** the product is now called **Euodos** (formerly Keystone). Same scenario, same models; the app, its window and its data folder carry the new name.

**New in 0.3.2:** the offer step lists every public dataset Euodos uses and shows the parking CNN's model card (held-out IoU, and the challenger the promotion gate rejected).

**New in 0.3.1:** type a question for the agents and watch the hierarchy work live (Director, leads, workers), with the policy each run really used; the clock shows the whole project as one bar shrinking from 4.2 to 2.4 years; the summary carries the Euodos wordmark.

**New in 0.3.0:** step 2, *The path*: seven legal paths (SB 4, SB 35/423, SB 684, SB 9 duplex, SB 9 lot split, ADU, rezone) tested against the parcel, each with its current statute, clock and checks marked met, to verify or fails. Change the project size, zoning or city status and the verdicts update; pick a path and the clock follows.

**New in 0.2.1:** a one-page summary of the scenario (press **P** or click **Summary**), edits confirm on screen once the live models finish, and the layout holds at the smallest window size.

**Install**

1. Download `Euodos-<version>.dmg`, open it, and drag Euodos into Applications.
2. The app is not signed with an Apple Developer ID yet, so macOS blocks the first launch. Open it once, then go to **System Settings → Privacy & Security** and click **Open Anyway** next to the Euodos message. Or, in Terminal: `xattr -dr com.apple.quarantine /Applications/Euodos.app`
3. Your runs, skills and agent lessons are saved in `~/Library/Application Support/Euodos`.

**Requirements:** a Mac with Apple Silicon (M1 or later) on macOS 13 or newer.

**Limits of the desktop build**

- Agents run on the offline scripted policy. To use Claude, start the app from Terminal with your key set (apps opened from Finder do not see shell variables): `ANTHROPIC_API_KEY=... /Applications/Euodos.app/Contents/MacOS/Euodos`
- Live re-scans of parcel imagery are not included (they need PyTorch). Site inspection uses the stored CNN scans and says so.
- Everything runs on your Mac; only the map's street tiles in the 3D demo and the Land tab are fetched online, so offline the map background is blank.

Verify the download: `shasum -a 256 Euodos-<version>.dmg` must match the `.sha256` file.
