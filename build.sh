#!/bin/bash
# Install and launch Voxbar as a LaunchAgent (auto-starts at login)
set -e

VOXBAR_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.voxbar.agent"
PLIST_SRC="$VOXBAR_DIR/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

# Stop existing instance
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
killall -9 Python 2>/dev/null && sleep 1 || true

# Install LaunchAgent
cp "$PLIST_SRC" "$PLIST_DST"

# Start
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "Voxbar installed and running. Will auto-start at login."
