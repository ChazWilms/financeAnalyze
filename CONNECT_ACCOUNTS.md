# Connecting your Discover + Huntington accounts

The blunt truth first: **neither Discover nor Huntington offers a personal-use
API.** There are exactly two ways to get your transactions into this app, and
both are wired up and ready:

| | Option A — CSV drop (default) | Option B — SimpleFIN auto-sync |
|---|---|---|
| Cost | Free | ~$1.50/mo (bridge.simplefin.org) |
| Effort | ~3 min/week of clicking | Zero after setup |
| Privacy | **Data never leaves your Mac** | Transactions flow through SimpleFIN/MX (a third-party aggregator you give bank credentials to) |
| Freshness | As fresh as your last export | Daily |

Either way, everything downstream (normalize → analyze → weekly report →
dashboard) is identical.

---

## Option A — the CSV drop routine (what's active now)

Once a week (Sunday afternoon fits the 5pm auto-report), download fresh
exports. **You don't need to rename or move anything** — just let them land in
`~/Downloads`; the pipeline identifies them by their contents:

**Discover** (discover.com → log in):
Activity & Statements → *All Activity & Statements* → pick a date range
covering since your last export → **Download** → CSV.

**Huntington** (huntington.com → log in, once per account —
checking, hub, savings):
Select the account → transaction history → **Export** → CSV
(“spreadsheet”). Overlapping date ranges are fine — duplicates are removed
automatically.

Then either wait for the Sunday 5:03pm auto-run, or run it yourself:

```bash
cd ~/Desktop/FinanceAnalyzer && bash weekly.sh     # full weekly run
# or just:  python3 scripts/refresh.py             # ingest + normalize only
```

`refresh.py` scans `~/Downloads` for anything that looks like a bank export
(by header signature), figures out **which** Huntington account a file belongs
to by matching its rows against your history, copies it into `data/raw/` with
a canonical datestamped name, de-dupes, and re-normalizes. It keeps a content-
hash ledger (`data/raw/.ingested.json`) so it never ingests the same file
twice, and it never touches the originals in Downloads.

If it can't tell which Huntington account a file is (brand-new account, no
overlapping history), it says so — rename the file to include
`checking`, `hub`, or `savings` and re-run.

## Option B — SimpleFIN auto-sync (optional, true "connected accounts")

If you decide the weekly clicking isn't worth it, SimpleFIN Bridge is the
privacy-friendliest aggregator (it's what Actual Budget uses; flat fee, no
selling data, read-only access). Setup is four steps — see the header of
`scripts/simplefin_sync.py`. After that, `weekly.sh` automatically pulls new
transactions every week before building the report; no more exports.

**Tradeoff to be clear about:** you're giving your Discover + Huntington
logins to their aggregator (MX), and your transaction data transits their
servers. That's the industry-standard mechanism (every budgeting app works
this way), but it *is* a departure from this app's fully-local design. Your
call. The app never requires it.

## The weekly report

Every Sunday at 5:03pm, launchd runs `weekly.sh`
(`~/Library/LaunchAgents/com.user.finance.weekly.plist`), which syncs
whatever data is available and writes:

- `reports/weekly/latest.md` — always the newest report
- `reports/weekly/weekly_<date>.md` — the archive

You'll get a desktop notification with the headline (income / spend / net,
plus a staleness warning if you haven't exported lately).

**To have an LLM explain it** (the whole point):

- **Claude Code / Claude Desktop:** open this folder and ask —
  *"read my weekly report and explain it"* (Claude reads
  `reports/weekly/latest.md` and can dig into the underlying data for
  follow-ups), or
- **claude.ai or any chatbot:** drag `reports/weekly/latest.md` into the
  chat. The report is self-contained — it explains its own conventions to
  the model, and ends with suggested questions worth asking.

Manage the schedule:

```bash
launchctl unload ~/Library/LaunchAgents/com.user.finance.weekly.plist  # pause
launchctl load   ~/Library/LaunchAgents/com.user.finance.weekly.plist  # resume
bash ~/Desktop/FinanceAnalyzer/weekly.sh                               # run now
tail /tmp/finance_weekly.log                                           # last run's output
```
