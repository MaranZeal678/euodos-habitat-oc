#!/usr/bin/env bash
# Build Keystone.app and Keystone-<version>.dmg, then smoke-test the bundled app headless.
#   packaging/build_macos.sh            (needs: pip install -r packaging/requirements-desktop.txt)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
VERSION=$(cat packaging/VERSION)
DIST=packaging/dist
rm -rf "$DIST" packaging/build/work
"$PY" packaging/make_icon.py packaging/build/Keystone.icns
"$PY" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "$DIST" --workpath packaging/build/work packaging/keystone.spec

# the bundled app must start, find its data, run the sandbox and the MCP child, and complete a graded agent mission
SMOKE_STATE=$(mktemp -d)
KEYSTONE_STATE_DIR="$SMOKE_STATE" "$DIST/Keystone.app/Contents/MacOS/Keystone" --smoke
rm -rf "$SMOKE_STATE"

# drag-to-install disk image: the app plus a shortcut to /Applications
STAGE=$(mktemp -d)
cp -R "$DIST/Keystone.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "Keystone $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DIST/Keystone-$VERSION.dmg"
rm -rf "$STAGE"
shasum -a 256 "$DIST/Keystone-$VERSION.dmg" | tee "$DIST/Keystone-$VERSION.dmg.sha256"
du -sh "$DIST/Keystone.app" "$DIST/Keystone-$VERSION.dmg"
