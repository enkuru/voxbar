#!/bin/bash
# Install Voxbar and start it as a LaunchAgent (auto-starts at login)
set -e

VOXBAR_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.voxbar.agent"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
PYTHON="$(which python3)"
SCRIPT="$VOXBAR_DIR/voxbar.py"

# Check dependencies
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.12+ first."
    exit 1
fi

if ! command -v cliclick &>/dev/null; then
    echo "Error: cliclick not found. Install with: brew install cliclick"
    exit 1
fi

if ! python3 -c "import objc" &>/dev/null; then
    echo "Installing Python dependencies..."
    pip3 install -r "$VOXBAR_DIR/requirements.txt"
fi

# Stop existing instance
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
pkill -f "python.*voxbar.py" 2>/dev/null && sleep 1 || true

# Copy example config if needed
if [ ! -f "$VOXBAR_DIR/config.json" ]; then
    cp "$VOXBAR_DIR/config.example.json" "$VOXBAR_DIR/config.json"
    echo "Created config.json from example."
fi

# Generate LaunchAgent plist
mkdir -p "$(dirname "$PLIST_DST")"
cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$VOXBAR_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardErrorPath</key>
    <string>/tmp/voxbar.err.log</string>
</dict>
</plist>
PLIST

# Install CLI globally
mkdir -p "$HOME/.local/bin"
ln -sf "$VOXBAR_DIR/voxbar" "$HOME/.local/bin/voxbar"

# Start
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo ""
echo "Voxbar installed and running!"
echo "It will auto-start at login."
echo ""
echo "Commands: voxbar start | stop | restart | status"
echo ""
echo "Grant Accessibility permissions to python3 and cliclick in:"
echo "  System Settings → Privacy & Security → Accessibility"
