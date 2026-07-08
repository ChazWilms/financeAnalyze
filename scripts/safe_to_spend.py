#!/usr/bin/env python3
"""
safe_to_spend.py — "How much can I spend today / this week?"

This is the engine behind the morning/weekly message you asked for. It reads
your budget (config/budget.json) and your normalized transactions, looks at how
much you've ALREADY spent this month in your day-to-day discretionary
categories, and divides what's left over the days remaining in the month.

Output:
  * A short "morning message" (the thing that would eventually be texted to you).
  * A weekly number.
  * A full budget-vs-actual table for the current month.

Usage:
    python3 scripts/safe_to_spend.py            # uses today's date
    python3 scripts/safe_to_spend.py --date 2026-06-15   # pretend it's that day
    python3 scripts/safe_to_spend.py --plan "Some Alt Plan"
    python3 scripts/safe_to_spend.py --message-only      # just the morning line

The "future feature" (texting your phone) only needs to take the --message-only
string and hand it to a notifier (Twilio, Pushover, email-to-SMS, etc.). The
math lives here so that part stays trivial.
"""

import argparse
import calendar
import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TX_JSON = os.path.join(REPO, "data", "normalized", "transactions.json")
PENDING_JSON = os.path.join(REPO, "data", "normalized", "pending.json")
BUDGET_JSON = os.path.join(REPO, "config", "budget.json")
if not os.path.exists(BUDGET_JSON):  # fresh clone — fall back to the example
    BUDGET_JSON = os.path.join(REPO, "config", "budget.example.json")

# Card transactions post 1-3 days late, so "posted-only" undercounts what you
# actually spent this morning. simplefin_sync.py snapshots PENDING charges to
# pending.json; we subtract the discretionary ones from today's number IF the
# snapshot is fresh (a stale one would double-count charges that have since
# posted and been imported).
PENDING_MAX_AGE_HOURS = 36


def load_pending(today):
    try:
        with open(PENDING_JSON, encoding="utf-8") as f:
            snap = json.load(f)
        fetched = datetime.fromisoformat(snap["fetched_at"])
    except (OSError, ValueError, KeyError):
        return []
    if (datetime.now() - fetched).total_seconds() > PENDING_MAX_AGE_HOURS * 3600:
        return []
    ym = today.strftime("%Y-%m")
    return [p for p in snap.get("items", []) if p["date"][:7] == ym]


def money(x):
    return f"${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def apply_plan(budget, plan_name):
    """Optionally swap in one of the alt_plans (shallow-merge over defaults)."""
    if not plan_name:
        return budget
    alt = budget.get("alt_plans", {}).get(plan_name)
    if not alt:
        names = ", ".join(budget.get("alt_plans", {}))
        raise SystemExit(f"Unknown plan '{plan_name}'. Options: {names}")
    merged = dict(budget)
    merged.update({k: v for k, v in alt.items() if k != "category_budgets"})
    if "category_budgets" in alt:
        merged["category_budgets"] = alt["category_budgets"]
    merged["active_plan"] = plan_name
    return merged


def compute(today, budget, tx):
    ym = today.strftime("%Y-%m")
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    day = today.day
    days_left = max(1, days_in_month - day + 1)   # include today

    cat_budget = budget["category_budgets"]
    disc = budget.get("discretionary_categories", [])

    # month-to-date spend per category (spend kind only)
    mtd = defaultdict(float)
    for t in tx:
        if t.get("kind") == "spend" and t["date"][:7] == ym:
            mtd[t["category"]] += -t["amount"]

    # ---- discretionary safe-to-spend -------------------------------------
    disc_budget = sum(cat_budget.get(c, 0) for c in disc)
    disc_spent = sum(mtd.get(c, 0) for c in disc)

    # Envelope-style rollover (opt-in via "rollover": true in budget.json):
    # carry LAST month's discretionary surplus/overspend into this month's
    # pool. Only the immediately-previous month rolls (no compounding), only
    # if we have data for it, and it's valued against the CURRENT plan's
    # budget (plans can change month to month; this keeps it predictable).
    # "rollover_start": "YYYY-MM" excludes months from before you started
    # budgeting — otherwise your first budgeted month inherits a penalty
    # from spending you'd never planned against.
    rollover = 0.0
    if budget.get("rollover"):
        prev_ym = (date(today.year, today.month, 1)
                   - timedelta(days=1)).strftime("%Y-%m")
        if (prev_ym >= budget.get("rollover_start", "")
                and any(t["date"][:7] == prev_ym for t in tx)):
            prev_spent = sum(-t["amount"] for t in tx
                             if t.get("kind") == "spend"
                             and t["date"][:7] == prev_ym
                             and t["category"] in disc)
            rollover = disc_budget - prev_spent

    # Pending card charges (not yet posted/imported) count against today.
    import categorize  # sibling module; scripts/ is on sys.path when run
    pending_by_cat = defaultdict(float)
    for p in load_pending(today):
        if p["amount"] >= 0:
            continue
        r = categorize.classify(p["description"], "", p["amount"])
        if r["kind"] == "spend":
            pending_by_cat[r["category"]] += -p["amount"]
    pending_disc = sum(pending_by_cat.get(c, 0) for c in disc)

    disc_left = disc_budget + rollover - disc_spent - pending_disc
    per_day = disc_left / days_left
    per_week = per_day * min(7, days_left)

    return {
        "ym": ym, "day": day, "days_in_month": days_in_month,
        "days_left": days_left, "mtd": mtd, "cat_budget": cat_budget,
        "disc": disc, "disc_budget": disc_budget, "disc_spent": disc_spent,
        "rollover": rollover,
        "pending_by_cat": pending_by_cat, "pending_disc": pending_disc,
        "data_through": max((t["date"] for t in tx), default="?"),
        "disc_left": disc_left, "per_day": per_day, "per_week": per_week,
    }


def _short(cat):
    return cat.split(" & ")[0]


def morning_message(c, plan):
    """Multi-line message: headline, per-category extras breakdown, freshness.

    'Extras' = the discretionary categories only (eating out, shopping, fun,
    cash). Groceries/gas/bills have their own monthly budgets in the full
    table but don't drive this number.
    """
    # per-category remaining (posted + pending)
    parts = []
    for cat in c["disc"]:
        left = (c["cat_budget"].get(cat, 0) - c["mtd"].get(cat, 0)
                - c["pending_by_cat"].get(cat, 0))
        parts.append(f"{_short(cat)} {'' if left >= 0 else '−'}"
                     f"${abs(left):,.0f}")
    breakdown = "Extras left: " + " · ".join(parts)

    pool = money(c["disc_budget"])
    if c.get("rollover"):
        pool += f" {'+' if c['rollover'] > 0 else '−'} " \
                f"{money(abs(c['rollover']))} rollover"
    notes = []
    if c["pending_disc"]:
        notes.append(f"{money(c['pending_disc'])} pending counted")
    notes.append(f"data thru {c['data_through']}")
    notes.append(f"{c['days_left']} days left in {c['ym']}")
    footer = "(" + " · ".join(notes) + ")"

    if c["disc_left"] < 0:
        head = (f"⚠️ Over budget: {money(-c['disc_left'])} past your {pool} "
                f"extras budget for {c['ym']}. Aim for $0 on extras "
                f"the rest of the month.")
    else:
        emoji = "💸" if c["per_day"] >= 10 else "🟡"
        head = (f"{emoji} Safe to spend today: ~{money(c['per_day'])} · "
                f"this week: ~{money(c['per_week'])} · of {pool} [{plan}]")
    return "\n".join([head, breakdown, footer])


def full_report(c, budget, plan):
    L = [morning_message(c, plan), ""]
    w = L.append
    w("=" * 64)
    w(f"BUDGET vs ACTUAL — {c['ym']}  (day {c['day']}/{c['days_in_month']}, "
      f"{c['days_left']} left)   plan: {plan}")
    w("=" * 64)
    w(f"  {'Category':24s}{'Budget':>10s}{'Spent':>10s}{'Left':>10s}  Pace")
    total_b = total_s = 0.0
    for cat, b in sorted(c["cat_budget"].items(), key=lambda kv: -kv[1]):
        s = c["mtd"].get(cat, 0.0)
        left = b - s
        total_b += b
        total_s += s
        # expected spend by now if pacing evenly
        expected = b * (c["day"] / c["days_in_month"])
        flag = "OVER" if s > expected * 1.15 else ("ok" if s <= expected else "watch")
        tag = "  ⚑" if cat in c["disc"] else ""
        w(f"  {cat:24s}{money(b):>10s}{money(s):>10s}{money(left):>10s}  {flag}{tag}")
    w("  " + "-" * 56)
    w(f"  {'TOTAL':24s}{money(total_b):>10s}{money(total_s):>10s}"
      f"{money(total_b-total_s):>10s}")
    w("  ⚑ = discretionary (drives the daily safe-to-spend number)")
    if c.get("rollover"):
        w(f"  Rollover from last month: {money(c['rollover'])} "
          f"(envelope-style; set \"rollover\": false in budget.json to disable)")
    if c["pending_disc"]:
        w(f"  Pending card charges counted against extras: "
          f"{money(c['pending_disc'])} (not yet posted; imported once final)")
    w("")
    inc = budget.get("monthly_income_estimate")
    sav = budget.get("monthly_savings_goal")
    if inc:
        w(f"  Plan income/mo: {money(inc)}   savings goal/mo: {money(sav or 0)}"
          f"   budgeted spend: {money(total_b)}")
        gap = inc - (sav or 0) - total_b
        w(f"  Income − savings goal − budget = {money(gap)} "
          f"({'cushion' if gap >= 0 else 'SHORTFALL'})")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--plan", help="use an alt_plan from budget.json")
    ap.add_argument("--message-only", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(TX_JSON):
        raise SystemExit("Run scripts/normalize.py first.")
    budget = apply_plan(load_json(BUDGET_JSON), args.plan)
    tx = load_json(TX_JSON)["transactions"]
    today = (datetime.strptime(args.date, "%Y-%m-%d").date()
             if args.date else date.today())

    c = compute(today, budget, tx)
    plan = budget.get("active_plan", "budget")
    if args.message_only:
        print(morning_message(c, plan))
    else:
        print(full_report(c, budget, plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
