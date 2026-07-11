#!/usr/bin/env python3
"""
planning.py — forward-looking "what should I do" calculators for your budget.

Tools, all with sensible defaults you can override on the command line:

  plan      — analyze your budget plan(s): is the plan internally consistent,
              are the category budgets realistic vs your actual spending, what
              does it project for savings — and a side-by-side comparison of
              every plan in budget.json (active_plan + alt_plans).
  subs      — subscription / recurring-charge auditor with stale flags.
  loans     — student-loan payoff simulator (time + interest per payment).
  savings   — savings-rate trend + emergency-fund runway.
  fuel      — how much your premium-gas habit actually costs (from data),
              and what a regular-gas car would save.
  commute   — Columbus decision: live at home & commute (gas + hotel +
              wear on the old Benz) vs rent in Columbus. Pure-dollar
              comparison PLUS the time cost, so you can weigh it honestly.
  car       — quick car-replacement sinking-fund math.

Examples:
    python3 scripts/planning.py plan
    python3 scripts/planning.py plan --plan "Tighter Month" --months 6
    python3 scripts/planning.py fuel
    python3 scripts/planning.py commute --rent 1250 --office-days 2 --hotel 110
    python3 scripts/planning.py car --target 8000 --months 14
"""

import argparse
import json
import math
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TX_JSON = os.path.join(REPO, "data", "normalized", "transactions.json")
BUDGET_JSON = os.path.join(REPO, "config", "budget.json")
if not os.path.exists(BUDGET_JSON):  # fresh clone — fall back to the example
    BUDGET_JSON = os.path.join(REPO, "config", "budget.example.json")
PROFILE_JSON = os.path.join(REPO, "config", "profile.json")
WK_PER_MO = 4.345


def load_profile():
    return json.load(open(PROFILE_JSON, encoding="utf-8")) if os.path.exists(PROFILE_JSON) else {}


def load_budget():
    return json.load(open(BUDGET_JSON, encoding="utf-8")) if os.path.exists(BUDGET_JSON) else {}


def merchant_key(desc):
    s = desc.upper()
    s = re.sub(r"\bPURCHASE\b", " ", s)
    s = re.sub(r"\b\d{2,}\b", "", s)
    s = re.sub(r"[*#].*$", "", s)
    s = re.sub(r"[^A-Z& ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:28] or desc[:28]


def money(x):
    return f"${x:,.2f}" if x >= 0 else f"-${abs(x):,.2f}"


def load_tx():
    if not os.path.exists(TX_JSON):
        return []
    return json.load(open(TX_JSON, encoding="utf-8"))["transactions"]


# ---------------------------------------------------------------------------
# plan — financial-plan analysis: sanity-check a plan on paper, reality-check
# it against actual spending, project savings, and compare all plans.
# ---------------------------------------------------------------------------
def _plan_variant(budget, name):
    """The budget with alt_plan `name` merged in (same semantics as
    safe_to_spend.apply_plan and the dashboard's planConfig: scalars override,
    category_budgets replaces wholesale)."""
    if name == budget.get("active_plan", "Current Plan"):
        return budget
    import safe_to_spend  # sibling module; scripts/ is on sys.path when run
    return safe_to_spend.apply_plan(budget, name)


def _actuals(tx, n):
    """Avg income + per-category spend over the last n COMPLETE months
    (a trailing partial month would understate everything, so it's dropped —
    same heuristic as _recent_monthly)."""
    months = sorted(set(t["date"][:7] for t in tx))
    if not months:
        return None
    last = months[-1]
    if max(int(t["date"][8:10]) for t in tx if t["date"][:7] == last) < 28:
        months = months[:-1]
    recent = set(months[-n:])
    if not recent:
        return None
    cat, inc = defaultdict(float), 0.0
    for t in tx:
        if t["date"][:7] not in recent:
            continue
        if t["kind"] == "spend":
            cat[t["category"]] += -t["amount"]
        elif t["kind"] == "income":
            inc += t["amount"]
    k = len(recent)
    return {"months": sorted(recent), "n": k,
            "cat_avg": {c: v / k for c, v in cat.items()},
            "avg_inc": inc / k,
            "avg_spend": sum(cat.values()) / k}


def _plan_metrics(p, actual):
    cats = {c: v for c, v in (p.get("category_budgets") or {}).items()
            if isinstance(v, (int, float))}
    inc = p.get("monthly_income_estimate") or 0
    sav = p.get("monthly_savings_goal") or 0
    disc = [c for c in p.get("discretionary_categories", []) if c in cats]
    m = {"cats": cats, "inc": inc, "sav": sav,
         "budgeted": sum(cats.values()),
         "disc_total": sum(cats[c] for c in disc),
         "goal": (p.get("savings_targets") or {}).get("emergency_fund_goal")}
    m["cushion"] = inc - sav - m["budgeted"]
    if actual:
        m["unbudgeted"] = sum(v for c, v in actual["cat_avg"].items()
                              if c not in cats)
        m["net_if_hit"] = inc - m["budgeted"] - m["unbudgeted"]
    return m


def _liquid(prof):
    """Cash + taxable brokerage — the same 'liquid' proxy cmd_savings uses."""
    cash = prof.get("cash_accounts", {}) or {}
    total = sum(v for v in cash.values() if isinstance(v, (int, float)))
    return total + (prof.get("investments", {}) or {}).get(
        "Schwab One (taxable)", 0)


def _months_to_goal(goal, liquid, rate):
    if not goal:
        return None
    if goal - liquid <= 0:
        return 0.0
    if rate <= 0:
        return math.inf
    return (goal - liquid) / rate


def _fmt_months(n):
    if n is None:
        return "—"
    if n == 0:
        return "reached ✅"
    return "never" if math.isinf(n) else f"{n:.1f} mo"


def cmd_plan(a):
    budget = load_budget()
    if not budget:
        print("No budget found — copy config/budget.example.json "
              "to config/budget.json.")
        return
    prof = load_profile()
    actual = _actuals(load_tx(), a.months)

    active = budget.get("active_plan", "Current Plan")
    alt_names = list(budget.get("alt_plans", {}) or {})
    focus = a.plan or active
    if focus != active and focus not in alt_names:
        raise SystemExit(f"Unknown plan '{focus}'. "
                         f"Options: {', '.join([active] + alt_names)}")
    p = _plan_variant(budget, focus)
    m = _plan_metrics(p, actual)

    print("=" * 68)
    print(f"FINANCIAL PLAN ANALYSIS — {focus}")
    print("=" * 68)
    print("THE PLAN ON PAPER")
    print(f"  Income estimate       : {money(m['inc'])}/mo")
    print(f"  Savings goal          : {money(m['sav'])}/mo")
    print(f"  Budgeted spending     : {money(m['budgeted'])}/mo across "
          f"{len(m['cats'])} categories ({money(m['disc_total'])} "
          "discretionary ⚑)")
    print(f"  Unallocated cushion   : {money(m['cushion'])}/mo   "
          "(income − savings − budgets)")
    if m["cushion"] < 0:
        print("  ⚠ SHORTFALL on paper: the plan commits more than the income")
        print("    covers — lower the savings goal or trim category budgets.")
    else:
        print("  The cushion must absorb everything you did NOT give a budget")
        print("  line (rent, bills, insurance…) — reality check below.")

    # ---- reality check ----------------------------------------------------
    if not actual:
        print("")
        print("  (No transaction data yet — run scripts/normalize.py to add a")
        print("   reality check of these budgets against actual spending.)")
    else:
        print("")
        print(f"REALITY CHECK — budgets vs actual avg over "
              f"{actual['n']} complete month(s) "
              f"({actual['months'][0]} … {actual['months'][-1]})")
        print(f"  {'Category':24s}{'Budget':>9s}{'Actual/mo':>11s}"
              f"{'Diff':>10s}  Verdict")
        disc = p.get("discretionary_categories", [])
        for cat, b in sorted(m["cats"].items(), key=lambda kv: -kv[1]):
            act = actual["cat_avg"].get(cat, 0.0)
            verdict = ("OVER — raise it or cut habit" if act > b * 1.10
                       else "tight" if act > b * 0.95 else "ok")
            tag = " ⚑" if cat in disc else ""
            print(f"  {cat:24s}{money(b):>9s}{money(act):>11s}"
                  f"{money(b - act):>10s}  {verdict}{tag}")
        unb = sorted(((c, v) for c, v in actual["cat_avg"].items()
                      if c not in m["cats"] and v > 0),
                     key=lambda kv: -kv[1])
        if unb:
            top = " · ".join(f"{c} {money(v)}" for c, v in unb[:5])
            if len(unb) > 5:
                top += f" · +{len(unb) - 5} more"
            print(f"  Spending with NO budget line: "
                  f"{money(m['unbudgeted'])}/mo avg")
            print(f"    {top}")
        d = actual["avg_inc"] - m["inc"]
        print(f"  Income: plan {money(m['inc'])} vs actual "
              f"{money(actual['avg_inc'])}/mo "
              f"({'+' if d >= 0 else '−'}{money(abs(d))} vs plan)")

        # ---- projection ----------------------------------------------------
        cur_net = actual["avg_inc"] - actual["avg_spend"]
        liquid = _liquid(prof)
        print("")
        print("PROJECTION")
        print(f"  If you hit every budget : net {money(m['net_if_hit'])}/mo  "
              f"({money(m['net_if_hit'] * 12)}/yr)   "
              "(plan income − budgets − unbudgeted avg)")
        print(f"  At your current pace    : net {money(cur_net)}/mo  "
              f"({money(cur_net * 12)}/yr)   (actual income − actual spend)")
        if m["sav"]:
            gap = m["net_if_hit"] - m["sav"]
            print(f"  Savings goal {money(m['sav'])}/mo: "
                  + (f"covered, {money(gap)}/mo to spare ✅" if gap >= 0 else
                     f"even on-plan you'd MISS it by {money(-gap)}/mo ⚠"))
        if m["goal"]:
            print(f"  Emergency fund {money(m['goal'])} (liquid now "
                  f"{money(liquid)}): "
                  f"{_fmt_months(_months_to_goal(m['goal'], liquid, m['net_if_hit']))} "
                  f"on plan · "
                  f"{_fmt_months(_months_to_goal(m['goal'], liquid, cur_net))} "
                  "at current pace")
            if not prof:
                print("    (no config/profile.json — liquid assumed $0; add "
                      "cash balances for real numbers)")

    # ---- side-by-side comparison ------------------------------------------
    names = [active] + alt_names
    if len(names) < 2:
        print("")
        print("  Only one plan defined. Add scenarios under \"alt_plans\" in")
        print("  config/budget.json to compare (see budget.example.json).")
        return
    mm = {n: _plan_metrics(_plan_variant(budget, n), actual) for n in names}
    W = 16
    trunc = lambda s: s if len(s) <= W - 2 else s[:W - 3] + "…"
    print("")
    print("PLAN COMPARISON" + ("" if actual else " (on paper only — no data)"))
    print("  " + " " * 24 + "".join(f"{trunc(n):>{W}s}" for n in names))
    rows = [("Income /mo", "inc"), ("Savings goal /mo", "sav"),
            ("Budgeted spend /mo", "budgeted"),
            ("Unallocated cushion /mo", "cushion")]
    if actual:
        rows += [("Unbudgeted (actual) /mo", "unbudgeted"),
                 ("Net if budgets hit /mo", "net_if_hit")]
    for label, key in rows:
        line = f"  {label:24s}"
        for n in names:
            v = mm[n][key]
            flag = " ⚠" if key == "cushion" and v < 0 else ""
            line += f"{money(v) + flag:>{W}s}"
        print(line)
    if actual and any(mm[n]["goal"] for n in names):
        liquid = _liquid(prof)
        line = f"  {'Months to emerg. fund':24s}"
        for n in names:
            line += (f"{_fmt_months(_months_to_goal(mm[n]['goal'], liquid, mm[n]['net_if_hit'])):>{W}s}")
        print(line)
    print("")
    print("  Try a plan day-to-day:  safe_to_spend.py --plan \"<name>\"")
    print("  (the dashboard's plan selector shows the same plans)")


# ---------------------------------------------------------------------------
def cmd_fuel(a):
    tx = load_tx()
    gas = [t for t in tx if t["kind"] == "spend" and t["category"] == "Gas & Fuel"]
    if not gas:
        print("No gas transactions found.")
        return
    total = -sum(t["amount"] for t in gas)
    months = len(set(t["date"][:7] for t in gas)) or 1
    per_mo = total / months
    # premium upcharge: the slice of each fill that is the premium-over-regular delta
    upcharge_frac = a.premium_delta / a.premium_price
    extra = total * upcharge_frac
    print("=" * 60)
    print("FUEL ANALYSIS  (for cars that take premium gas)")
    print("=" * 60)
    print(f"  Total fuel spend on record : {money(total)}  over {months} months")
    print(f"  Average                    : {money(per_mo)}/mo  ({money(per_mo*12)}/yr)")
    print(f"  Assumed premium upcharge   : {money(a.premium_delta)}/gal on "
          f"{money(a.premium_price)}/gal premium ({upcharge_frac*100:.0f}% of spend)")
    print(f"  → Premium 'tax' you pay    : ~{money(extra/months*12)}/yr vs a "
          "regular-gas car")
    print(f"  A reliable regular-gas car would also cut maintenance materially")
    print(f"  on an aging luxury car (timing belts, suspension,")
    print(f"  cooling, electronics often run $800–2,000 per incident).")


# ---------------------------------------------------------------------------
def cmd_commute(a):
    # ---- option A: live at home, commute to Columbus ----------------------
    round_trip = a.distance * 2
    gas_per_trip = round_trip / a.mpg * a.premium_price
    weekly_gas = gas_per_trip * a.trips
    weekly_hotel = a.hotel * a.hotel_nights
    weekly_wear = round_trip * a.trips * a.wear
    monthly_gas = weekly_gas * WK_PER_MO
    monthly_hotel = weekly_hotel * WK_PER_MO
    monthly_wear = weekly_wear * WK_PER_MO
    commute_cash = monthly_gas + monthly_hotel              # out-of-pocket
    commute_all = commute_cash + monthly_wear              # incl. wear/depreciation
    weekly_hours = (round_trip / a.avg_mph) * a.trips
    monthly_hours = weekly_hours * WK_PER_MO

    # ---- option B: rent in Columbus ---------------------------------------
    rent_all = a.rent + a.utils + a.local_gas

    print("=" * 64)
    print("COMMUTE vs RENT  —  Columbus, in-office "
          f"{a.office_days} days/week")
    print("=" * 64)
    print(f"Assumptions: {a.distance}mi each way, {a.mpg}mpg, "
          f"{money(a.premium_price)}/gal, {a.trips} trip(s)/wk, "
          f"{a.hotel_nights} hotel night(s)/wk @ {money(a.hotel)}")
    print("")
    print("OPTION A — live at home, commute & stay over")
    print(f"  Gas                : {money(monthly_gas)}/mo")
    print(f"  Hotel              : {money(monthly_hotel)}/mo")
    print(f"  Out-of-pocket cash : {money(commute_cash)}/mo")
    print(f"  + Car wear/deprec. : {money(monthly_wear)}/mo "
          f"(@ {money(a.wear)}/mi — higher for the old Benz)")
    print(f"  = All-in cost      : {money(commute_all)}/mo")
    print(f"  Time in the car    : ~{weekly_hours:.1f} hrs/wk  "
          f"(~{monthly_hours:.0f} hrs/mo)")
    print("")
    print("OPTION B — rent in Columbus")
    print(f"  Rent               : {money(a.rent)}/mo")
    print(f"  Utilities+internet : {money(a.utils)}/mo")
    print(f"  Local gas          : {money(a.local_gas)}/mo")
    print(f"  = All-in cost      : {money(rent_all)}/mo")
    print("")
    diff = rent_all - commute_all
    print("VERDICT")
    if diff > 0:
        print(f"  Commuting from home is ~{money(diff)}/mo CHEAPER "
              f"({money(diff*12)}/yr)…")
        print(f"  …but costs you ~{monthly_hours:.0f} hrs/mo behind the wheel and "
              "piles miles")
        print( "  onto a car that's already a reliability risk. If you value your")
        if monthly_hours > 0:
            print(f"  time over {money(diff/monthly_hours)}/hr, renting wins.")
    else:
        print(f"  Renting in Columbus is ~{money(-diff)}/mo cheaper AND saves "
              f"~{monthly_hours:.0f} hrs/mo of driving — rent.")
    print("  Note: a car payment on a replacement vehicle would add to BOTH")
    print("  options; commuting just burns the replacement timeline faster.")


# ---------------------------------------------------------------------------
def cmd_car(a):
    monthly = a.target / a.months
    print("=" * 56)
    print("CAR REPLACEMENT SINKING FUND")
    print("=" * 56)
    print(f"  Goal down payment : {money(a.target)}")
    print(f"  Timeline          : {a.months} months")
    print(f"  → Save            : {money(monthly)}/mo")
    print(f"  At {money(a.target)} down on a ~$18–22k reliable used Honda/Toyota,")
    print(f"  you'd finance ~$12–16k. Buying a regular-gas car ends the premium")
    print(f"  fuel upcharge and the high-mileage repair roulette.")


def cmd_subs(a):
    tx = load_tx()
    spend = [t for t in tx if t["kind"] == "spend"]
    if not spend:
        print("No spend data.")
        return
    last_date = max(t["date"] for t in spend)
    by = defaultdict(list)
    for t in spend:
        by[merchant_key(t["description"])].append(t)
    subs = []
    for k, items in by.items():
        months = sorted(set(t["date"][:7] for t in items))
        if len(months) < 3 or len(items) > round(len(months) * 1.5):
            continue
        amts = [-t["amount"] for t in items]
        med = statistics.median(amts)
        if med <= 0 or (max(amts) - min(amts)) / med > 0.30:
            continue
        seen = sorted(t["date"] for t in items)
        gap_days = (datetime.fromisoformat(last_date)
                    - datetime.fromisoformat(seen[-1])).days
        subs.append({"name": k, "amt": med, "n_mo": len(months),
                     "first": seen[0], "last": seen[-1], "yr": med * 12,
                     "stale": gap_days > 45})
    subs.sort(key=lambda s: -s["yr"])
    print("=" * 72)
    print("SUBSCRIPTION & RECURRING-CHARGE AUDITOR")
    print("=" * 72)
    print(f"  {'Merchant':28s}{'~Each':>9s}{'/yr':>10s}{'Mos':>5s}  "
          f"{'Last seen':>10s}  Status")
    active_yr = 0.0
    for s in subs:
        status = "⚠ not seen 45+ days" if s["stale"] else "active"
        if not s["stale"]:
            active_yr += s["yr"]
        print(f"  {s['name']:28s}{money(s['amt']):>9s}{money(s['yr']):>10s}"
              f"{s['n_mo']:>5d}  {s['last']:>10s}  {status}")
    print("  " + "-" * 68)
    print(f"  Active recurring spend: ~{money(active_yr)}/yr "
          f"(~{money(active_yr/12)}/mo)")
    print("  Review anything you don't use — and the ⚠ ones in case they're")
    print("  still billing a card that's not in this export.")


def _payoff_months(balance, annual_rate_pct, payment):
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return balance / payment
    if payment <= balance * r:
        return None  # payment doesn't even cover interest
    return math.log(payment / (payment - balance * r)) / math.log(1 + r)


def cmd_loans(a):
    prof = load_profile()
    loans = prof.get("loans", [])
    if not loans:
        print("No loans in config/profile.json.")
        return
    bal = sum(l["balance"] for l in loans)
    blended = sum(l["balance"] * l["rate_pct"] for l in loans) / bal
    print("=" * 68)
    print("STUDENT LOAN PAYOFF SIMULATOR")
    print("=" * 68)
    for l in loans:
        print(f"  {l['name']:30s} {money(l['balance']):>10s} @ {l['rate_pct']}%"
              f"  (repay starts {l.get('repayment_begins','?')})")
    print(f"  {'TOTAL':30s} {money(bal):>10s} @ {blended:.2f}% blended")
    print(f"  Currently subsidized → $0 interest until repayment begins.")
    print("")
    print(f"  Once interest starts, payoff time & cost at various payments")
    print(f"  (blended {blended:.2f}%):")
    print(f"    {'Payment/mo':>12s}{'Payoff':>11s}{'Interest':>12s}{'Total paid':>13s}")
    pays = a.payments or [150, 250, 400, 600]
    for p in pays:
        n = _payoff_months(bal, blended, p)
        if n is None:
            print(f"    {money(p):>12s}   never (below interest)")
            continue
        interest = p * n - bal
        print(f"    {money(p):>12s}{n:>9.1f}mo{money(interest):>12s}"
              f"{money(bal+interest):>13s}")
    print("")
    print("  STRATEGY")
    print(f"  • While subsidized (0%): don't prepay — invest instead.")
    print(f"  • Avalanche: when interest starts, kill the {loans[-1]['rate_pct']}% "
          "loan first.")
    inv = a.invest_return
    print(f"  • Extra payments earn a guaranteed {blended:.2f}%. Investing might")
    print(f"    earn ~{inv:.0f}% but isn't guaranteed. At {blended:.2f}%, once")
    print(f"    interest starts paying the loans off fast is a strong, low-risk")
    print(f"    move — after you capture any employer 401(k) match.")


def _recent_monthly(tx, n=3):
    spend, inc = defaultdict(float), defaultdict(float)
    for t in tx:
        ym = t["date"][:7]
        if t["kind"] == "spend":
            spend[ym] += -t["amount"]
        elif t["kind"] == "income":
            inc[ym] += t["amount"]
    months = sorted(set(spend) | set(inc))
    if not months:
        return None
    last = months[-1]
    last_days = [int(t["date"][8:10]) for t in tx if t["date"][:7] == last]
    if last_days and max(last_days) < 28:
        months = months[:-1]
    recent = months[-n:]
    return {
        "months": months, "recent": recent, "spend": spend, "inc": inc,
        "avg_spend": sum(spend[m] for m in recent) / len(recent) if recent else 0,
        "avg_inc": sum(inc[m] for m in recent) / len(recent) if recent else 0,
    }


def cmd_savings(a):
    tx = load_tx()
    prof = load_profile()
    budg = load_budget()
    r = _recent_monthly(tx, a.months)
    if not r:
        print("No data.")
        return
    print("=" * 64)
    print("SAVINGS RATE, TREND & RUNWAY")
    print("=" * 64)
    print("  Monthly net (income − spend), recent months:")
    for m in r["months"][-12:]:
        net = r["inc"][m] - r["spend"][m]
        rate = (net / r["inc"][m] * 100) if r["inc"][m] else 0
        bar = "█" * min(30, int(abs(net) / 150))
        sign = "+" if net >= 0 else "-"
        print(f"    {m}  net {money(net):>11s} ({rate:>5.0f}%)  {sign}{bar}")
    avg_net = r["avg_inc"] - r["avg_spend"]
    print(f"\n  Recent avg: income {money(r['avg_inc'])}/mo, spend "
          f"{money(r['avg_spend'])}/mo, net {money(avg_net)}/mo")

    # liquid + runway
    cash = prof.get("cash_accounts", {}) or {}
    cash_total = sum(v for v in cash.values() if isinstance(v, (int, float)))
    taxable = (prof.get("investments", {}) or {}).get("Schwab One (taxable)", 0)
    liquid = cash_total + taxable
    print("\n  EMERGENCY-FUND RUNWAY")
    print(f"    Liquid (cash {money(cash_total)} + taxable brokerage "
          f"{money(taxable)}) = {money(liquid)}")
    if r["avg_spend"] > 0:
        print(f"    Runway = {liquid/r['avg_spend']:.1f} months of spending "
              f"at {money(r['avg_spend'])}/mo")
    print(f"    3-month fund target: {money(r['avg_spend']*3)}   "
          f"6-month: {money(r['avg_spend']*6)}")
    goal = (budg.get("savings_targets", {}) or {}).get("emergency_fund_goal")
    if goal:
        print(f"    Goal (budget.json): {money(goal)} — "
              f"{'reached ✅' if liquid>=goal else money(goal-liquid)+' to go'}")
    print("    NOTE: add your Huntington cash balances to config/profile.json")
    print("    for an accurate runway (taxable brokerage shown as a proxy).")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("plan")
    pl.add_argument("--plan", help="analyze a specific plan "
                    "(default: the active plan; alt plans always compared)")
    pl.add_argument("--months", type=int, default=3,
                    help="complete months of actuals for the reality check")
    pl.set_defaults(func=cmd_plan)

    s = sub.add_parser("subs")
    s.set_defaults(func=cmd_subs)

    ln = sub.add_parser("loans")
    ln.add_argument("--payments", type=float, nargs="*",
                    help="monthly payment scenarios (e.g. 200 400)")
    ln.add_argument("--invest-return", type=float, default=7)
    ln.set_defaults(func=cmd_loans)

    sv = sub.add_parser("savings")
    sv.add_argument("--months", type=int, default=3)
    sv.set_defaults(func=cmd_savings)

    f = sub.add_parser("fuel")
    f.add_argument("--premium-price", type=float, default=3.80)
    f.add_argument("--premium-delta", type=float, default=0.55,
                   help="$/gal premium costs over regular")
    f.set_defaults(func=cmd_fuel)

    c = sub.add_parser("commute")
    c.add_argument("--distance", type=float, default=140, help="miles each way")
    c.add_argument("--mpg", type=float, default=22)
    c.add_argument("--premium-price", type=float, default=3.80)
    c.add_argument("--trips", type=float, default=1, help="round trips/week")
    c.add_argument("--hotel", type=float, default=120, help="$/night")
    c.add_argument("--hotel-nights", type=float, default=1)
    c.add_argument("--wear", type=float, default=0.15, help="$/mile wear+deprec")
    c.add_argument("--avg-mph", type=float, default=62)
    c.add_argument("--office-days", type=int, default=2)
    c.add_argument("--rent", type=float, default=1300)
    c.add_argument("--utils", type=float, default=260)
    c.add_argument("--local-gas", type=float, default=80)
    c.set_defaults(func=cmd_commute)

    k = sub.add_parser("car")
    k.add_argument("--target", type=float, default=7000, help="down payment goal")
    k.add_argument("--months", type=int, default=18)
    k.set_defaults(func=cmd_car)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
