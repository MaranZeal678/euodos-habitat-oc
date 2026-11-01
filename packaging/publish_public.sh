#!/usr/bin/env bash
# Mirror a release's .dmg from this (private) repo to the public downloads repo, after checking it is byte-for-byte the
# file CI built and smoke-tested.   packaging/publish_public.sh v0.2.0
set -euo pipefail
TAG=${1:?usage: packaging/publish_public.sh <tag>}
SRC=MaranZeal678/keystone-habitat-oc
DST=MaranZeal678/keystone-releases
cd "$(dirname "$0")/.."
NOTES=$PWD/packaging/RELEASE_NOTES.md
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"
gh release download "$TAG" -R "$SRC" -p "Keystone-*.dmg*"
DMG=$(ls Keystone-*.dmg)
[ "$(awk '{print $1}' "$DMG.sha256")" = "$(shasum -a 256 "$DMG" | awk '{print $1}')" ] || { echo "checksum mismatch for $DMG"; exit 1; }
shasum -a 256 "$DMG" > "$DMG.sha256"  # bare file name, so `shasum -c` works for whoever downloads it
gh release create "$TAG" -R "$DST" --title "Keystone ${TAG#v}" --notes-file "$NOTES" "$DMG" "$DMG.sha256"
echo "public: https://github.com/$DST/releases/tag/$TAG"
