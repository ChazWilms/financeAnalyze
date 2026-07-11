# 💳 Finance Analyzer

A private, reusable tool to analyze your **Huntington Bank** and **credit card**
transaction history. Built for two modes of use:

- **Visual & interactive** — open `dashboard.html`, drop in your CSVs, and
  filter/explore everything in your browser.
- **Deep written analysis** — tell Claude *"use the Finance Analyzer"* (or drop
  files in `data/raw/`) and it reads `APP_INSTRUCTIONS.md`, runs the pipeline,
  and gives you a thorough breakdown in chat.

Everything runs **locally**. Your financial data never leaves your machine.

---

## Quick start — interactive dashboard (no setup)

1. Export your transactions as CSV from Huntington and your credit card site.
2. Double-click **`dashboard.html`** (opens in your browser).
3. Drag the CSV files onto the page.

You get instant KPIs (in / out / net / savings rate), monthly cash-flow charts,
spending-by-category, top merchants, recurring-charge detection, anomaly flags,
and a sortable, filterable transaction table. Your data is remembered in the
browser between sessions (and you can **Clear data** anytime).

**Filter by:** date range (YTD / 30d / 90d / all), account, category, income vs
spending, amount range, and free-text search. **Export** any filtered view back
to CSV.

---

## Quick start — Claude-powered analysis

1. Drop your CSV exports into **`data/raw/`** (or just hand them to Claude).
2. Say: **"Use the Finance Analyzer to analyze these."**
3. Claude reads `APP_INSTRUCTIONS.md` and runs:
   ```bash
   python3 scripts/normalize.py       # raw CSVs -> data/normalized/transactions.json
   python3 scripts/analyze.py --save  # full report, also saved to reports/
   ```
4. You get an in-depth narrative: cash flow, where the money went, subscriptions,
   anomalies, trends, and specific observations on your real numbers.

Requires Python 3 (preinstalled on macOS). No `pip install` needed — stdlib only.

## The weekly report (automatic)

Every **Sunday 5:03pm** a launchd job runs `weekly.sh`: it ingests any fresh
bank exports sitting in `~/Downloads` (no renaming needed — files are
identified by content), rebuilds everything, writes an LLM-readable summary to
**`reports/weekly/latest.md`**, and pops a notification. Ask Claude *"explain
my weekly report"* — or drag `latest.md` into any chatbot; it explains its own
conventions. Run it anytime with `bash weekly.sh`. How to export CSVs from
Discover/Huntington (and the optional SimpleFIN auto-sync): see
**`CONNECT_ACCOUNTS.md`**.

## One command to refresh everything

After dropping new CSVs in `data/raw/`:
```bash
bash run.sh            # normalize → snapshot → save report
```

## Budgeting & planning tools

```bash
python3 scripts/safe_to_spend.py          # daily/weekly "safe to spend" + budget vs actual
python3 scripts/safe_to_spend.py --message-only   # the one-line morning message
python3 scripts/planning.py plan          # financial-plan analysis: plan vs reality + compare alt plans
python3 scripts/planning.py purchase --amount 7000 --what "Car"   # big-buy impact: cash, runway, rebuild
python3 scripts/planning.py subs          # subscription / recurring-charge auditor
python3 scripts/planning.py fuel          # what premium gas actually costs you
python3 scripts/planning.py commute       # Columbus: commute-from-home vs rent
python3 scripts/planning.py car           # car-replacement sinking-fund math
```

### Your personal config (git-ignored — real numbers never get committed)

```bash
cp config/budget.example.json config/budget.json          # your monthly budget/plans
cp config/local_profile.example.js config/local_profile.js # dashboard budget + net-worth numbers
```

- `config/budget.json` — your budget & plans (scripts fall back to the example
  until you create it). Supports envelope-style rollover: set
  `"rollover": true` and last month's discretionary surplus/overspend carries
  into this month's safe-to-spend pool (`"rollover_start": "YYYY-MM"` marks
  when you started budgeting so earlier months don't count). Add what-if
  scenarios under `"alt_plans"` (see the example file) — `planning.py plan`
  analyzes and compares them, `safe_to_spend.py --plan "<name>"` runs a day
  on one, and the dashboard's plan selector switches between them.
- `config/profile.json` — investment balances, loans, and an `owner_context`
  line used in weekly reports (create it by hand; see APP_INSTRUCTIONS.md).
- `config/local_profile.js` — the dashboard reads this for your real numbers;
  the tracked `dashboard.html` only ships generic starter values.
- `config/rules.json` — your own keyword→category rules (local merchants,
  favorite spots); checked before the built-in rules so they win ties. Copy
  `config/rules.example.json` to start.
- `config/overrides.json` — optional one-off categorize corrections
  (e.g. "that $5,000 withdrawal was a car purchase"); format documented in
  `scripts/categorize.py`.

All four are in `.gitignore`, so `git push` can never leak them. The dashboard
has the same budget, safe-to-spend banner, net-worth panel, and a plan switcher
built in.

---

## Tips for clean results

- **Name files with hints** so accounts & signs are detected correctly:
  - `huntington_checking_2026.csv`
  - `huntington_savings_2026.csv`
  - `chase_creditcard_2026.csv` (any card; the word *credit*/*card* matters)
- Re-running with new files is safe — duplicate transactions are removed
  automatically.
- Categorization is keyword-based. If something's mislabeled, see
  **Improving accuracy** in `APP_INSTRUCTIONS.md`.

## Layout

| Path | What it is |
|------|------------|
| `dashboard.html` | Self-contained interactive dashboard (open in browser) |
| `APP_INSTRUCTIONS.md` | The workflow Claude follows each time |
| `scripts/normalize.py` | CSV → normalized JSON (robust column detection) |
| `scripts/analyze.py` | Normalized JSON → in-depth report |
| `scripts/categorize.py` | Merchant→category rules (source of truth) |
| `data/raw/` | Put your CSV exports here |
| `data/normalized/` | Generated `transactions.json` |
| `reports/` | Saved analysis reports |
| `examples/` | A synthetic sample CSV to try things out (not analyzed) |

### Try it with the sample first
Drag `examples/sample_huntington_checking.csv` onto `dashboard.html`, or run:
```bash
python3 scripts/normalize.py examples/sample_huntington_checking.csv
python3 scripts/analyze.py
```

## Privacy

No network calls touch your transaction data. The dashboard stores data only in
your browser's local storage. `data/` and `reports/` are git-ignored so nothing
sensitive gets committed.
