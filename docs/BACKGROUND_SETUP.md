# Background Scanner Setup Guide

Automate deal scanning with macOS launchd for twice-weekly discount checking.

## Overview

The background scanner automatically checks your watchlist for deals:
- **Schedule**: Monday & Thursday at 9:00 AM
- **Notifications**: macOS notifications when deals found
- **Logging**: Detailed logs in `~/Library/Logs/KrogerScanner/`
- **View Results**: Use `get_latest_deal_scan` MCP tool with Claude

## Quick Setup

### Prerequisites

1. **Kroger API Credentials** in `.env` file:
   ```bash
   KROGER_CLIENT_ID=your_client_id
   KROGER_CLIENT_SECRET=your_client_secret
   KROGER_PREFERRED_LOCATION=your_location_id
   ```

2. **Preferred Location Set**: Use `set_preferred_location` tool first

3. **Items in Watchlist**: Add items with `add_to_watchlist` tool

### Automated Setup (Recommended)

```bash
cd /Users/jeremyparker/Desktop/Claude\ Coding\ Projects/kroger-mcp
bash scripts/setup-background-scanner.sh
```

This script:
- ✅ Loads credentials from `.env` file
- ✅ Creates configured launchd plist
- ✅ Installs wrapper script to `/usr/local/bin/`
- ✅ Makes scanner executable
- ✅ Loads launch agent
- ✅ Verifies installation

### Manual Setup

If you prefer manual setup:

1. **Copy plist template**:
   ```bash
   cp scripts/com.user.kroger-discount-scanner.plist ~/Library/LaunchAgents/
   ```

2. **Edit plist** with your credentials:
   ```bash
   nano ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
   ```
   Replace `YOUR_CLIENT_ID_HERE`, `YOUR_CLIENT_SECRET_HERE`, and `YOUR_LOCATION_ID_HERE`

3. **Install wrapper script**:
   ```bash
   sudo cp scripts/kroger-scanner-wrapper.sh /usr/local/bin/kroger-scanner-wrapper
   sudo chmod +x /usr/local/bin/kroger-scanner-wrapper
   ```

4. **Make scanner executable**:
   ```bash
   chmod +x scripts/background_scanner.py
   ```

5. **Load launch agent**:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
   ```

## Verification

### Check if Running

```bash
launchctl list | grep kroger
```

Should show: `com.user.kroger-discount-scanner`

### Test Manually

```bash
launchctl start com.user.kroger-discount-scanner
```

### View Logs

```bash
# Scanner logs
tail -f ~/Library/Logs/KrogerScanner/scanner.log

# stdout logs
tail -f /tmp/kroger-scanner-out.log

# stderr logs
tail -f /tmp/kroger-scanner-err.log
```

### View Results in Claude

After a scan runs:

```python
# Ask Claude to get latest scan results
get_latest_deal_scan()
```

## How It Works

### Scan Process

1. **Trigger**: launchd starts script Mon/Thu at 9 AM
2. **Load Watchlist**: Reads up to 50 items from `deal_watchlist` table
3. **Check Prices**: Calls Kroger API for each item
4. **Detect Deals**: Filters to items with promo price < regular price
5. **Record Prices**: Saves to `price_history` table (for trend analysis)
6. **Save Results**: Writes deals to `deal_scan_results` table
7. **Notify**: Sends macOS notification if deals found

### API Usage

- **Max Items**: 50 per scan (configurable in script)
- **Frequency**: Twice weekly = ~100 API calls/week
- **Daily Average**: ~14 API calls/day
- **Well Under Limit**: 10,000 calls/day limit

### Database Tables

**deal_watchlist** - Items to scan
- Added via `add_to_watchlist` tool
- Priority levels: 1=low, 2=medium, 3=high

**deal_scan_results** - Scan findings
- Stored for 7 days
- View with `get_latest_deal_scan` tool

**price_history** - All price observations
- Used for trend analysis
- View with `get_price_history` tool

## Customization

### Change Schedule

Edit `~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist`:

```xml
<!-- Example: Add Sunday 8 PM -->
<dict>
  <key>Weekday</key>
  <integer>0</integer>  <!-- 0=Sunday, 1=Monday, etc. -->
  <key>Hour</key>
  <integer>20</integer>
  <key>Minute</key>
  <integer>0</integer>
</dict>
```

Reload agent after changes:
```bash
launchctl unload ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
launchctl load ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
```

### Increase Scan Limit

Edit `scripts/background_scanner.py`:

```python
# Change from 50 to 100 items
LIMIT 100
```

### Disable Notifications

Edit `scripts/background_scanner.py`:

```python
# Comment out notification call
# send_notification(len(deals_found))
```

## Troubleshooting

### Agent Not Running

```bash
# Check status
launchctl list | grep kroger

# View errors
cat /tmp/kroger-scanner-err.log

# Reload agent
launchctl unload ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
launchctl load ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
```

### No Deals Found

- **Add items to watchlist**: Use `add_to_watchlist` tool
- **Check logs**: Look for API errors in scanner.log
- **Verify credentials**: Ensure `.env` has valid API keys
- **Test manually**: Run `launchctl start com.user.kroger-discount-scanner`

### Permission Errors

```bash
# Ensure scripts are executable
chmod +x scripts/background_scanner.py
sudo chmod +x /usr/local/bin/kroger-scanner-wrapper

# Check plist permissions
chmod 644 ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
```

### API Limit Reached

Reduce scan frequency or limit items:
- Edit plist to scan weekly instead of twice weekly
- Lower LIMIT in background_scanner.py

## Uninstallation

```bash
# Unload agent
launchctl unload ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist

# Remove files
rm ~/Library/LaunchAgents/com.user.kroger-discount-scanner.plist
sudo rm /usr/local/bin/kroger-scanner-wrapper

# Optional: Clean logs
rm -rf ~/Library/Logs/KrogerScanner
```

## Advanced Usage

### Multiple Locations

To scan different locations on different days:

1. Create separate plist files (one per location)
2. Set different environment variables per plist
3. Load both agents

### Custom Filters

Edit `background_scanner.py` to add filters:

```python
# Only scan items with target_price set
if not item.get("target_price"):
    continue

# Only scan high-priority items
if item.get("priority", 0) < 3:
    continue
```

### Integration with Shortcuts

Create macOS Shortcut to:
1. Trigger manual scan: `launchctl start com.user.kroger-discount-scanner`
2. Read latest results: Parse `deal_scan_results` table
3. Send to specific apps (Messages, Slack, etc.)

## Security Notes

- **Credentials in plist**: plist file contains API credentials
- **File permissions**: Ensure plist is 644 (readable by user only)
- **Alternative**: Use macOS Keychain for credentials (advanced)
- **Logs**: Logs may contain product info, stored locally only

## Support

For issues or questions:
- Check logs first: `~/Library/Logs/KrogerScanner/scanner.log`
- Review launchd docs: `man launchd.plist`
- Test script directly: `python3 scripts/background_scanner.py`
- File issue: [GitHub Issues](https://github.com/yourusername/kroger-mcp/issues)
