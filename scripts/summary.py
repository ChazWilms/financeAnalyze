#!/usr/bin/env python3
"""
summary.py — one-screen financial snapshot.

Pulls together the whole picture in a single command: net worth, recent
run-rate, this month's budget status, top spend, goals, loans, and a few
auto-generated action items. Think of it as the terminal version of the
dashboard's top section — the thing to glance at weekly.

    python3 scripts/summary.py
"""

import json
import os
from collections import defaultdict
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TX = os.path.join(REPO, "data", "normalized", "transactions.json")
BUDGET = os.path.join(REPO, "config", "budget.json")
if not os.path.exists(BUDGET):  # fresh clone — fall back to the example
    BUDGET = os.path.join(REPO, "config", "budget.example.json")
PROFILE = os.path.join(REPO, "config", "profile.json")


def money(x):
    return f"${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"


def load(p, default=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def recent_months(tx, n=3):
    sp, inc = defaultdict(float), defaultdict(float)
    for t in tx:
        ym = t["date"][:7]
        if t["kind"] == "spend":
            sp[ym] += -t["amount"]
        elif t["kind"] == "income":
            inc[ym] += t["amount"]
    months = sorted(set(sp) | set(inc))
    if months:
        last = months[-1]
        maxd = max(int(t["date"][8:10]) for t in tx if t["date"][:7] == last)
        if maxd < 28:
            months = months[:-1]
    rec = months[-n:]
    return sp, inc, rec


def main():
    data = load(TX)
    if not data:
        print("Run scripts/normalize.py first.")
        return 1
    tx = data["transactions"]
    budget = load(BUDGET, {})
    profile = load(PROFILE, {})

    sp, inc, rec = recent_months(tx, 3)
    avg_sp = sum(sp[m] for m in rec) / len(rec) if rec else 0
    avg_in = sum(inc[m] for m in rec) / len(rec) if rec else 0

    inv = profile.get("investments", {}) or {}
    inv_total = sum(inv.values())
    loans = profile.get("loans", [])
    loan_total = sum(l["balance"] for l in loans)
    net_worth = inv_total - loan_total

    W = 60
    print("╔" + "═" * W + "╗")
    print("║" + "  FINANCIAL SNAPSHOT".ljust(W) + "║")
    print("║" + f"  as of {date.today()}  ·  {len(tx):,} transactions".ljust(W) + "║")
    print("╚" + "═" * W + "╝")

    print(f"\n  NET WORTH: {money(net_worth)}")
    print(f"    Invested {money(inv_total)}  −  Loans {money(loan_total)}"
          " (0% subsidized)")

    print(f"\n  RECENT RUN-RATE (last {len(rec)} mo: {', '.join(rec)})")
    print(f"    Income {money(avg_in)}/mo  ·  Spend {money(avg_sp)}/mo  ·  "
          f"Net {money(avg_in - avg_sp)}/mo")

    # top categories recent
    cat = defaultdict(float)
    for t in tx:
        if t["kind"] == "spend" and t["date"][:7] in rec:
            cat[t["category"]] += -t["amount"]
    print("\n  TOP SPEND (recent /mo):")
    for c, v in sorted(cat.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {c:24s} {money(v/len(rec))}/mo")

    # goals
    goals = profile.get("goals", [])
    if goals:
        print("\n  GOALS:")
        for g in goals:
            pct = g["current"] / g["target"] * 100 if g["target"] else 0
            filled = min(20, int(pct / 5))
            bar = "█" * filled + "░" * (20 - filled)
            print(f"    {g['name']:24s} {bar} {pct:>3.0f}%  "
                  f"{money(g['current'])}/{money(g['target'])}")

    # action items (auto)
    print("\n  ACTION ITEMS:")
    items = []
    plan_inc = budget.get("monthly_income_estimate")
    if avg_in - avg_sp < 0:
        items.append(f"You're net −{money(avg_sp - avg_in)}/mo lately. Summer "
                     "internship income should flip this — lock in savings now.")
    cats_b = budget.get("category_budgets", {})
    for c in ("Dining & Food", "Shopping"):
        if cat.get(c, 0) / max(1, len(rec)) > cats_b.get(c, 1e9):
            items.append(f"{c} is over budget ({money(cat[c]/len(rec))}/mo vs "
                         f"{money(cats_b[c])} target) — top cut opportunity.")
    if loan_total and all(l.get("subsidized") for l in loans):
        items.append(f"Loans are 0% (subsidized) until ~2027 — don't prepay; "
                     "invest instead, then pay them off fast once interest starts.")
    if not items:
        items.append("On track — keep it up.")
    for i, it in enumerate(items, 1):
        print(f"    {i}. {it}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
