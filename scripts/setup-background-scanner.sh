#!/bin/bash
# Setup script for Kroger background scanner

set -e

PROJECT_DIR="/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp"
PLIST_SRC="$PROJECT_DIR/scripts/com.user.kroger-discount-scanner.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.user.kroger-discount-scanner.plist"
WRAPPER_SRC="$PROJECT_DIR/scripts/kroger-scanner-wrapper.sh"
WRAPPER_DEST="/usr/local/bin/kroger-scanner-wrapper"

echo "=== Kroger Background Scanner Setup ==="
echo ""

# Check if .env file exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ERROR: .env file not found at $PROJECT_DIR/.env"
    echo "Please create .env file with KROGER_CLIENT_ID, KROGER_CLIENT_SECRET, and KROGER_PREFERRED_LOCATION"
    exit 1
fi

# Load environment variables
source "$PROJECT_DIR/.env"

if [ -z "$KROGER_CLIENT_ID" ] || [ -z "$KROGER_CLIENT_SECRET" ] || [ -z "$KROGER_PREFERRED_LOCATION" ]; then
    echo "ERROR: Missing required environment variables in .env file"
    echo "Required: KROGER_CLIENT_ID, KROGER_CLIENT_SECRET, KROGER_PREFERRED_LOCATION"
    exit 1
fi

echo "✓ Environment variables loaded from .env"

# Update plist with environment variables
echo "Updating plist with credentials..."
sed -e "s|YOUR_CLIENT_ID_HERE|$KROGER_CLIENT_ID|g" \
    -e "s|YOUR_CLIENT_SECRET_HERE|$KROGER_CLIENT_SECRET|g" \
    -e "s|YOUR_LOCATION_ID_HERE|$KROGER_PREFERRED_LOCATION|g" \
    "$PLIST_SRC" > "/tmp/kroger-scanner.plist"

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$HOME/Library/LaunchAgents"

# Copy plist to LaunchAgents
echo "Installing launch agent..."
cp "/tmp/kroger-scanner.plist" "$PLIST_DEST"
rm "/tmp/kroger-scanner.plist"
echo "✓ Installed: $PLIST_DEST"

# Copy wrapper script to /usr/local/bin (requires sudo)
echo "Installing wrapper script to /usr/local/bin (requires sudo)..."
sudo cp "$WRAPPER_SRC" "$WRAPPER_DEST"
sudo chmod +x "$WRAPPER_DEST"
echo "✓ Installed: $WRAPPER_DEST"

# Make background scanner executable
chmod +x "$PROJECT_DIR/scripts/background_scanner.py"
echo "✓ Made scanner script executable"

# Unload existing agent if running
if launchctl list | grep -q "com.user.kroger-discount-scanner"; then
    echo "Unloading existing agent..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Load the launch agent
echo "Loading launch agent..."
launchctl load "$PLIST_DEST"
echo "✓ Launch agent loaded"

# Verify it's loaded
if launchctl list | grep -q "com.user.kroger-discount-scanner"; then
    echo "✓ Launch agent is running"
else
    echo "WARNING: Launch agent may not be running. Check with: launchctl list | grep kroger"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "The scanner will run automatically on:"
echo "  - Monday at 9:00 AM"
echo "  - Thursday at 9:00 AM"
echo ""
echo "To test manually, run:"
echo "  launchctl start com.user.kroger-discount-scanner"
echo ""
echo "To view logs:"
echo "  tail -f ~/Library/Logs/KrogerScanner/scanner.log"
echo "  tail -f /tmp/kroger-scanner-out.log"
echo "  tail -f /tmp/kroger-scanner-err.log"
echo ""
echo "To uninstall:"
echo "  launchctl unload $PLIST_DEST"
echo "  rm $PLIST_DEST"
echo "  sudo rm $WRAPPER_DEST"
