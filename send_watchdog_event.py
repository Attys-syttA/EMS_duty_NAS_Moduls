#!/usr/bin/env python3
"""
send_watchdog_event.py — egyszerű segéd, amivel a watchdog eseményfájlt létrehozhatod
Használat:
  python send_watchdog_event.py --action restart --reason "hotfix"
"""
import json
import argparse
from pathlib import Path
from runpy import run_path

# Forwarding shim — the real implementation lives in EMS_Duty_Moduls/scripts
real = Path(__file__).resolve().parent / "EMS_Duty_Moduls" / "scripts" / "send_watchdog_event.py"
if real.exists():
  run_path(str(real), run_name="__main__")
else:
  raise SystemExit("send_watchdog_event helper not found; ensure EMS_Duty_Moduls/scripts/send_watchdog_event.py exists")

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
