"""
categorize.py — Classification engine for transactions.

Two-layer design, because real bank/card exports already ship a coarse
"Category" column we can lean on:

  1. classify(description, bank_category, amount) -> {category, kind, ...}
     The full classifier. It (a) detects INTERNAL money movement (account
     transfers, credit-card payments, brokerage moves, P2P) so it never gets
     counted as real income/spend; (b) detects income; (c) trusts the
     institution's own category where useful; (d) falls back to keyword rules.

  2. keyword_category(description) / categorize(description)
     Pure keyword matching on the description text. Used to refine rows the
     bank labeled vaguely ("Other", "Merchandise", "Services") and as the
     browser dashboard's logic.

KIND is the most important output for budgeting:
  - "income"   real money in  (paychecks, interest, cashback, refunds)
  - "spend"    real money out (everything you actually consume)
  - "internal" money you moved between your own pots, or paid your card with —
               EXCLUDED from income & spend so cash flow isn't double-counted.

Keep the keyword rules / kind logic in sync with the mirrored block in
dashboard.html so the UI and the Python pipeline always agree.
"""

import json
import os
import re

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "config")
_OVERRIDES_JSON = os.path.join(_CONFIG_DIR, "overrides.json")
_RULES_JSON = os.path.join(_CONFIG_DIR, "rules.json")
_overrides_cache = None
_user_rules_cache = None


def _user_rules():
    """Personal keyword rules from config/rules.json (git-ignored).

    Format: {"rules": [{"category": "Groceries",
                        "keywords": ["kroger", "fresh thyme"]}]}
    Checked BEFORE the built-in CATEGORY_RULES, so they win ties — use them
    for local merchants or to re-route a keyword without editing this file.
    Copy config/rules.example.json to config/rules.json to start.
    """
    global _user_rules_cache
    if _user_rules_cache is None:
        try:
            with open(_RULES_JSON, encoding="utf-8") as f:
                _user_rules_cache = [
                    (r["category"], [k.lower() for k in r.get("keywords", [])])
                    for r in json.load(f).get("rules", [])]
        except (OSError, ValueError, KeyError):
            _user_rules_cache = []
    return _user_rules_cache


def _overrides():
    """Personal one-off corrections from config/overrides.json (git-ignored).

    Each entry: {"description": "...", "amount": -5600.0 (optional),
                 "category": "...", "kind": "..." (optional)}.
    Matches on the normalized (lowercased, whitespace-collapsed) description,
    plus the exact final amount when given.
    """
    global _overrides_cache
    if _overrides_cache is None:
        try:
            with open(_OVERRIDES_JSON, encoding="utf-8") as f:
                _overrides_cache = json.load(f).get("overrides", [])
        except (OSError, ValueError):
            _overrides_cache = []
    return _overrides_cache

# ---------------------------------------------------------------------------
# Keyword rules (description -> spending category), priority order.
# ---------------------------------------------------------------------------
CATEGORY_RULES = [
    ("Subscriptions & Software", [
        "netflix", "spotify", "hulu", "disney", "youtube premium", "youtubepre",
        "apple.com/bill", "apple.com", "itunes", "icloud", "google storage",
        "google one", "adobe", "microsoft", "msft", "office 365", "openai",
        "anthropic", "claude", "chatgpt", "github", "notion", "dropbox",
        "amazon prime", "prime video", "hbo", "max.com", "paramount",
        "peacock", "audible", "patreon", "substack", "canva", "1password",
        "linkedin", "nordvpn", "expressvpn", "playstation plus", "xbox game",
        "nintendo online", "twitch", "discord nitro", "onlyfans",
    ]),
    ("Utilities & Phone", [
        "at&t", "att*", "verizon", "t-mobile", "tmobile", "sprint",
        "comcast", "xfinity", "spectrum", "cox comm", "centurylink",
        "duke energy", "aep", "columbia gas", "first energy", "firstenergy",
        "toledo edison", "consumers energy", "dte", "national grid",
        "electric", "water dept", "water util", "sewer", "natural gas",
        "energy", "utility", "internet", "broadband", "google fiber",
    ]),
    ("Housing & Rent", [
        "rent", "apartment", "apartments", "leasing", "property mgmt",
        "property management", "landlord", "mortgage", "hoa", "realty",
        "residential", "the flats", "the district", "campus village",
    ]),
    ("Insurance", [
        "geico", "progressive", "state farm", "allstate", "liberty mutual",
        "nationwide ins", "usaa", "insurance", "ins prem", "policy",
        "metlife", "aetna", "anthem", "cigna", "humana", "unitedhealth",
    ]),
    ("Healthcare", [
        "pharmacy", "cvs", "walgreens", "rite aid", "doctor", "dental",
        "dentist", "hospital", "clinic", "medical", "health", "urgent care",
        "optometr", "vision", "labcorp", "quest diag", "copay", "physician",
    ]),
    ("Groceries", [
        "kroger", "meijer", "aldi", "whole foods", "wholefds", "trader joe",
        "walmart", "wal-mart", "wm super", "costco", "sam's club", "sams club",
        "giant eagle", "food lion", "safeway", "publix", "wegmans", "heb",
        "h-e-b", "sprouts", "fresh thyme", "marc's", "marcs", "grocery",
        "supermarket", "market basket", "save a lot", "save-a-lot",
        "conv. store", "conv store", "macs conv", "circle k",
    ]),
    ("Dining & Food", [
        "restaurant", "mcdonald", "chipotle", "starbucks", "dunkin",
        "taco bell", "wendy", "burger king", "burgerking", "pizza",
        "doordash", "ubereats", "uber eats", "grubhub", "postmates",
        "cafe", "coffee", "grill", "kitchen", "chick-fil-a", "chickfila",
        "chick fil a", "panera", "subway", "five guys", "raising cane",
        "canes", "jimmy john", "jersey mike", "qdoba", "panda express",
        "sonic", "arby", "dairy queen", "kfc", "popeyes", "wingstop",
        "buffalo wild", "bdubs", "ihop", "denny", "waffle house", "diner",
        "tavern", "brewing", "brewery", "pub", "eatery", "bistro", "deli",
        "donut", "bakery", "ice cream", "smoothie", "juice", "bar &",
        "olive garden", "texas roadhouse", "applebee", "chili's", "chilis",
        "red lobster", "longhorn", "outback", "cracker barrel", "cheesecake",
        "red robin", "noodles & co", "noodles and co", "first watch",
        "steakhouse", "cantina", "taqueria", "sushi", "thai", "ramen",
        "packo",
    ]),
    ("Gas & Fuel", [
        "shell", "bp ", "bp#", "exxon", "mobil ", "exxonmobil", "marathon",
        "speedway", "sunoco", "chevron", "circlek", "valero", "citgo",
        "phillips 66", "kwik", "sheetz", "wawa", "gas station", "fuel",
        "gasoline", "pilot", "loves travel", "love's", "racetrac", "get go", "getgo",
    ]),
    ("Transport", [
        "uber", "lyft", "parking", "park mobile", "parkmobile", "toll",
        "ezpass", "e-zpass", "transit", "metro", "rta", "bus ", "amtrak",
        "rental car", "enterprise rent", "hertz", "avis", "budget rent",
        "scooter", "bird", "lime", "bike share",
    ]),
    ("Auto & Vehicle", [
        "autozone", "o'reilly", "oreilly", "advance auto", "napa auto",
        "jiffy lube", "valvoline", "midas", "firestone", "discount tire",
        "tire", "mechanic", "auto repair", "car wash", "carwash",
        "dealership", "carmax", "dmv", "bmv", "registration", "smog",
    ]),
    ("Travel", [
        "airline", "airlines", "delta air", "united air", "american air",
        "southwest air", "spirit air", "frontier air", "jetblue", "alaska air",
        "hotel", "motel", "marriott", "hilton", "hyatt", "holiday inn",
        "best western", "airbnb", "vrbo", "expedia", "booking.com", "priceline",
        "kayak", "airport", "tsa pre", "global entry", "resort", "lodging",
    ]),
    ("Education", [
        "tuition", "university", "college", "bookstore", "udemy", "coursera",
        "edx", "chegg", "pearson", "mcgraw", "cengage", "school", "campus",
        "student loan", "fafsa", "scholarship", "registrar", "bowling green",
        "bgsu", "ohio state", "owens comm",
    ]),
    ("Entertainment", [
        "cinema", "movie", "amc ", "regal", "cinemark", "theatre", "theater",
        "steam games", "steampowered", "playstation", "xbox", "nintendo",
        "epic games", "riot games", "ticketmaster", "stubhub", "live nation",
        "concert", "eventbrite", "fandango", "bowling lan", "arcade", "golf",
        "peloton", "casino", "pride", "kalshi", "draftkings", "fanduel",
        "betmgm", "prizepicks",
    ]),
    ("Donations", [
        "salvation army", "goodwill", "red cross", "gofundme", "donation",
        "st. jude", "st jude", "unicef", "charity", "nonprofit",
    ]),
    ("Health & Fitness", [
        "gym", "fitness", "planet fit", "la fitness", "anytime fitness",
        "crunch", "yoga", "crossfit", "rec center", "recreation",
    ]),
    ("Shopping", [
        "amazon", "amzn", "target", "best buy", "bestbuy", "ebay", "etsy",
        "nike", "adidas", "lululemon", "apple store", "microcenter",
        "micro center", "home depot", "lowe's", "lowes", "menards", "ikea",
        "wayfair", "old navy", "gap ", "h&m", "zara", "macy", "nordstrom",
        "tj maxx", "tjmaxx", "marshalls", "ross stores", "kohl", "ulta",
        "sephora", "gamestop", "barnes", "dick's sport", "dicks sport",
        "five below", "dollar gen", "dollar tree", "family dollar", "shein",
        "temu", "wish.com", "store", "shop", "boutique", "vending",
        "paypal", "stockx", "goat ", "mercari", "poshmark", "depop",
    ]),
]

# ---------------------------------------------------------------------------
# Bank/card "Category" column -> our taxonomy.
# REFINE means: try keyword rules first, then fall back to BANK_DEFAULT.
# ---------------------------------------------------------------------------
REFINE = "__REFINE__"
BANK_CATEGORY_MAP = {
    # food
    "Fast Food": "Dining & Food", "Restaurants": "Dining & Food",
    "Coffee Shop": "Dining & Food", "Dining": "Dining & Food",
    # fuel / auto / transport
    "Gasoline": "Gas & Fuel",
    "Parking": "Transport", "Public Transportation": "Transport",
    "Auto Parts & Service": "Auto & Vehicle", "Automotive": "Auto & Vehicle",
    # groceries
    "Groceries": "Groceries", "Supermarkets": "Groceries",
    # health / personal
    "Fitness": "Health & Fitness", "Pharmacy": "Healthcare",
    "Medical Services": "Healthcare", "Hair": "Personal Care",
    # shopping
    "Electronics": "Shopping", "Clothing": "Shopping",
    "Books & Magazines": "Shopping", "Merchandise": REFINE,
    # entertainment / travel
    "Hobbies": "Entertainment", "Admission & Tickets": "Entertainment",
    "Travel/ Entertainment": "Entertainment", "Travel": "Travel",
    # home
    "Home Improvement": "Home & Garden", "Lawn & Garden": "Home & Garden",
    # education
    "School Fee": "Education", "Education": "Education",
    # taxes / gov / services
    "Tax": "Taxes", "Government Services": "Taxes",
    "Accounting Fee": "Services", "Services": REFINE,
    # internal (also caught earlier, mapped here for safety)
    "Transfer": "Transfers", "Retirement": "Investments",
    # catch-all
    "Other": REFINE,
}
BANK_DEFAULT = {"Other": "Uncategorized", "Merchandise": "Shopping",
                "Services": "Services"}

# Category -> kind membership
INCOME_CATS = {"Income", "Interest", "Cashback & Rewards", "Refunds",
               "Financial Aid", "Deposits", "Other Income"}
INTERNAL_CATS = {"Transfers", "Credit Card Payment", "P2P Transfer",
                 "Investments"}

ALL_SPEND_CATEGORIES = [
    "Groceries", "Dining & Food", "Gas & Fuel", "Transport", "Auto & Vehicle",
    "Shopping", "Subscriptions & Software", "Utilities & Phone",
    "Housing & Rent", "Insurance", "Healthcare", "Personal Care",
    "Entertainment", "Health & Fitness", "Travel", "Education",
    "Home & Garden", "Taxes", "Fees & Interest", "Cash & ATM", "Services",
    "Donations", "Uncategorized",
]
ALL_CATEGORIES = (ALL_SPEND_CATEGORIES + sorted(INCOME_CATS)
                  + sorted(INTERNAL_CATS))


def _norm(text):
    return " " + re.sub(r"\s+", " ", (text or "").lower()).strip() + " "


def keyword_category(description):
    """Pure keyword match -> a spending category, or 'Uncategorized'."""
    t = _norm(description)
    for category, keywords in (*_user_rules(), *CATEGORY_RULES):
        for kw in keywords:
            if kw in t:
                return category
    return "Uncategorized"


def refine_spend_category(description):
    """Resolve a spend category for vaguely-labeled rows.

    Catches cash/ATM and fees (which banks often bury in 'Other') before
    falling back to keyword matching.
    """
    t = _norm(description)
    if any(k in t for k in ("atm", "cash withdrawal", "cash advance",
                            "withdrawal")):
        return "Cash & ATM"
    if any(k in t for k in ("overdraft", "service charge", "finance charge",
                            "interest charged", "transaction fee",
                            "withdrawal fee", "late fee", "annual fee",
                            "nsf", " fee ")):
        return "Fees & Interest"
    return keyword_category(description)


def kind_of(category):
    if category in INCOME_CATS:
        return "income"
    if category in INTERNAL_CATS:
        return "internal"
    return "spend"


def classify(description, bank_category="", amount=0.0):
    """Full classification. Returns dict(category, kind).

    `amount` MUST be the FINAL normalized amount (negative = money out).
    Logic: (1) detect internal money movement (either direction); then the
    sign decides — money IN is income, money OUT is spend.
    """
    t = _norm(description)
    bc = (bank_category or "").strip()

    # 0) One-off overrides (config/overrides.json, git-ignored) -------------
    # e.g. a big cash withdrawal that was really a car purchase.
    for o in _overrides():
        if t.strip() == _norm(o.get("description", "")).strip() and (
                "amount" not in o or amount == o["amount"]):
            return {"category": o["category"],
                    "kind": o.get("kind") or kind_of(o["category"])}

    # 1) INTERNAL money movement (either direction) ------------------------
    if "internet tfr" in t or "internal transfer" in t or "online transfer" in t:
        return {"category": "Transfers", "kind": "internal"}
    if any(k in t for k in ("schwab", "moneylink", "brokerage", "e*trade",
                            "etrade", "fidelity", "vanguard", "robinhood",
                            "coinbase", "wealthfront", "betterment")):
        return {"category": "Investments", "kind": "internal"}
    if bc in ("Credit Card Payment", "Payments and Credits", "Retirement"):
        cat = "Investments" if bc == "Retirement" else "Credit Card Payment"
        return {"category": cat, "kind": "internal"}
    if ("discover" in t or "credit card" in t) and any(
            k in t for k in ("payment", "e-payment", "epayment", "directpay",
                             "autopay")):
        return {"category": "Credit Card Payment", "kind": "internal"}
    # P2P money movement (incl. "PURCHASE VENMO *NAME"). analyze.py reports net.
    if ("paypal inst xfer" in t or "inst xfer" in t or "apple cash" in t
            or "venmo" in t or "moneysend" in t or "bank xfer" in t
            or "cash app" in t or "sent money" in t or "zelle" in t):
        return {"category": "P2P Transfer", "kind": "internal"}

    # 2) MONEY IN -> income -------------------------------------------------
    if amount > 0:
        if bc == "Paycheck" or any(k in t for k in ("payroll", "dirdep",
                                   "dir dep", "direct dep", "direct deposit",
                                   "wages", "salary")):
            return {"category": "Income", "kind": "income"}
        if bc == "Interest" or "interest payment" in t or "interest paid" in t:
            return {"category": "Interest", "kind": "income"}
        if (bc == "Awards and Rebate Credits" or "cashback" in t
                or "cash back" in t or "redemption" in t or "reward" in t):
            return {"category": "Cashback & Rewards", "kind": "income"}
        if any(k in t for k in ("bowling green", "bgsu", "financial aid",
                                "disburse", "fin aid", "refund check")):
            return {"category": "Financial Aid", "kind": "income"}
        if any(k in t for k in ("refund", "merchandise ret", "return",
                                "reversal", "credit voucher")):
            return {"category": "Refunds", "kind": "income"}
        if any(k in t for k in ("deposit", "mobile check", "withdrawal")):
            return {"category": "Deposits", "kind": "income"}
        return {"category": "Other Income", "kind": "income"}

    # 3) MONEY OUT -> spend -------------------------------------------------
    if bc in BANK_CATEGORY_MAP:
        mapped = BANK_CATEGORY_MAP[bc]
        if mapped == REFINE:
            r = refine_spend_category(description)
            cat = r if r != "Uncategorized" else BANK_DEFAULT.get(bc, "Shopping")
        else:
            cat = mapped
        # bank cat could itself be internal (Transfer/Retirement) on outflow
        return {"category": cat, "kind": kind_of(cat)}

    cat = refine_spend_category(description)
    return {"category": cat, "kind": kind_of(cat)}


def categorize(description):
    """Back-compat: description-only category (no bank hint)."""
    return classify(description, "", -1.0)["category"]


if __name__ == "__main__":
    samples = [
        ("INTERNET TFR TO CHECKING", "Transfer", -500),
        ("74128 TONY PACKO DIRDEP", "Other", 806.53),
        ("INNOSOURCE INC PAYROLL", "Paycheck", 500),
        ("INTEREST PAYMENT", "Interest", 31.66),
        ("DISCOVER E-PAYMENT", "Credit Card Payment", -1200),
        ("PAYPAL INST XFER", "Other", -8.61),
        ("PURCHASE APPLE CASH SENT MONEY", "Other", -10),
        ("SCHWAB BROKERAGE MONEYLINK", "Other", -300),
        ("PURCHASE ONLYFANS.COM*A", "Other", -9.99),
        ("Bowling Green St ACH", "Other", -250),
        ("RED ROBIN MAUMEE", "Restaurants", -20.56),
        ("LOVE'S #0356", "Gasoline", -87.54),
        ("AMAZON MKTPL*RS3F59GU2", "Merchandise", -34.0),
        ("HUNTINGTON ATM CASH WITHDRAWAL", "Other", -60),
    ]
    for d, bc, a in samples:
        r = classify(d, bc, a)
        print(f"{r['kind']:9s} {r['category']:24s} <- [{bc}] {d}")
