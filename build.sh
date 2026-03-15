#!/bin/bash
# Rebuild and deploy Voxbar.app to /Applications
set -e

VOXBAR_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Deploying Voxbar..."
killall -9 Voxbar 2>/dev/null || true
sleep 1
rm -rf /Applications/Voxbar.app
cp -R "$VOXBAR_DIR/Voxbar.app" /Applications/Voxbar.app
echo "APPL????" > /Applications/Voxbar.app/Contents/PkgInfo
xattr -cr /Applications/Voxbar.app 2>/dev/null || true
echo "Launching..."
open /Applications/Voxbar.app
echo "Done."
