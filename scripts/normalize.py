#!/usr/bin/env python3
"""
normalize.py — Robust transaction CSV -> normalized JSON pipeline.

Goal: take ANY transaction export the user drops into data/raw/ (Huntington
checking/savings, any credit card, or a generic export) and turn it into one
clean, consistent JSON file the analyzer and dashboard both understand.

Design principles
-----------------
* stdlib only (csv, json, re, glob, os, sys, datetime) — no pip installs needed.
* Header detection is fuzzy & case-insensitive so we tolerate format drift.
* Sign convention after normalization:
      amount > 0  => money IN  (income, refunds, credit-card payments received)
      amount < 0  => money OUT (purchases, withdrawals, fees)
  Credit-card exports are auto-flipped because they list purchases as positive.
* Every row is tagged with the source file + detected account so multi-account
  analysis works.
* De-duplicates identical (date, amount, description, account) rows.

Usage
-----
    python3 scripts/normalize.py
        Reads every *.csv in data/raw/, writes data/normalized/transactions.json

    python3 scripts/normalize.py path/to/file.csv [more.csv ...]
        Normalizes specific files instead of scanning data/raw/.

Account type / sign handling
----------------------------
By default the script GUESSES whether a file is a credit card or a bank account
from its headers and filename. You can force it by putting a hint in the
filename, e.g.:
    huntington_checking_2026.csv     -> bank
    chase_creditcard_2026.csv        -> credit  (purchases get flipped to negative)
"""

import csv
import glob
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from categorize import classify  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO_ROOT, "data", "raw")
OUT_DIR = os.path.join(REPO_ROOT, "data", "normalized")
OUT_FILE = os.path.join(OUT_DIR, "transactions.json")

# ---------------------------------------------------------------------------
# Header alias tables. Lowercased header text is matched against these.
# ---------------------------------------------------------------------------
DATE_HEADERS = [
    "transaction date", "trans date", "post date", "posting date",
    "posted date", "date", "effective date",
]
DESC_HEADERS = [
    "description", "memo", "payee", "name", "transaction", "details",
    "merchant", "narrative",
]
AMOUNT_HEADERS = ["amount", "transaction amount", "amt"]
DEBIT_HEADERS = ["debit", "withdrawal", "withdrawals", "money out", "outflow"]
CREDIT_HEADERS = ["credit", "deposit", "deposits", "money in", "inflow"]
BALANCE_HEADERS = ["balance", "running balance", "ending balance"]
TYPE_HEADERS = ["type", "transaction type", "debit/credit"]
BANKCAT_HEADERS = ["category", "transaction category"]

DATE_FORMATS = [
    "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y",
    "%d/%m/%Y", "%b %d, %Y", "%m/%d/%Y %H:%M", "%Y/%m/%d",
    "%m/%d/%Y %I:%M %p",
]


def find_col(headers_lower, aliases):
    """Return index of first header matching any alias (exact then substring)."""
    for i, h in enumerate(headers_lower):
        if h in aliases:
            return i
    for i, h in enumerate(headers_lower):
        for a in aliases:
            if a in h:
                return i
    return None


def parse_amount(raw):
    """Parse a currency string into a float. Handles $, commas, ()-negatives."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    if s in ("", "-", "--"):
        return None
    try:
        val = float(s)
    except ValueError:
        # Strip any stray non-numeric chars and retry.
        s2 = re.sub(r"[^0-9.\-]", "", s)
        try:
            val = float(s2)
        except ValueError:
            return None
    return -val if neg else val


def parse_date(raw):
    """Parse a date string into ISO YYYY-MM-DD, or None."""
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Last resort: pull out an m/d/y pattern.
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        mm, dd, yy = m.groups()
        yy = ("20" + yy) if len(yy) == 2 else yy
        try:
            return datetime(int(yy), int(mm), int(dd)).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def guess_account(filename, headers_lower):
    """Best-effort (account_label, is_credit_card) from filename + headers."""
    fn = filename.lower()
    is_credit = any(k in fn for k in ("credit", "card", "visa", "mastercard",
                                      "amex", "discover", "capital"))
    # Credit-card exports usually lack a running balance column.
    if not is_credit and find_col(headers_lower, BALANCE_HEADERS) is None \
            and find_col(headers_lower, AMOUNT_HEADERS) is not None \
            and find_col(headers_lower, DEBIT_HEADERS) is None:
        # ambiguous — leave as bank unless filename says card
        pass

    def titlecase(name):
        s = re.sub(r"[_\-]", " ", os.path.splitext(name)[0]).title()
        return s.replace("Creditcard", "Card").replace("Hub", "Hub")

    if "huntington" in fn:
        if "saving" in fn:
            label = "Huntington Savings"
        elif "checking" in fn:
            label = "Huntington Checking"
        elif "credit" in fn or "card" in fn:
            label = "Huntington Credit Card"
        elif "hub" in fn:
            # explicit so datestamped refreshes (huntington_hub_20260707.csv)
            # land in the same account and de-dupe against older files
            label = "Huntington Hub"
        else:
            label = titlecase(filename)
    elif "discover" in fn:
        label = "Discover Card"
    elif "capital" in fn:
        label = "Capital One Card"
    else:
        label = titlecase(filename)

    return label, is_credit


def normalize_file(path):
    """Parse one CSV file into a list of normalized transaction dicts."""
    filename = os.path.basename(path)
    rows = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        # Sniff delimiter; default to comma.
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)
        all_rows = [r for r in reader if any(c.strip() for c in r)]

    if not all_rows:
        return []

    # Find the header row: the first row that contains a recognizable date or
    # amount header. Some bank exports have junk preamble lines.
    header_idx = 0
    for i, row in enumerate(all_rows[:10]):
        low = [c.strip().lower() for c in row]
        if find_col(low, DATE_HEADERS) is not None and (
            find_col(low, AMOUNT_HEADERS) is not None
            or find_col(low, DEBIT_HEADERS) is not None
            or find_col(low, CREDIT_HEADERS) is not None
        ):
            header_idx = i
            break

    headers = [c.strip() for c in all_rows[header_idx]]
    headers_lower = [h.lower() for h in headers]
    data_rows = all_rows[header_idx + 1:]

    date_i = find_col(headers_lower, DATE_HEADERS)
    desc_i = find_col(headers_lower, DESC_HEADERS)
    amt_i = find_col(headers_lower, AMOUNT_HEADERS)
    debit_i = find_col(headers_lower, DEBIT_HEADERS)
    credit_i = find_col(headers_lower, CREDIT_HEADERS)
    bal_i = find_col(headers_lower, BALANCE_HEADERS)
    type_i = find_col(headers_lower, TYPE_HEADERS)
    bankcat_i = find_col(headers_lower, BANKCAT_HEADERS)

    account_label, is_credit = guess_account(filename, headers_lower)

    def cell(row, idx):
        return row[idx] if idx is not None and idx < len(row) else ""

    out = []
    for row in data_rows:
        date = parse_date(cell(row, date_i))
        if not date:
            continue  # skip rows without a parseable date (totals, blanks)

        desc = cell(row, desc_i).strip()
        if not desc:
            # build a description from whatever non-empty cells remain
            desc = " ".join(c.strip() for c in row
                            if c.strip() and c.strip() != cell(row, date_i)) or "(no description)"
        desc = re.sub(r"\s+", " ", desc)

        # ---- Determine amount + sign --------------------------------------
        amount = None
        if amt_i is not None:
            amount = parse_amount(cell(row, amt_i))
        if amount is None and (debit_i is not None or credit_i is not None):
            d = parse_amount(cell(row, debit_i)) if debit_i is not None else None
            c = parse_amount(cell(row, credit_i)) if credit_i is not None else None
            if c is not None and c != 0:
                amount = abs(c)            # credit = money in
            elif d is not None and d != 0:
                amount = -abs(d)           # debit = money out
        if amount is None:
            continue

        # Credit-card single-amount exports list purchases as positive.
        # Flip so our convention (out = negative) holds. Skip flip if the file
        # already used debit/credit columns (handled above).
        if is_credit and amt_i is not None and debit_i is None and credit_i is None:
            amount = -amount

        balance = parse_amount(cell(row, bal_i)) if bal_i is not None else None
        raw_type = cell(row, type_i).strip() if type_i is not None else ""
        bank_category = cell(row, bankcat_i).strip() if bankcat_i is not None else ""

        result = classify(desc, bank_category, amount)
        flow = "in" if amount >= 0 else "out"

        out.append({
            "date": date,
            "description": desc,
            "amount": round(amount, 2),
            "flow": flow,
            "kind": result["kind"],            # income | spend | internal
            "category": result["category"],
            "bank_category": bank_category,
            "account": account_label,
            "balance": round(balance, 2) if balance is not None else None,
            "raw_type": raw_type,
            "source_file": filename,
        })
    return out


def main(argv):
    if len(argv) > 1:
        paths = argv[1:]
    else:
        paths = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")) +
                       glob.glob(os.path.join(RAW_DIR, "*.CSV")))

    if not paths:
        print(f"No CSV files found in {RAW_DIR}")
        print("Drop your transaction exports there and re-run.")
        return 1

    all_tx = []
    for p in paths:
        try:
            tx = normalize_file(p)
            print(f"  {os.path.basename(p):40s} -> {len(tx):5d} transactions")
            all_tx.extend(tx)
        except Exception as e:  # noqa: BLE001
            print(f"  !! Failed on {p}: {e}")

    # De-duplicate.
    seen = set()
    deduped = []
    for t in all_tx:
        key = (t["date"], t["amount"], t["description"], t["account"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)

    deduped.sort(key=lambda t: t["date"])

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "transaction_count": len(deduped),
        "source_files": [os.path.basename(p) for p in paths],
        "transactions": deduped,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    dropped = len(all_tx) - len(deduped)
    print(f"\nWrote {len(deduped)} transactions to {OUT_FILE}"
          + (f" ({dropped} duplicates removed)" if dropped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
