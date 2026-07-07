# Finance Analyzer — Build Roadmap & Progress

Living doc tracking the iterative development (the `/loop`). Newest insights at top.

## ✅ Done (2026-07-07 — "connect accounts" + weekly report)
- **scripts/refresh.py** — auto-ingests new Discover/Huntington exports from
  `~/Downloads` (identifies by header signature; disambiguates Huntington
  accounts by row-overlap vs history; content-hash ledger; idempotent),
  then normalizes + prints per-account data freshness.
- **scripts/weekly_report.py** — self-contained, LLM-queryable weekly markdown
  → `reports/weekly/latest.md` + dated archive. Covers freshness, week's
  transactions, budget MTD, 6-mo trend, subs, anomaly/new-merchant/duplicate
  flags, net worth/goals, suggested questions.
- **weekly.sh + launchd** (`com.user.finance.weekly`, Sun 5:03pm) — sync →
  report → desktop notification. Logs: /tmp/finance_weekly.log.
- **scripts/simplefin_sync.py** — optional true auto-sync via SimpleFIN Bridge
  (opt-in, ~$1.50/mo). Writes Money In/Out CSVs so signs survive normalize.
- **CONNECT_ACCOUNTS.md** — the two connection paths + LLM-query instructions.
- normalize.py + dashboard: explicit `hub` filename handling so datestamped
  refreshes land in the same account.

## ✅ Done
- **Robust ingestion** of real exports: Huntington (checking/hub/savings, with
  bank `Category` column) + Discover credit card (auto sign-flip). 4 files,
  2,050 tx, 99.7% categorized.
- **Classifier v2** (`scripts/categorize.py`): bank-category mapping + keyword
  rules + INTERNAL detection. `kind` = income / spend / internal so transfers,
  credit-card payments, brokerage moves, and P2P are excluded from cash flow.
  Sign-driven: money in = income, money out = spend.
- **Analysis v2** (`scripts/analyze.py`): cash flow, internal flows, monthly
  trend, recent run-rate, category+tier, fixed/discretionary, merchants,
  recurring, anomalies, opaque (cash/P2P).
- **Budget plan delivered** (chat + this repo): summer / rest-of-2026 / move-out
  Columbus / car fund / loan strategy / cuts.
- **Safe-to-spend engine** (`scripts/safe_to_spend.py` + `config/budget.json`):
  daily/weekly number, budget-vs-actual, morning message (`--message-only`).
- **Profile/config** (`config/profile.json`): investments + loans for net worth.

## ✅ Done (cont.)
- **Dashboard synced with classifier v2** — verified byte-for-byte equal to the
  Python pipeline on real data (~2k transactions).
- **Dashboard UI**: safe-to-spend banner (daily/weekly), budget-vs-actual,
  net-worth panel, and a plan switcher for alt budget plans. Verified.
- **planning.py**: `fuel` (what premium gas costs vs regular), `commute`
  (commute-from-home vs renting near work, dollars AND hours), `car`
  (replacement sinking fund).

## ✅ Done (cont.)
- **planning.py subs** — subscription auditor with last-seen + stale flag.
- **planning.py loans** — payoff simulator (months + total interest per plan).
- **planning.py savings** — net-trend bars + emergency-fund runway.
- **Dashboard goal progress bars** (emergency fund, car fund, Roth) from
  profile.json. Full pipeline consistency-checked (6 scripts + JS + configs).
- Docs: README + APP_INSTRUCTIONS quick-refs updated for all tools.

## ✅ Done (cont.)
- **summary.py** — one-screen snapshot (net worth, run-rate, top spend, goals,
  auto action items).
- **Dashboard what-if cut projector** — sliders for discretionary cats →
  projected $/mo + $/yr saved from trimming a category.
- **Morning message** — `scripts/morning.sh` (+ macOS notification) and
  `MORNING_MESSAGE.md` with phone-notify options (Pushover/email-SMS/Twilio)
  and a launchd plist to run it daily at 8am. (The "future feature" you flagged.)
- **Housekeeping** — sensitive source docs moved to `data/statements/`
  (git-ignored); `config/profile.json` git-ignored; full QA passes.

## 🔜 Backlog (nice-to-haves, lower priority)
1. Savings-rate trend chart in the dashboard (CLI version exists in `savings`).
2. Income-volatility smoothing (weekly pay is lumpy).
3. Auto-refresh: a single `make`-style command to re-run the whole pipeline.
4. Multi-currency / new-bank format support if accounts change.

## 💡 Ideas / research backlog (useful info to add)
- **Premium-gas tracker**: quantify the extra $/mo premium gas costs vs regular,
  and project car-replacement break-even.
- **Commute-vs-rent calculator** for a move-near-work decision (gas+hotel+wear vs
  rent), parameterized by office days/week.
- **Savings-rate trend** chart and a "months of expenses saved" runway metric.
- **Subscription auditor**: list every recurring charge with last-seen date so
  forgotten subs surface.
- **Income volatility view**: weekly pay is lumpy — show a smoothed income line.
- **"What-if" sliders**: cut dining/shopping by X% → projected annual savings.
- **Tax setup note**: internship is W-2; flag if withholding looks off.
- **Loan payoff simulator**: when interest starts (late 2027), show payoff time
  at different monthly payments vs investing the difference.
- **Goal tracker**: emergency fund (3–6 mo) + car fund progress bars.
