#!/usr/bin/env python3
"""
weekly_report.py — generate the weekly LLM-queryable finance report.

Produces a self-contained markdown report covering the most recent week of
data: cash flow, every transaction, budget-vs-actual month-to-date, trend,
subscriptions, anomalies, and net worth. The header explains the data
conventions so the file can be pasted into (or read by) Claude or any other
LLM and queried directly — "why was my spending up?", "what should I cut?".

Usage
-----
    python3 scripts/weekly_report.py            # print + save
    python3 scripts/weekly_report.py --print    # print only, don't save

Output: reports/weekly/weekly_<end-date>.md  and  reports/weekly/latest.md
"""

import json
import os
import re
import shutil
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORM_FILE = os.path.join(REPO, "data", "normalized", "transactions.json")
BUDGET_FILE = os.path.join(REPO, "config", "budget.json")
if not os.path.exists(BUDGET_FILE):  # fresh clone — fall back to the example
    BUDGET_FILE = os.path.join(REPO, "config", "budget.example.json")
PROFILE_FILE = os.path.join(REPO, "config", "profile.json")
OUT_DIR = os.path.join(REPO, "reports", "weekly")
MAX_LISTED_TX = 90


def money(x):
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def merchant_key(desc):
    s = re.sub(r"[#*]\S*", "", desc.upper())
    s = re.sub(r"\d{3,}", "", s)
    return re.sub(r"\s+", " ", s).strip()[:28]


def iso(d):
    return d.strftime("%Y-%m-%d")


def build(tx, budget, profile, today):
    L = []
    w = L.append

    dates = sorted(t["date"] for t in tx)
    data_end = datetime.strptime(dates[-1], "%Y-%m-%d").date()
    wk_start = data_end - timedelta(days=6)
    prev_start, prev_end = wk_start - timedelta(days=7), wk_start - timedelta(days=1)

    def in_range(t, a, b):
        return iso(a) <= t["date"] <= iso(b)

    week = [t for t in tx if in_range(t, wk_start, data_end)]
    prev = [t for t in tx if in_range(t, prev_start, prev_end)]
    wk_spend = [t for t in week if t["kind"] == "spend"]
    wk_income = [t for t in week if t["kind"] == "income"]
    wk_internal = [t for t in week if t["kind"] == "internal"]

    # ---- Header + conventions (the part an LLM needs) ----------------------
    w(f"# Weekly Finance Report — {iso(wk_start)} to {iso(data_end)}")
    w("")
    owner_ctx = profile.get("owner_context") or (
        "(add an 'owner_context' line to config/profile.json with your "
        "situation — job, rent, goals — so LLM summaries have context)")
    w(f"*Generated {iso(today)} by FinanceAnalyzer (local, private). "
      f"Owner: {owner_ctx}*")
    w("")
    w("> **Conventions (read first if you're an LLM):** amounts > 0 are money "
      "in, < 0 are money out. Every transaction has `kind`: **income** (real "
      "money in), **spend** (real consumption), or **internal** (transfers "
      "between the owner's own accounts, credit-card payments, brokerage moves, "
      "P2P) — internal is *excluded* from all income/spend/net math so "
      "nothing is double-counted. Accounts: e.g. Huntington Checking / "
      "Savings (bank) and a credit card (purchases already "
      "normalized to negative). Categories are keyword-based and imperfect. "
      "When answering questions, use the numbers in this report; flag any "
      "section marked ⚠ stale as possibly incomplete.")
    w("")

    # ---- Freshness ----------------------------------------------------------
    last_by_acct = {}
    for t in tx:
        last_by_acct[t["account"]] = max(last_by_acct.get(t["account"], ""), t["date"])
    stale = []
    w("## Data freshness")
    w("")
    w("| Account | Data through | Age |")
    w("|---|---|---|")
    for acct in sorted(last_by_acct):
        age = (today - datetime.strptime(last_by_acct[acct], "%Y-%m-%d").date()).days
        flag = " ⚠ stale" if age > 10 else ""
        if age > 10:
            stale.append(acct)
        w(f"| {acct} | {last_by_acct[acct]} | {age}d{flag} |")
    w("")
    if stale:
        w(f"⚠ **{len(stale)} account(s) stale** — recent totals below are "
          f"incomplete until fresh exports are ingested (download new CSVs, "
          f"then run `python3 scripts/refresh.py`).")
        w("")

    # ---- This week ----------------------------------------------------------
    tot_in = sum(t["amount"] for t in wk_income)
    tot_out = sum(t["amount"] for t in wk_spend)          # negative
    prev_out = sum(t["amount"] for t in prev if t["kind"] == "spend")
    w(f"## This week ({iso(wk_start)} – {iso(data_end)})")
    w("")
    w(f"- **Income:** {money(tot_in)}   **Spend:** {money(tot_out)}   "
      f"**Net:** {money(tot_in + tot_out)}")
    delta = -tot_out - (-prev_out)
    w(f"- vs previous week ({iso(prev_start)} – {iso(prev_end)}): spend was "
      f"{money(-prev_out)} → {'up' if delta > 0 else 'down'} "
      f"{money(abs(delta))}")
    if wk_internal:
        moved = sum(t["amount"] for t in wk_internal)
        w(f"- Internal moves (excluded above): {len(wk_internal)} transactions, "
          f"net {money(moved)}")
    w("")

    by_cat = defaultdict(float)
    for t in wk_spend:
        by_cat[t["category"]] += -t["amount"]
    if by_cat:
        w("**Spend by category this week:**")
        w("")
        w("| Category | Spent |")
        w("|---|---|")
        for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            w(f"| {c} | {money(v)} |")
        w("")

    listed = sorted(wk_spend + wk_income, key=lambda t: (t["date"], t["amount"]))
    w(f"**All transactions this week ({len(listed)}):**")
    w("")
    w("| Date | Amount | Category | Description | Account |")
    w("|---|---|---|---|---|")
    shown = listed if len(listed) <= MAX_LISTED_TX else \
        sorted(listed, key=lambda t: abs(t["amount"]), reverse=True)[:MAX_LISTED_TX]
    for t in sorted(shown, key=lambda t: t["date"]):
        w(f"| {t['date']} | {money(t['amount'])} | {t['category']} | "
          f"{t['description'][:48]} | {t['account'].replace('Huntington ', 'H.')} |")
    if len(listed) > MAX_LISTED_TX:
        w(f"| … | | | *({len(listed) - MAX_LISTED_TX} smaller rows omitted)* | |")
    w("")

    # ---- Month to date vs budget -------------------------------------------
    plan = budget.get("active_plan", "")
    cat_budgets = dict(budget.get("category_budgets", {}))
    month = iso(today)[:7]
    mtd = [t for t in tx if t["date"][:7] == month and t["kind"] == "spend"]
    mtd_by = defaultdict(float)
    for t in mtd:
        mtd_by[t["category"]] += -t["amount"]
    days_in = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][today.month - 1]
    frac = today.day / days_in
    w(f"## Month to date — {month} (day {today.day}/{days_in}, "
      f"plan: {plan})")
    w("")
    mtd_note = ""
    if last_by_acct and max(last_by_acct.values()) < iso(today - timedelta(days=3)):
        mtd_note = " ⚠ data lags — actual spend is likely higher"
    w(f"Total spent so far: **{money(sum(mtd_by.values()))}** of "
      f"{money(sum(cat_budgets.values()))} budgeted{mtd_note}")
    w("")
    w("| Category | Budget | Spent | Left | Pace |")
    w("|---|---|---|---|---|")
    for c, b in sorted(cat_budgets.items(), key=lambda kv: -kv[1]):
        s = mtd_by.pop(c, 0.0)
        pace = "🔴 over" if s > b else ("🟡 hot" if s > b * max(frac, 0.15) else "🟢 ok")
        w(f"| {c} | {money(b)} | {money(s)} | {money(b - s)} | {pace} |")
    for c, s in sorted(mtd_by.items(), key=lambda kv: -kv[1]):
        w(f"| {c} *(unbudgeted)* | — | {money(s)} | — | ⚪ |")
    w("")

    # ---- Trend --------------------------------------------------------------
    mi, mo = defaultdict(float), defaultdict(float)
    for t in tx:
        m = t["date"][:7]
        if t["kind"] == "income":
            mi[m] += t["amount"]
        elif t["kind"] == "spend":
            mo[m] += -t["amount"]
    months = sorted(set(mi) | set(mo))[-6:]
    w("## Six-month trend")
    w("")
    w("| Month | Income | Spend | Net |")
    w("|---|---|---|---|")
    for m in months:
        w(f"| {m} | {money(mi[m])} | {money(-mo[m])} | {money(mi[m] - mo[m])} |")
    # a month only counts as complete if the data actually covers past it
    complete = [m for m in sorted(set(mi) | set(mo)) if m < iso(data_end)[:7]][-3:]
    if complete:
        ai = sum(mi[m] for m in complete) / len(complete)
        ao = sum(mo[m] for m in complete) / len(complete)
        w("")
        w(f"3-month run-rate (complete months {', '.join(complete)}): income "
          f"{money(ai)}/mo, spend {money(-ao)}/mo, net {money(ai - ao)}/mo")
    w("")

    # ---- Recurring ----------------------------------------------------------
    by_merch = defaultdict(list)
    for t in tx:
        if t["kind"] == "spend":
            by_merch[merchant_key(t["description"])].append(t)
    w("## Recurring / subscriptions")
    w("")
    rows = []
    for mk, ts in by_merch.items():
        mset = sorted(set(t["date"][:7] for t in ts))
        if len(mset) < 3:
            continue
        amts = [-t["amount"] for t in ts]
        med = statistics.median(amts)
        if med <= 0 or (max(amts) - min(amts)) > max(3.0, med * 0.35):
            continue
        last_seen = max(t["date"] for t in ts)
        # judge "still active" against the newest data we have, not today —
        # otherwise stale exports make every subscription look lapsed
        active = last_seen >= iso(data_end - timedelta(days=45))
        rows.append((med * 12, mk, med, len(mset), last_seen, active))
    if rows:
        w("| Merchant | ~Each | Months seen | Last seen | ~/yr |")
        w("|---|---|---|---|---|")
        for yr, mk, med, nm, last_seen, active in sorted(rows, reverse=True):
            note = "" if active else " *(maybe lapsed)*"
            w(f"| {mk}{note} | {money(med)} | {nm} | {last_seen} | {money(yr)} |")
        est = sum(r[0] for r in rows if r[5])
        w("")
        w(f"Estimated active recurring: **{money(est)}/yr**")
    else:
        w("*None detected.*")
    w("")

    # ---- Flags --------------------------------------------------------------
    w("## Flags")
    w("")
    flags = []
    med_by_cat = {}
    for c in set(t["category"] for t in tx if t["kind"] == "spend"):
        vals = [-t["amount"] for t in tx if t["kind"] == "spend" and t["category"] == c]
        if len(vals) >= 5:
            med_by_cat[c] = statistics.median(vals)
    for t in wk_spend:
        m = med_by_cat.get(t["category"])
        if m and -t["amount"] > 4 * m and -t["amount"] > 75:
            flags.append(f"Large for its category: {t['date']} "
                         f"{money(t['amount'])} — {t['description'][:50]} "
                         f"(median {t['category']} is {money(-m)})")
    seen_before = set(merchant_key(t["description"]) for t in tx
                      if t["kind"] == "spend" and t["date"] < iso(wk_start))
    new_merch = sorted(set(merchant_key(t["description"]) for t in wk_spend)
                       - seen_before)
    if new_merch:
        flags.append("First-time merchants this week (verify you recognize "
                     "them): " + ", ".join(new_merch[:10]))
    counts = defaultdict(list)
    for t in wk_spend:
        counts[(t["date"], t["amount"], merchant_key(t["description"]))].append(t)
    for (d, a, mk), ts in counts.items():
        if len(ts) > 1:
            flags.append(f"Possible duplicate charge: {len(ts)}× {money(a)} "
                         f"at {mk} on {d}")
    for f in flags:
        w(f"- ⚠ {f}")
    if not flags:
        w("*Nothing unusual this week.*")
    w("")

    # ---- Net worth & goals --------------------------------------------------
    if profile:
        inv = profile.get("investments", {})
        loans = profile.get("loans", [])
        inv_t = sum(v for v in inv.values() if isinstance(v, (int, float)))
        loan_t = sum(l.get("balance", 0) for l in loans)
        w(f"## Net worth & goals (profile as of {profile.get('as_of', '?')})")
        w("")
        w(f"- Invested {money(inv_t)} ({', '.join(f'{k} {money(v)}' for k, v in inv.items())})")
        w(f"- Student loans {money(-loan_t)} — subsidized, 0% while in school, "
          f"repayment ~{loans[0].get('repayment_begins', '?') if loans else '?'}")
        w(f"- **Net worth (excl. bank cash): {money(inv_t - loan_t)}**")
        for g in profile.get("goals", []):
            pct = 100 * g["current"] / g["target"] if g.get("target") else 0
            w(f"- Goal — {g['name']}: {money(g['current'])} / "
              f"{money(g['target'])} ({pct:.0f}%)")
        w("")

    # ---- Prompts ------------------------------------------------------------
    w("## Questions worth asking (paste this file into Claude and ask)")
    w("")
    w("- What changed vs last week, and is any of it a problem?")
    w("- Am I on pace for my monthly budget? Which category should I watch?")
    w("- Is my summer savings goal ($1,900/mo while the internship pays "
      "~$3,400/mo) on track based on the actual deposits above?")
    w("- Any charges here that look like mistakes, duplicates, or fraud?")
    w("- What single change would save me the most next month?")
    w("")
    return "\n".join(L)


def main(argv):
    tx = load_json(NORM_FILE, {}).get("transactions")
    if not tx:
        print("No normalized data — run scripts/refresh.py first.")
        return 1
    budget = load_json(BUDGET_FILE, {})
    profile = load_json(PROFILE_FILE, {})
    today = datetime.now().date()
    report = build(tx, budget, profile, today)

    if "--print" in argv:
        print(report)
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    dates = sorted(t["date"] for t in tx)
    out = os.path.join(OUT_DIR, f"weekly_{dates[-1]}.md")
    with open(out, "w") as f:
        f.write(report + "\n")
    shutil.copyfile(out, os.path.join(OUT_DIR, "latest.md"))
    print(report)
    print(f"\nSaved: {out}\n       (also reports/weekly/latest.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
