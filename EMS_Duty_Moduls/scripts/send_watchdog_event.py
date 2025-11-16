#!/usr/bin/env python3
"""
send_watchdog_event.py — egyszerű segéd, amivel a watchdog eseményfájlt létrehozhatod
Használat:
  python EMS_Duty_Moduls/scripts/send_watchdog_event.py --action restart --reason "hotfix"
"""
import json
import argparse
from pathlib import Path

# Make sure the event is written to the repository root 'events/' folder (same as watchdog expects)
ROOT = Path(__file__).resolve().parents[1]
EVENTS_DIR = ROOT / "events"
EVENT_FILE = EVENTS_DIR / "watchdog_event.json"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trigger watchdog event (write JSON into events/)")
    parser.add_argument("--action", type=str, choices=["restart"], required=True, help="Action to request (restart)")
    parser.add_argument("--reason", type=str, default="manual_event", help="Optional free-form reason")
    args = parser.parse_args()

    EVENTS_DIR.mkdir(exist_ok=True)
    payload = {"action": args.action, "reason": args.reason}

    with open(EVENT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote event to {EVENT_FILE}: {payload}")
