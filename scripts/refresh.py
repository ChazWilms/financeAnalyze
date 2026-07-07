#!/usr/bin/env python3
"""
refresh.py — one-command data refresh: find new bank exports, ingest, normalize.

This is the closest thing to "connecting" the accounts without handing bank
credentials to a third-party aggregator: you download fresh CSV exports from
Discover / Huntington (they land in ~/Downloads), and this script does the rest.

What it does
------------
1. Scans ~/Downloads (and data/raw/ itself) for CSV files that look like
   Discover or Huntington transaction exports (by header signature).
2. Figures out WHICH account a Huntington export belongs to (checking / hub /
   savings) by overlap-matching its rows against your existing history —
   Huntington's export headers are identical across accounts, so filename
   alone isn't enough.
3. Copies each new export into data/raw/ with a canonical, datestamped name
   (e.g. discover_creditcard_20260707.csv) so normalize.py labels + de-dupes
   it correctly against the files already there. Originals in Downloads are
   left untouched.
4. Remembers what it already ingested (data/raw/.ingested.json, by content
   hash) so re-runs are idempotent.
5. Re-runs normalize.py and prints how fresh each account's data now is.

Usage
-----
    python3 scripts/refresh.py            # scan Downloads + ingest + normalize
    python3 scripts/refresh.py --dry-run  # show what would be ingested
    python3 scripts/refresh.py file.csv   # ingest a specific file
"""

import csv
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO, "data", "raw")
NORM_FILE = os.path.join(REPO, "data", "normalized", "transactions.json")
LEDGER = os.path.join(RAW_DIR, ".ingested.json")
DOWNLOADS = os.path.expanduser("~/Downloads")
SCAN_DAYS = 60          # ignore Downloads files older than this
MIN_OVERLAP = 3         # rows that must match history to claim an account

DISCOVER_SIG = {"trans. date", "post date", "description", "amount"}
HUNTINGTON_SIG = {"date", "description", "amount"}   # + Category/Split/Tags


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ledger():
    try:
        with open(LEDGER) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_ledger(ledger):
    with open(LEDGER, "w") as f:
        json.dump(ledger, f, indent=2)


def read_headers_and_rows(path, max_rows=None):
    """Return (lowercased header list, data rows) or (None, []) if unreadable."""
    try:
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            rows = [r for r in reader if any(c.strip() for c in r)]
    except OSError:
        return None, []
    if not rows:
        return None, []
    headers = [c.strip().lower() for c in rows[0]]
    data = rows[1:max_rows + 1] if max_rows else rows[1:]
    return headers, data


def classify_export(path):
    """Return 'discover' | 'huntington' | None from the header row."""
    headers, data = read_headers_and_rows(path, max_rows=1)
    if not headers or not data:
        return None
    hset = set(headers)
    if DISCOVER_SIG.issubset(hset):
        return "discover"
    if HUNTINGTON_SIG.issubset(hset) and "category" in hset:
        return "huntington"
    return None


def norm_desc(s):
    return re.sub(r"\s+", " ", s.strip().upper())[:40]


def parse_mdY(s):
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def file_row_keys(path):
    """(date, amount, desc-prefix) keys for overlap matching."""
    headers, data = read_headers_and_rows(path)
    if not headers:
        return set()
    try:
        di = headers.index("date")
        de = headers.index("description")
        am = headers.index("amount")
    except ValueError:
        return set()
    keys = set()
    for r in data:
        if len(r) <= max(di, de, am):
            continue
        d = parse_mdY(r[di])
        if not d:
            continue
        try:
            amt = round(float(r[am].replace("$", "").replace(",", "")), 2)
        except ValueError:
            continue
        keys.add((d, amt, norm_desc(r[de])))
    return keys


def history_keys_by_account():
    """Existing normalized rows, keyed the same way, grouped by account."""
    try:
        with open(NORM_FILE) as f:
            txs = json.load(f)["transactions"]
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for t in txs:
        out.setdefault(t["account"], set()).add(
            (t["date"], round(t["amount"], 2), norm_desc(t["description"])))
    return out


def match_huntington_account(path):
    """Which Huntington account is this export? -> canonical stem or None."""
    stems = {
        "Huntington Checking": "huntington_checking",
        "Huntington Hub": "huntington_hub",
        "Huntington Savings": "huntington_savings",
    }
    fn = os.path.basename(path).lower()
    for label, stem in stems.items():
        hint = stem.split("_")[1]
        if hint in fn:
            return stem
    keys = file_row_keys(path)
    if not keys:
        return None
    scores = []
    for label, stem in stems.items():
        hist = history_keys_by_account().get(label, set())
        scores.append((len(keys & hist), stem, label))
    scores.sort(reverse=True)
    best, runner = scores[0], scores[1]
    if best[0] >= MIN_OVERLAP and best[0] > runner[0]:
        return best[1]
    return None


def find_candidates(explicit_paths):
    if explicit_paths:
        return [os.path.abspath(p) for p in explicit_paths]
    cutoff = datetime.now() - timedelta(days=SCAN_DAYS)
    cands = []
    # also scan the app folder itself — exports sometimes get dropped there
    for folder in (DOWNLOADS, REPO):
        for p in glob.glob(os.path.join(folder, "*.csv")) + \
                 glob.glob(os.path.join(folder, "*.CSV")):
            if datetime.fromtimestamp(os.path.getmtime(p)) >= cutoff:
                cands.append(p)
    return sorted(cands)


def main(argv):
    dry = "--dry-run" in argv
    paths = [a for a in argv[1:] if not a.startswith("-")]
    ledger = load_ledger()
    stamp = datetime.now().strftime("%Y%m%d")
    ingested, skipped, unknown = [], [], []

    for path in find_candidates(paths):
        kind = classify_export(path)
        if kind is None:
            continue  # not a bank export — ignore silently
        digest = sha256(path)
        if digest in ledger:
            skipped.append(os.path.basename(path))
            continue
        if kind == "discover":
            stem = "discover_creditcard"
        else:
            stem = match_huntington_account(path)
            if stem is None:
                unknown.append(path)
                continue
        dest = os.path.join(RAW_DIR, f"{stem}_{stamp}.csv")
        n = 1
        while os.path.exists(dest) and sha256(dest) != digest:
            n += 1
            dest = os.path.join(RAW_DIR, f"{stem}_{stamp}_{n}.csv")
        if dry:
            print(f"  would ingest: {path} -> {os.path.basename(dest)}")
            ingested.append(os.path.basename(dest))
            continue
        with open(path, "rb") as src, open(dest, "wb") as out:
            out.write(src.read())
        ledger[digest] = {"file": os.path.basename(dest),
                          "from": path,
                          "ingested_at": datetime.now().isoformat(timespec="seconds")}
        ingested.append(os.path.basename(dest))

    if not dry:
        save_ledger(ledger)

    if ingested:
        if not dry:
            print("Ingested new exports:", flush=True)
            for f in ingested:
                print(f"  + {f}", flush=True)
    else:
        print("No new bank exports found"
              + (f" in {DOWNLOADS}" if not paths else "") + ".")
    if unknown:
        print("\n⚠ Couldn't tell which Huntington account these belong to.")
        print("  Rename with a hint (checking/hub/savings) and re-run:")
        for p in unknown:
            print(f"    {p}")

    if not dry:
        print("\n▶ Normalizing…", flush=True)
        r = subprocess.run([sys.executable,
                            os.path.join(REPO, "scripts", "normalize.py")])
        if r.returncode != 0:
            return r.returncode

    # Freshness per account
    try:
        with open(NORM_FILE) as f:
            txs = json.load(f)["transactions"]
        last = {}
        for t in txs:
            last[t["account"]] = max(last.get(t["account"], ""), t["date"])
        today = datetime.now().date()
        print("\nDATA FRESHNESS")
        for acct in sorted(last):
            age = (today - datetime.strptime(last[acct], "%Y-%m-%d").date()).days
            flag = "  ← stale, export a fresh CSV" if age > 10 else ""
            print(f"  {acct:22s} through {last[acct]}  ({age}d ago){flag}")
    except (OSError, ValueError, KeyError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
