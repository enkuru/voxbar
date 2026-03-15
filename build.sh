#!/bin/bash
# Build and deploy Voxbar.app to /Applications using py2app
set -e

VOXBAR_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VOXBAR_DIR"

echo "Building Voxbar with py2app..."
rm -rf build dist
python3 setup.py py2app 2>&1 | tail -5

echo "Deploying to /Applications..."
killall -9 Voxbar 2>/dev/null || true
sleep 1
rm -rf /Applications/Voxbar.app
cp -R dist/Voxbar.app /Applications/Voxbar.app
xattr -cr /Applications/Voxbar.app 2>/dev/null || true

echo "Launching..."
open /Applications/Voxbar.app
echo "Done."
