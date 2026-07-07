#!/bin/bash
# morning.sh — prints your daily safe-to-spend message and (on macOS) pops a
# desktop notification. This is the hook for the "text me each morning" feature:
# swap the notification line for a Pushover/Twilio/email call when ready.
#
# Run it manually:   bash scripts/morning.sh
# Or schedule it (see MORNING_MESSAGE.md) to run every morning.

cd "$(dirname "$0")/.." || exit 1

# Use the freshest data you've imported. (If you drop new CSVs in data/raw/,
# uncomment the next line to re-normalize before computing.)
# python3 scripts/normalize.py >/dev/null 2>&1

# Pull fresh transactions first if SimpleFIN auto-sync is set up, so the
# number reflects yesterday's spending (failures fall back to local data).
if [ -f config/simplefin_access.url ]; then
  python3 scripts/simplefin_sync.py >/dev/null 2>&1 || true
fi

MSG="$(python3 scripts/safe_to_spend.py --message-only)"
echo "$MSG"

# --- Notify (macOS desktop). Replace with your phone notifier later. ---------
if command -v osascript >/dev/null 2>&1; then
  # strip emoji/quotes that can confuse AppleScript
  CLEAN="$(printf '%s' "$MSG" | tr -d '"\\' )"
  osascript -e "display notification \"${CLEAN}\" with title \"💸 Finance Analyzer\"" 2>/dev/null || true
fi

# --- Phone delivery (iMessage / ntfy / email) --------------------------------
# Configured in config/notify.json (git-ignored); skipped silently if absent.
python3 scripts/notify.py "$MSG" || true

# --- Phone push examples (uncomment + fill in to enable) --------------------
# Pushover (https://pushover.net): free, simple phone push
# curl -s -F "token=APP_TOKEN" -F "user=USER_KEY" -F "message=$MSG" \
#   https://api.pushover.net/1/messages.json >/dev/null
#
# Email-to-SMS (most carriers): send to e.g. 4195551234@vtext.com (Verizon)
# printf '%s' "$MSG" | mail -s "Safe to spend" 4195551234@vtext.com
