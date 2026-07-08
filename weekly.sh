#!/bin/bash
# weekly.sh — the once-a-week refresh + report, in one command.
#
#   bash weekly.sh
#
# 1. Pulls new transactions: SimpleFIN auto-sync if configured, and any fresh
#    CSV exports sitting in ~/Downloads (refresh.py finds them by content).
# 2. Regenerates the weekly LLM-queryable report -> reports/weekly/latest.md
# 3. Pops a macOS notification with the headline numbers.
#
# Scheduled automatically every Sunday 5pm via
# ~/Library/LaunchAgents/com.user.finance.weekly.plist (see CONNECT_ACCOUNTS.md).
set -u
cd "$(dirname "$0")" || exit 1

echo "════════ Finance Analyzer weekly run — $(date) ════════"

# Auto-sync via SimpleFIN if it's been set up (optional; see simplefin_sync.py)
if [ -f config/simplefin_access.url ]; then
  echo "▶ SimpleFIN sync…"
  python3 scripts/simplefin_sync.py || echo "  (SimpleFIN sync failed — continuing with local data)"
fi

echo "▶ Ingesting new exports from ~/Downloads + normalizing…"
python3 scripts/refresh.py

echo ""
echo "▶ Building weekly report…"
python3 scripts/weekly_report.py >/dev/null || exit 1

REPORT="$PWD/reports/weekly/latest.md"
HEADLINE="$(grep -m1 '^- \*\*Income:' "$REPORT" | sed 's/\*//g; s/^- *//')"
STALE="$(grep -m1 'account(s) stale' "$REPORT" >/dev/null && echo ' ⚠ some data stale — export fresh CSVs' || true)"

echo ""
echo "Weekly report ready: $REPORT"
echo "  $HEADLINE$STALE"

if command -v osascript >/dev/null 2>&1; then
  CLEAN="$(printf '%s' "${HEADLINE}${STALE}" | tr -d '"\\')"
  osascript -e "display notification \"${CLEAN}\" with title \"📊 Weekly finance report ready\" subtitle \"reports/weekly/latest.md\"" 2>/dev/null || true
fi

# Phone delivery (iMessage / ntfy / email — config/notify.json, optional).
python3 scripts/notify.py "📊 Weekly report ready — ${HEADLINE}${STALE}" || true
