#!/usr/bin/env python3
"""
notify.py — deliver a message to your phone. Used by morning.sh (and anything
else) to send the daily safe-to-spend line beyond the desktop notification.

Reads config/notify.json (git-ignored — copy config/notify.example.json).
Every channel is optional; unset channels are skipped silently, so configure
one or several:

  "imessage"   your phone number (e.g. "+15555551234") or Apple ID email.
               The Mac sends you a real iMessage via Messages.app — free, no
               third party, but Messages must be signed in on this Mac.
  "ntfy_topic" a topic name for https://ntfy.sh — free push notifications;
               install the ntfy app on your iPhone and subscribe to the same
               topic. Pick something long/random (the topic IS the secret,
               and messages transit ntfy's servers).
  "email"      {"to": ..., "user": ..., "app_password": ...} — sends via
               Gmail SMTP. Use an App Password (Google Account → Security →
               2-Step Verification → App passwords), NOT your real password.

Usage:  python3 scripts/notify.py "message text"
        echo "message" | python3 scripts/notify.py
"""

import json
import os
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO, "config", "notify.json")

APPLESCRIPT = '''
on run argv
  set theTarget to item 1 of argv
  set theMsg to item 2 of argv
  tell application "Messages"
    set theService to 1st account whose service type = iMessage
    send theMsg to participant theTarget of theService
  end tell
end run
'''


def send_imessage(target, msg):
    subprocess.run(["osascript", "-e", APPLESCRIPT, target, msg],
                   check=True, capture_output=True, timeout=30)


def send_ntfy(topic, msg):
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}", data=msg.encode(),
        headers={"Title": "Finance Analyzer",
                 "User-Agent": "FinanceAnalyzer/1.0"})
    urllib.request.urlopen(req, timeout=30).read()


def send_email(cfg, msg):
    import smtplib
    from email.message import EmailMessage
    m = EmailMessage()
    m["Subject"] = "💸 Safe to spend today"
    m["From"] = cfg["user"]
    m["To"] = cfg["to"]
    m.set_content(msg)
    with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"),
                      int(cfg.get("smtp_port", 587)), timeout=30) as s:
        s.starttls()
        s.login(cfg["user"], cfg["app_password"])
        s.send_message(m)


def main():
    msg = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if not msg:
        print("notify.py: no message given", file=sys.stderr)
        return 1
    try:
        with open(CONF, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        print("notify.py: no config/notify.json — nothing to send "
              "(copy config/notify.example.json to set up)")
        return 0

    sent, failed = [], []
    if cfg.get("imessage"):
        try:
            send_imessage(cfg["imessage"], msg)
            sent.append(f"iMessage → {cfg['imessage']}")
        except Exception as e:
            failed.append(f"iMessage: {e}")
    if cfg.get("ntfy_topic"):
        try:
            send_ntfy(cfg["ntfy_topic"], msg)
            sent.append(f"ntfy → {cfg['ntfy_topic']}")
        except Exception as e:
            failed.append(f"ntfy: {e}")
    if isinstance(cfg.get("email"), dict) and cfg["email"].get("to"):
        try:
            send_email(cfg["email"], msg)
            sent.append(f"email → {cfg['email']['to']}")
        except Exception as e:
            failed.append(f"email: {e}")

    for s in sent:
        print(f"  sent {s}")
    for f_ in failed:
        print(f"  ⚠ {f_}", file=sys.stderr)
    return 1 if (failed and not sent) else 0


if __name__ == "__main__":
    raise SystemExit(main())
