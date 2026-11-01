Keystone for Habitat for Humanity of Orange County's Keys to 100, as a Mac app: the dashboard, the mission-control demo, the agent hierarchy, the mortgage designer and the MCP server, all running locally.

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
