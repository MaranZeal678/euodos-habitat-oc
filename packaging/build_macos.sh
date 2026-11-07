#!/usr/bin/env bash
# Build Euodos.app and Euodos-<version>.dmg, then smoke-test the bundled app headless.
#   packaging/build_macos.sh            (needs: pip install -r packaging/requirements-desktop.txt)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
VERSION=$(cat packaging/VERSION)
DIST=packaging/dist
rm -rf "$DIST" packaging/build/work
"$PY" packaging/make_icon.py packaging/build/Euodos.icns
"$PY" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "$DIST" --workpath packaging/build/work packaging/keystone.spec

# the bundled app must start, find its data, run the sandbox and the MCP child, and complete a graded agent mission
SMOKE_STATE=$(mktemp -d)
KEYSTONE_STATE_DIR="$SMOKE_STATE" "$DIST/Euodos.app/Contents/MacOS/Euodos" --smoke
rm -rf "$SMOKE_STATE"

# drag-to-install disk image: the app plus a shortcut to /Applications
STAGE=$(mktemp -d)
cp -R "$DIST/Euodos.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "Euodos $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DIST/Euodos-$VERSION.dmg"
rm -rf "$STAGE"
(cd "$DIST" && shasum -a 256 "Euodos-$VERSION.dmg" | tee "Euodos-$VERSION.dmg.sha256")  # bare name: `shasum -c` works after download
du -sh "$DIST/Euodos.app" "$DIST/Euodos-$VERSION.dmg"
