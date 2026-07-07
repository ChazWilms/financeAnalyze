#!/bin/bash
# run.sh — refresh the whole pipeline in one command.
# Drop new CSVs in data/raw/ first, then: bash run.sh
set -e
cd "$(dirname "$0")"

echo "▶ Normalizing transactions…"
python3 scripts/normalize.py

echo ""
echo "▶ Snapshot:"
python3 scripts/summary.py

echo ""
echo "▶ Saving full report to reports/…"
python3 scripts/analyze.py --save >/dev/null
echo "  done."

echo ""
echo "Next:"
echo "  • open dashboard.html for the interactive view"
echo "  • python3 scripts/safe_to_spend.py     (today's number + budget vs actual)"
echo "  • python3 scripts/planning.py subs|loans|savings|fuel|commute|car"
