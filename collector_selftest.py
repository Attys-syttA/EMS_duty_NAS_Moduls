#!/bin/python3
"""
Collector Self-Test for EMS Duty NAS environment
-----------------------------------------------
Létrehoz teszthibákat a bot.log-ban és ellenőrzi,
hogy a log_collector_NAS_v2.py reagál-e.
"""

import time
import json
from pathlib import Path
from datetime import datetime

# Forwarding shim to moved script under EMS_Duty_Moduls
REAL = Path(__file__).resolve().parent / "EMS_Duty_Moduls" / "scripts" / "collector_selftest.py"
if REAL.exists():
    import runpy
    runpy.run_path(str(REAL), run_name="__main__")
    raise SystemExit(0)
ROOT = Path("/volume1/homes/Attila_NAS_System/EMS_Duty")
BOT_LOG = ROOT / "logs" / "bot.log"
COLLECTOR_LOG = ROOT / "logs" / "error_alerts.log"
DM_QUEUE = ROOT / "pending_dm.json"

print("=== EMS Duty Collector Self-Test ===")
print(f"Időpont: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("Hely: ", ROOT)

# 1️⃣ Tesztsorok létrehozása
entries = [
    "| TEST | exception: simulated critical test error",
    "| TEST | error: simulated warning test message",
    "| TEST | env_update: this should be ignored",
]

with open(BOT_LOG, "a", encoding="utf8") as f:
    for line in entries:
        msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {line}\n"
        f.write(msg)
        print("➡️  Hozzáadva a bot.log-hoz:", line)

print("\nVárakozás a collector feldolgozására (60 mp)...\n")
time.sleep(60)

# 2️⃣ Collector log elemzése
if COLLECTOR_LOG.exists():
    text = COLLECTOR_LOG.read_text(errors="ignore")
    print("=== Collector észlelt hibák a legutóbbi percekben ===")
    for line in text.splitlines()[-10:]:
        print(line)
else:
    print("❌ Nincs collector log (error_alerts.log).")

# 3️⃣ DM puffer ellenőrzése
if DM_QUEUE.exists():
    try:
        dm_data = json.loads(DM_QUEUE.read_text())
        print(f"\n📩 DM puffer talált ({len(dm_data)} üzenet):")
        for d in dm_data[-3:]:
            print("-", d[:80], "...")
    except Exception as e:
        print("⚠️  DM puffer olvasási hiba:", e)
else:
    print("\n✅ Nincs függő DM puffer — collector valószínűleg elküldte az értesítést.")

print("\n=== Teszt vége ===")
