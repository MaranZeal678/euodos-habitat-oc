Keystone for Habitat for Humanity of Orange County's Keys to 100, as a Mac app. It opens on the **Crossline Church scenario** (Impact Lab Lane 2, Clear it): a congregation offers its parking lot, and Keystone shows how 30 families move in within 2.4 years instead of 4.2: the site screened in minutes, SB 4 by-right approval, and funding plus family pre-qualification starting on day one. The dashboard, the agent hierarchy, the mortgage designer and the MCP server are all included and run locally.

**Demo sign-in:** `maria@habitat-oc.demo` / `keys-to-100` (a demo persona; each session gets its own copy of the scenario, and nothing it changes is saved). The **Go** menu also plays the 30-second film.

**Install**

1. Download `Keystone-<version>.dmg`, open it, and drag Keystone into Applications.
2. The app is not signed with an Apple Developer ID yet, so macOS blocks the first launch. Open it once, then go to **System Settings → Privacy & Security** and click **Open Anyway** next to the Keystone message. Or, in Terminal: `xattr -dr com.apple.quarantine /Applications/Keystone.app`
3. Your runs, skills and agent lessons are saved in `~/Library/Application Support/Keystone`.

**Requirements:** a Mac with Apple Silicon (M1 or later) on macOS 13 or newer.

**Limits of the desktop build**

- Agents run on the offline scripted policy. To use Claude, start the app from Terminal with your key set (apps opened from Finder do not see shell variables): `ANTHROPIC_API_KEY=... /Applications/Keystone.app/Contents/MacOS/Keystone`
- Live re-scans of parcel imagery are not included (they need PyTorch). Site inspection uses the stored CNN scans and says so.
- Everything runs on your Mac; only the map's street tiles in the 3D demo and the Land tab are fetched online, so offline the map background is blank.

Verify the download: `shasum -a 256 Keystone-<version>.dmg` must match the `.sha256` file.
