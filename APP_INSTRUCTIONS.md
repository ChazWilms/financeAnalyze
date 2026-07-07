# APP INSTRUCTIONS — Finance Analyzer (read this first)

> **For the AI assistant (Claude, Gemini, etc.):** When the user says something like *"use the Finance Analyzer,"*
> *"analyze my transactions,"* or drops files into this repo, READ THIS FILE
> FIRST, then follow the workflow below exactly. This file is the contract for
> how this app behaves every time.

---

## What this app is

A reusable, privacy-first personal-finance analyzer for **Huntington Bank / Capital One / most banks'**
(checking/savings) and **credit card** transaction exports. It has two halves
that share the same logic:

1. **Python pipeline** (`scripts/`) — for the deep, written analysis Claude
   produces in chat. stdlib-only, no installs needed.
2. **`dashboard.html`** — a self-contained browser dashboard the user opens himself
   to filter/explore visually. 100% client-side; no data leaves the machine.

Both use the **same category rules** (`scripts/categorize.py` ⇄ the rules block
in `dashboard.html`) and the **same sign convention** so they never disagree.

**Sign convention (critical):** after normalization,
`amount > 0` = money IN, `amount < 0` = money OUT. Credit-card exports list
purchases as positive, so the pipeline auto-flips them — purchases end up
negative, just like bank debits.

---

## Where files go

```
FinanceAnalyzer/
├── APP_INSTRUCTIONS.md          ← you are here
├── README.md                    ← human-facing quickstart
├── dashboard.html               ← the user opens this in a browser
├── data/
│   ├── raw/                     ← the user drops his CSV exports HERE
│   └── normalized/              ← pipeline writes transactions.json HERE
├── scripts/
│   ├── categorize.py            ← classifier: category + kind (income/spend/internal)
│   ├── normalize.py             ← CSV → normalized JSON (uses bank Category col)
│   ├── analyze.py               ← normalized JSON → in-depth written report
│   └── safe_to_spend.py         ← daily/weekly "safe to spend" + budget vs actual
├── config/
│   ├── budget.example.json      ← tracked template; copy to budget.json
│   ├── budget.json              ← active monthly budget + plans (git-ignored)
│   ├── profile.json             ← investments + loans + owner_context (git-ignored)
│   ├── local_profile.example.js ← tracked template; copy to local_profile.js
│   ├── local_profile.js         ← dashboard's real budget/profile (git-ignored)
│   ├── rules.json               ← personal keyword→category rules (git-ignored)
│   └── overrides.json           ← one-off categorize corrections (git-ignored)
├── examples/                    ← synthetic sample CSV for testing (NOT scanned)
└── reports/                     ← saved markdown reports land here
```

## Key concept: the `kind` field
Every transaction is tagged `kind` = **income** (money in) | **spend** (money
out you consume) | **internal** (transfers between the user's own accounts, credit
-card payments, brokerage/Schwab moves, P2P Venmo/PayPal/Apple Cash). **Internal
is excluded from all income/spend/cash-flow math** — this is what keeps totals
from double-counting (e.g. a Discover purchase AND the checking payment that
pays it off). Money-in = income, money-out = spend, after internal is removed.

## Non-CSV data the user may drop (loans, investments)
- **NSLDS `MyStudentData.txt`** (federal student loans): parse loan balances,
  rates, repayment dates → update `config/profile.json` `loans`.
- **Schwab balance letters / brokerage PDFs**: read balances → update
  `config/profile.json` `investments`.
These aren't transactions; they feed the **net-worth** and **debt-strategy**
views. Update profile.json, don't try to normalize them as CSVs. Source docs
live in `data/statements/` (git-ignored, sensitive).

If the user drops files somewhere else (Desktop, a message, etc.), **move/copy them
into `data/raw/` first**, then proceed.

---

## THE WORKFLOW (do this every time)

### 1. Locate the new transaction files
- Look in `data/raw/` for `*.csv`. If the user pasted a path or dropped files
  elsewhere, copy them into `data/raw/` first.
- These exports vary by bank. The normalizer auto-detects columns
  (date / description / amount, or separate debit & credit columns) and the
  account type. **Filename hints help** — prefer names like
  `huntington_checking_2026.csv`, `huntington_savings_2026.csv`,
  `chase_creditcard_2026.csv`. If a file is a credit card but the name doesn't
  say so, rename it (or tell me) so purchases get the right sign.

### 2. Normalize
```bash
cd ~/Desktop/FinanceAnalyzer
python3 scripts/normalize.py
```
This scans `data/raw/`, parses + categorizes + de-dupes everything, and writes
`data/normalized/transactions.json`. Sanity-check the per-file transaction
counts it prints. If any file parsed to 0 rows, open it, inspect the header, and
add the missing header alias to `normalize.py` (`*_HEADERS` lists).

### 3. Run the deep analysis
```bash
python3 scripts/analyze.py --save
```
This prints a full report and saves a timestamped copy to `reports/`. It covers:
cash flow, monthly breakdown, spending by category, per-account totals, top
merchants (by spend & frequency), largest expenses, **recurring/subscription
detection**, and **anomaly flags**.

### 4. Present results to the user (this is the important part)
Don't just dump the script output. **Synthesize it** into a clear, in-depth
narrative in chat. Always include, at minimum:
- **Headline cash flow** for the period (in / out / net / savings rate).
- **Where the money went** — top categories with % of spend, called out plainly.
- **Recurring charges & subscriptions** — list them with monthly + annualized
  cost, and flag anything that looks forgotten/unused or that increased.
- **Notable / anomalous transactions** — large one-offs, duplicates, fees.
- **Trends** — month-over-month direction (spend rising? which categories?).
- **Concrete, specific observations** tailored to the user's actual data — not
  generic advice. Tie suggestions to real numbers ("Dining is $X/mo, ~Y% of
  spend"). Be honest and direct.
- If data spans only part of the period, say so and note projections are naive.

Keep the tone factual and useful. Use tables where they aid scanning.

### 5. Point the user to the dashboard for interactive filtering
Remind him he can open `dashboard.html` in a browser and **drag the same CSVs
(or `data/normalized/transactions.json`) onto it** to filter by date, account,
category, amount, and search — all the slicing he wants, visually.

---

## THE WEEKLY REPORT (added 2026-07-07)

A launchd job (`~/Library/LaunchAgents/com.user.finance.weekly.plist`) runs
`weekly.sh` **every Sunday 5:03pm**: it ingests any new bank exports from
`~/Downloads` (via `scripts/refresh.py` — identifies files by content, no
renaming needed), optionally pulls SimpleFIN if configured
(`scripts/simplefin_sync.py`), and writes an LLM-queryable report to
`reports/weekly/latest.md` (+ a dated archive copy), then pops a notification.

**When the user says "explain my weekly report," "weekly report," or asks
questions about his week's finances:** read `reports/weekly/latest.md`
first, answer from it, and dig into `data/normalized/transactions.json` for
anything deeper. If the freshness table shows accounts >10 days stale, tell
him to download fresh CSVs (they can just land in Downloads) and run
`python3 scripts/refresh.py` or `bash weekly.sh`.

How the accounts "connect" (both paths wired; see `CONNECT_ACCOUNTS.md`):
- **Default:** the user downloads CSVs from discover.com / huntington.com into
  `~/Downloads`; `refresh.py` auto-detects, canonically names, de-dupes,
  normalizes. Content-hash ledger at `data/raw/.ingested.json`.
- **Optional:** SimpleFIN Bridge auto-sync (~$1.50/mo, third-party
  aggregator — his explicit opt-in required since data transits their
  servers). Setup steps in `scripts/simplefin_sync.py` header.

---

## Improving accuracy over time

- **Miscategorized merchants?** Add a rule to `config/rules.json` (git-ignored;
  copy `config/rules.example.json`) and mirror it as `window.LOCAL_RULES` in
  `config/local_profile.js` — user rules are checked before the built-ins, so
  they win ties. Re-run `normalize.py` + `analyze.py`. Only edit the tracked
  `CATEGORY_RULES` (in `scripts/categorize.py` + `dashboard.html`, kept in
  sync) for genuinely universal merchants everyone would want.
- **One transaction wrong** (not a merchant pattern)? Use `config/overrides.json`
  (+ `window.LOCAL_OVERRIDES` in local_profile.js for the dashboard).
- **A new bank/card format won't parse?** Add its header names to the
  `*_HEADERS` alias lists in `normalize.py` (and the matching consts in
  `dashboard.html`). Add a new date format to `DATE_FORMATS` if needed.
- **Account sign looks inverted** (income shown as spend or vice-versa)? Check
  the credit-card detection in `guess_account()` — fix via filename hint or the
  `is_credit` logic.

## Guardrails
- **Never upload or transmit** the user's financial data anywhere. Everything stays
  local. No external API calls with transaction contents.
- `data/raw/` and `data/normalized/` may contain sensitive data — they're
  git-ignored. Don't commit them.
- **Never put real numbers or personal details in tracked files**
  (`dashboard.html`, `*.example.*`, scripts, docs). Personal data lives only
  in the git-ignored config files: `config/budget.json`, `config/profile.json`,
  `config/local_profile.js`, `config/overrides.json`. Before committing, run
  `git diff --cached` and check nothing personal slipped in.
- If asked to compare to a prior period, look in `reports/` for older reports.
- If something in the data looks like fraud (unknown merchant, odd location,
  duplicate charge), **call it out explicitly**.

## Quick reference
```bash
cd ~/Desktop/FinanceAnalyzer
bash weekly.sh                        # the whole weekly refresh + report + notify
python3 scripts/refresh.py            # find new exports in ~/Downloads + normalize
python3 scripts/weekly_report.py      # regenerate reports/weekly/latest.md
python3 scripts/simplefin_sync.py     # optional auto-sync (see CONNECT_ACCOUNTS.md)
python3 scripts/normalize.py          # data/raw/*.csv  -> normalized JSON
python3 scripts/analyze.py --save     # JSON -> report (printed + saved)
python3 scripts/safe_to_spend.py      # daily/weekly safe-to-spend + budget vs actual
python3 scripts/safe_to_spend.py --message-only   # the morning text line
python3 scripts/planning.py subs      # subscription / recurring auditor
python3 scripts/planning.py loans     # student-loan payoff simulator
python3 scripts/planning.py savings   # savings-rate trend + emergency-fund runway
python3 scripts/planning.py fuel      # premium-gas cost analysis
python3 scripts/planning.py commute   # Columbus commute-from-home vs rent
python3 scripts/planning.py car       # car-replacement sinking fund
python3 scripts/categorize.py         # smoke-test the classifier
open dashboard.html                   # interactive UI (or just double-click it)

# Want to demo/test without touching real data? Use the synthetic sample:
python3 scripts/normalize.py examples/sample_huntington_checking.csv
python3 scripts/analyze.py
```
