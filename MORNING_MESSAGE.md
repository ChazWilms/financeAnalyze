# 📱 Morning "safe-to-spend" message — setup

The number you wanted texted to you each morning is already computed by
`scripts/safe_to_spend.py --message-only`, e.g.:

> 💸 Safe to spend today: ~$25.00 · this week: ~$175.00 ($175.00 left of your
> $500.00 discretionary budget this month — 7 days to go)

`scripts/morning.sh` wraps that and pops a **macOS desktop notification**. To
actually push it to your **phone**, pick one of the options below — then it can
run automatically every morning.

## Step 1 — try it now
```bash
bash ~/Desktop/FinanceAnalyzer/scripts/morning.sh
```

## Step 2 — choose how it reaches your phone
- **Pushover** (easiest, ~$5 one-time): make an app token + user key, then
  uncomment the `curl` block in `morning.sh`. Reliable push to iOS/Android.
- **Email-to-SMS** (free): most carriers accept email → text (e.g. Verizon
  `number@vtext.com`, AT&T `@txt.att.net`). Uncomment the `mail` line.
- **Twilio** (real SMS, pay-per-text): add a 3-line `curl` to their API.
- **macOS only**: the built-in desktop notification already works, no setup.

## Step 3 — run it automatically each morning (macOS launchd)
Save this as `~/Library/LaunchAgents/com.user.finance.morning.plist`, then
`launchctl load ~/Library/LaunchAgents/com.user.finance.morning.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.user.finance.morning</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/YOURNAME/Desktop/FinanceAnalyzer/scripts/morning.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/finance_morning.log</string>
  <key>StandardErrorPath</key><string>/tmp/finance_morning.err</string>
</dict></plist>
```

This fires at **8:00 AM daily**. For a weekly Monday message instead, add
`<key>Weekday</key><integer>1</integer>` inside the `StartCalendarInterval` dict.

> Note: the message reflects the latest data you've imported. To keep it current
> you'll want to drop fresh transaction CSVs into `data/raw/` periodically and
> re-run `scripts/normalize.py` (or uncomment that line in `morning.sh`).
