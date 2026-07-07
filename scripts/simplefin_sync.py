#!/usr/bin/env python3
"""
simplefin_sync.py — OPTIONAL true auto-sync via SimpleFIN Bridge.

Discover and Huntington don't offer personal-use APIs, so the only way to get
transactions without downloading CSVs yourself is through an aggregator.
SimpleFIN Bridge (https://bridge.simplefin.org, ~$1.50/mo) is the
privacy-friendliest one: you link your banks there once, and this script pulls
new transactions from it on demand. If you'd rather not hand bank credentials
to any third party, skip this entirely and use scripts/refresh.py with manual
CSV exports — the rest of the app works the same either way.

One-time setup
--------------
1. Create an account at https://bridge.simplefin.org and connect
   Discover + Huntington there.
2. On the Bridge site, create a new "app" connection → it gives you a
   SETUP TOKEN (long base64 string).
3. Run:  python3 scripts/simplefin_sync.py --setup PASTE_TOKEN_HERE
   This claims the token and stores the access URL in
   config/simplefin_access.url (git-ignored, chmod 600).
4. Run:  python3 scripts/simplefin_sync.py
   First run writes config/simplefin_map.json listing your accounts —
   edit it so each SimpleFIN account maps to the right canonical name
   (discover_creditcard / huntington_checking / huntington_hub /
   huntington_savings), then run again.

Routine use:  python3 scripts/simplefin_sync.py   (weekly.sh calls this
automatically if the access URL exists). Fetches each account since the day
after its newest known transaction (avoids double-counting rows that came in
via CSV exports with slightly different descriptions), writes Money In/Money
Out CSVs into data/raw/, and re-runs normalize.py.
"""

import base64
import csv
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO, "data", "raw")
NORM_FILE = os.path.join(REPO, "data", "normalized", "transactions.json")
ACCESS_FILE = os.path.join(REPO, "config", "simplefin_access.url")
MAP_FILE = os.path.join(REPO, "config", "simplefin_map.json")
FIRST_SYNC_DAYS = 90

CANONICAL = ["discover_creditcard", "huntington_checking",
             "huntington_hub", "huntington_savings"]
STEM_TO_LABEL = {
    "discover_creditcard": "Discover Card",
    "huntington_checking": "Huntington Checking",
    "huntington_hub": "Huntington Hub",
    "huntington_savings": "Huntington Savings",
}


def claim_setup_token(token):
    claim_url = base64.b64decode(token.strip()).decode()
    req = urllib.request.Request(claim_url, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=30) as resp:
        access_url = resp.read().decode().strip()
    os.makedirs(os.path.dirname(ACCESS_FILE), exist_ok=True)
    with open(ACCESS_FILE, "w") as f:
        f.write(access_url + "\n")
    os.chmod(ACCESS_FILE, 0o600)
    print(f"Access URL saved to {ACCESS_FILE}")
    print("Now run: python3 scripts/simplefin_sync.py")


def get_access_url():
    try:
        with open(ACCESS_FILE) as f:
            return f.read().strip()
    except OSError:
        return None


def fetch_accounts(access_url, start_epoch):
    # access URL embeds credentials: https://user:pass@host/simplefin
    scheme, rest = access_url.split("://", 1)
    if "@" in rest:
        auth, host = rest.rsplit("@", 1)
        url = f"{scheme}://{host}/accounts?start-date={start_epoch}&pending=0"
        creds = base64.b64encode(auth.encode()).decode()
        req = urllib.request.Request(url,
                                     headers={"Authorization": f"Basic {creds}"})
    else:
        req = urllib.request.Request(
            f"{access_url}/accounts?start-date={start_epoch}&pending=0")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def last_dates_by_label():
    try:
        with open(NORM_FILE) as f:
            txs = json.load(f)["transactions"]
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for t in txs:
        out[t["account"]] = max(out.get(t["account"], ""), t["date"])
    return out


def load_or_seed_map(accounts):
    if os.path.exists(MAP_FILE):
        with open(MAP_FILE) as f:
            return json.load(f)
    seed = {"_instructions":
            "Map each SimpleFIN account id to one of: " + ", ".join(CANONICAL),
            "accounts": {}}
    for a in accounts:
        name = f"{a.get('org', {}).get('name', '?')} {a.get('name', '?')}"
        guess = ""
        low = name.lower()
        if "discover" in low:
            guess = "discover_creditcard"
        elif "saving" in low:
            guess = "huntington_savings"
        elif "check" in low:
            guess = "huntington_checking"
        elif "hub" in low:
            guess = "huntington_hub"
        seed["accounts"][a["id"]] = {"name": name, "maps_to": guess}
    with open(MAP_FILE, "w") as f:
        json.dump(seed, f, indent=2)
    return seed


def main(argv):
    if len(argv) >= 3 and argv[1] == "--setup":
        claim_setup_token(argv[2])
        return 0

    access_url = get_access_url()
    if not access_url:
        print("Not set up yet. See the header of this file for the 4 steps")
        print("(create SimpleFIN Bridge account → link banks → --setup TOKEN).")
        return 1

    # Earliest start date we might need across accounts.
    last = last_dates_by_label()
    default_start = datetime.now() - timedelta(days=FIRST_SYNC_DAYS)
    starts = {}
    for stem, label in STEM_TO_LABEL.items():
        if label in last:
            starts[stem] = datetime.strptime(last[label], "%Y-%m-%d") \
                + timedelta(days=1)
        else:
            starts[stem] = default_start
    earliest = min(starts.values())

    print(f"Fetching from SimpleFIN since {earliest.date()}…")
    data = fetch_accounts(access_url, int(earliest.timestamp()))
    for err in data.get("errors", []):
        print(f"  ⚠ SimpleFIN: {err}")
    accounts = data.get("accounts", [])
    if not accounts:
        print("No accounts returned.")
        return 1

    amap = load_or_seed_map(accounts)
    unmapped = [v["name"] for v in amap["accounts"].values()
                if not v.get("maps_to")]
    if unmapped:
        print(f"\nEdit {MAP_FILE} and fill in 'maps_to' for:")
        for n in unmapped:
            print(f"  - {n}")
        print("then re-run this script.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d")
    wrote_any = False
    for a in accounts:
        entry = amap["accounts"].get(a["id"])
        if not entry or not entry.get("maps_to"):
            continue
        stem = entry["maps_to"]
        cutoff = starts.get(stem, default_start).strftime("%Y-%m-%d")
        rows = []
        for t in a.get("transactions", []):
            if t.get("pending"):
                continue
            date = datetime.fromtimestamp(
                t.get("posted") or t.get("transacted_at") or 0
            ).strftime("%Y-%m-%d")
            if date < cutoff:
                continue
            amt = float(t.get("amount", 0))
            desc = (t.get("description") or t.get("payee") or "").strip()
            rows.append([date, desc,
                         f"{-amt:.2f}" if amt < 0 else "",
                         f"{amt:.2f}" if amt > 0 else ""])
        if not rows:
            print(f"  {entry['name']:35s} nothing new")
            continue
        dest = os.path.join(RAW_DIR, f"{stem}_sf_{stamp}.csv")
        with open(dest, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Date", "Description", "Money Out", "Money In"])
            w.writerows(sorted(rows))
        print(f"  {entry['name']:35s} {len(rows):4d} new -> "
              f"{os.path.basename(dest)}")
        wrote_any = True

    if wrote_any:
        print("\n▶ Normalizing…", flush=True)
        return subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", "normalize.py")]
        ).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
