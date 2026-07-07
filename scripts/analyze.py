#!/usr/bin/env python3
"""
analyze.py — In-depth, budget-oriented analysis over normalized transactions.

Reads data/normalized/transactions.json and prints a thorough report. Unlike a
naive analyzer, this one respects the `kind` field so internal money movement
(account transfers, credit-card payments, brokerage moves, P2P) is NEVER
counted as real income or spending.

Sections: cash flow • internal flows • monthly trend • recent run-rate (budget
basis) • spending by category & tier • fixed vs discretionary • top merchants •
recurring/subscriptions • largest expenses • anomalies • opaque spend (cash/P2P).

Usage:
    python3 scripts/analyze.py [--save] [--json path] [--months N]
"""

import argparse
import json
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JSON = os.path.join(REPO_ROOT, "data", "normalized", "transactions.json")
REPORTS_DIR = os.path.join(REPO_ROOT, "reports")

# Spending tiers — drives budgeting & cut recommendations.
TIER = {
    "Housing & Rent": "Fixed", "Utilities & Phone": "Fixed",
    "Insurance": "Fixed", "Education": "Fixed", "Taxes": "Fixed",
    "Fees & Interest": "Fixed",
    "Groceries": "Essential", "Gas & Fuel": "Essential",
    "Transport": "Essential", "Auto & Vehicle": "Essential",
    "Healthcare": "Essential",
    "Subscriptions & Software": "Discretionary", "Dining & Food": "Discretionary",
    "Entertainment": "Discretionary", "Shopping": "Discretionary",
    "Travel": "Discretionary", "Personal Care": "Discretionary",
    "Health & Fitness": "Discretionary", "Cash & ATM": "Discretionary",
    "Donations": "Discretionary", "Services": "Discretionary",
    "Home & Garden": "Discretionary", "Uncategorized": "Discretionary",
}


def money(x):
    return f"${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"


def month_of(d):
    return d[:7]


def merchant_key(desc):
    s = desc.upper()
    s = re.sub(r"\bPURCHASE\b", " ", s)
    s = re.sub(r"\b\d{2,}\b", "", s)
    s = re.sub(r"[*#].*$", "", s)
    s = re.sub(r"\s+(POS|DEBIT|CARD|ONLINE|RECURRING|AUTH)\b", " ", s)
    s = re.sub(r"[^A-Z& ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:30] or desc[:30]


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("transactions", []), data


def complete_months(tx):
    """Return sorted list of YYYY-MM that are 'complete' (exclude a partial
    final month, i.e. one whose max day < 28)."""
    months = sorted(set(month_of(t["date"]) for t in tx))
    if not months:
        return []
    last = months[-1]
    last_days = [int(t["date"][8:10]) for t in tx if month_of(t["date"]) == last]
    if last_days and max(last_days) < 28:
        return months[:-1]
    return months


def analyze(tx, recent_n=3):
    L = []
    w = L.append
    if not tx:
        return "No transactions."

    income = [t for t in tx if t["kind"] == "income"]
    spend = [t for t in tx if t["kind"] == "spend"]
    internal = [t for t in tx if t["kind"] == "internal"]

    total_in = sum(t["amount"] for t in income)
    total_out = -sum(t["amount"] for t in spend)   # net spend (refunds reduce)
    net = total_in - total_out
    dates = sorted(t["date"] for t in tx)
    start, end = dates[0], dates[-1]
    days = max(1, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1)
    n_months_all = len(set(month_of(t["date"]) for t in tx))

    w("=" * 72)
    w("FINANCIAL ANALYSIS REPORT")
    w("=" * 72)
    w(f"Period   : {start} -> {end}  ({days} days, {n_months_all} months)")
    w(f"Records  : {len(tx):,}  ({len(income)} income / {len(spend)} spend / "
      f"{len(internal)} internal)")
    accts = sorted(set(t["account"] for t in tx))
    w(f"Accounts : {', '.join(accts)}")

    # ---- Cash flow --------------------------------------------------------
    w("")
    w("CASH FLOW  (real money only — internal transfers excluded)")
    w("-" * 72)
    w(f"  Income (paychecks, interest, cashback, refunds) : {money(total_in):>14s}")
    w(f"  Spending (actual consumption)                   : {money(-total_out):>14s}")
    w(f"  Net saved                                       : {money(net):>14s}")
    if total_in:
        w(f"  Savings rate                                    : {net/total_in*100:>13.1f}%")
    w(f"  Avg spend / month (whole period)                : {money(total_out/max(1,n_months_all)):>14s}")

    # income composition
    inc_by = defaultdict(float)
    for t in income:
        inc_by[t["category"]] += t["amount"]
    w("  Income breakdown:")
    for c, v in sorted(inc_by.items(), key=lambda kv: -kv[1]):
        w(f"      {c:24s} {money(v):>14s}")

    # ---- Internal flows ---------------------------------------------------
    w("")
    w("INTERNAL FLOWS  (not income/spend — money you moved or paid off)")
    w("-" * 72)
    int_by = defaultdict(float)
    int_cnt = defaultdict(int)
    for t in internal:
        int_by[t["category"]] += t["amount"]
        int_cnt[t["category"]] += 1
    for c, v in sorted(int_by.items(), key=lambda kv: kv[1]):
        sign = "net out" if v < 0 else "net in "
        w(f"  {c:22s} {sign} {money(v):>14s}   ({int_cnt[c]} transactions)")
    w("  (Net P2P = Venmo/PayPal/Apple Cash/Zelle person-to-person flow;")
    w("   negative means you sent out more than you received.)")

    # ---- Monthly trend ----------------------------------------------------
    mi, mo = defaultdict(float), defaultdict(float)
    for t in income:
        mi[month_of(t["date"])] += t["amount"]
    for t in spend:
        mo[month_of(t["date"])] += -t["amount"]
    months = sorted(set(mi) | set(mo))
    w("")
    w("MONTHLY TREND")
    w("-" * 72)
    w(f"  {'Month':9s} {'Income':>12s} {'Spend':>12s} {'Net':>12s}")
    for m in months:
        w(f"  {m:9s} {money(mi[m]):>12s} {money(-mo[m]):>12s} {money(mi[m]-mo[m]):>12s}")

    # ---- Recent run-rate (budget basis) ----------------------------------
    cmonths = complete_months(tx)
    recent = cmonths[-recent_n:] if len(cmonths) >= recent_n else cmonths
    w("")
    w(f"RECENT RUN-RATE  (avg over last {len(recent)} complete months: "
      f"{', '.join(recent)})")
    w("-" * 72)
    if recent:
        r_in = sum(mi[m] for m in recent) / len(recent)
        r_out = sum(mo[m] for m in recent) / len(recent)
        w(f"  Avg monthly income : {money(r_in)}")
        w(f"  Avg monthly spend  : {money(r_out)}")
        w(f"  Avg monthly net    : {money(r_in - r_out)}")

    # ---- Spending by category (whole + recent avg) -----------------------
    cat_total = defaultdict(float)
    cat_cnt = defaultdict(int)
    cat_recent = defaultdict(float)
    for t in spend:
        cat_total[t["category"]] += -t["amount"]
        cat_cnt[t["category"]] += 1
        if month_of(t["date"]) in recent:
            cat_recent[t["category"]] += -t["amount"]
    w("")
    w("SPENDING BY CATEGORY")
    w("-" * 72)
    w(f"  {'Category':24s}{'Tier':13s}{'Total':>11s}{'%':>6s}{'#':>5s}{'~/mo now':>11s}")
    for cat, amt in sorted(cat_total.items(), key=lambda kv: -kv[1]):
        pct = amt / total_out * 100 if total_out else 0
        permo = cat_recent[cat] / len(recent) if recent else 0
        w(f"  {cat:24s}{TIER.get(cat,'?'):13s}{money(amt):>11s}{pct:>5.1f}%"
          f"{cat_cnt[cat]:>5d}{money(permo):>11s}")

    # ---- Fixed vs discretionary ------------------------------------------
    tier_recent = defaultdict(float)
    for cat, v in cat_recent.items():
        tier_recent[TIER.get(cat, "Discretionary")] += v
    w("")
    w(f"FIXED vs DISCRETIONARY  (avg / month over last {len(recent)} months)")
    w("-" * 72)
    tr_total = sum(tier_recent.values()) or 1
    for tier in ("Fixed", "Essential", "Discretionary"):
        v = tier_recent.get(tier, 0) / len(recent) if recent else 0
        share = (tier_recent.get(tier, 0) / tr_total * 100)
        w(f"  {tier:14s} {money(v):>12s} / mo   ({share:.0f}% of spend)")

    # ---- Top merchants ----------------------------------------------------
    mt, mc = defaultdict(float), defaultdict(int)
    for t in spend:
        k = merchant_key(t["description"])
        mt[k] += -t["amount"]
        mc[k] += 1
    w("")
    w("TOP 20 MERCHANTS BY SPEND")
    w("-" * 72)
    for k, amt in sorted(mt.items(), key=lambda kv: -kv[1])[:20]:
        w(f"  {k:32s} {money(amt):>11s}  ({mc[k]}x)")

    # ---- Recurring / subscriptions ---------------------------------------
    by_merch = defaultdict(list)
    for t in spend:
        by_merch[merchant_key(t["description"])].append(t)
    recurring = []
    for k, items in by_merch.items():
        mset = sorted(set(month_of(t["date"]) for t in items))
        if len(mset) >= 3 and len(items) <= round(len(mset) * 1.4):
            amts = [-t["amount"] for t in items]
            med = statistics.median(amts)
            if med <= 0:
                continue
            if (max(amts) - min(amts)) / med <= 0.25:
                recurring.append((k, med, len(mset), med * 12))
    w("")
    w("LIKELY RECURRING / SUBSCRIPTIONS  (~monthly, steady amount)")
    w("-" * 72)
    if recurring:
        w(f"  {'Merchant':30s}{'~Each':>10s}{'Months':>8s}{'~/yr':>12s}")
        annual = 0.0
        for k, med, n, yr in sorted(recurring, key=lambda r: -r[3]):
            annual += yr
            w(f"  {k:30s}{money(med):>10s}{n:>8d}{money(yr):>12s}")
        w(f"  Estimated recurring / year: {money(annual)}")
    else:
        w("  None detected.")

    # ---- Largest expenses -------------------------------------------------
    w("")
    w("15 LARGEST EXPENSES")
    w("-" * 72)
    for t in sorted(spend, key=lambda t: t["amount"])[:15]:
        w(f"  {t['date']}  {money(t['amount']):>11s}  {t['category']:18s} "
          f"{t['description'][:34]}")

    # ---- Anomalies --------------------------------------------------------
    cat_amts = defaultdict(list)
    for t in spend:
        cat_amts[t["category"]].append(-t["amount"])
    flags = []
    for t in spend:
        a = cat_amts[t["category"]]
        if len(a) < 6:
            continue
        med = statistics.median(a)
        if med > 0 and -t["amount"] > med * 5 and -t["amount"] > 100:
            flags.append((t, med))
    w("")
    w("ANOMALY FLAGS  (>5x that category's median)")
    w("-" * 72)
    if flags:
        for t, med in sorted(flags, key=lambda x: x[0]["amount"])[:12]:
            w(f"  {t['date']}  {money(t['amount']):>11s}  {t['category']:16s}"
              f" (median {money(med)})  {t['description'][:26]}")
    else:
        w("  None.")

    # ---- Opaque spend -----------------------------------------------------
    cash = -sum(t["amount"] for t in spend if t["category"] == "Cash & ATM")
    p2p_net = sum(t["amount"] for t in internal if t["category"] == "P2P Transfer")
    w("")
    w("OPAQUE / UNTRACKED MONEY")
    w("-" * 72)
    w(f"  Cash & ATM spending (purpose unknown) : {money(cash)}")
    w(f"  Net P2P (Venmo/PayPal/etc.)           : {money(p2p_net)}"
      "  (negative = net sent out)")

    w("")
    w("=" * 72)
    w("kind=spend is real consumption; kind=internal (transfers, card payments,")
    w("brokerage, P2P) is excluded from income/spend. Categorization is keyword")
    w("+ bank-category based — refine scripts/categorize.py to improve.")
    w("=" * 72)
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--months", type=int, default=3, help="run-rate window")
    args = ap.parse_args()
    if not os.path.exists(args.json):
        print(f"Not found: {args.json}\nRun: python3 scripts/normalize.py")
        return 1
    tx, _ = load(args.json)
    report = analyze(tx, recent_n=args.months)
    print(report)
    if args.save:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        p = os.path.join(REPORTS_DIR,
                         f"report_{datetime.now():%Y%m%d_%H%M%S}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("```\n" + report + "\n```\n")
        print(f"\nSaved -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
