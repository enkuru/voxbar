#!/bin/bash
# Uninstall Voxbar: stop the service and remove the LaunchAgent
set -e

PLIST_NAME="com.voxbar.agent"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

echo "Stopping Voxbar..."
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
pkill -f "python.*voxbar.py" 2>/dev/null || true

echo "Removing LaunchAgent..."
rm -f "$PLIST_DST"

echo "Voxbar uninstalled."
echo "To remove the source files: rm -rf $(cd "$(dirname "$0")" && pwd)"
