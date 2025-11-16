#!/bin/python3
"""
EMS Duty Log Collector – NAS v5
--------------------------------------
• Python 3.8 kompatibilis
• Anti-spam logika: csak új hibák után küld értesítést
• collector_state.json: last_checked + last_reported
• .env-ből olvasható intervallumok (DM és ADMIN)
• Hibák kategorizálása (CRITICAL / WARNING)
• INFO/DEBUG prefix-szűrés bővítve
• Restart-figyelés: csak hibás újrainduláskor DM
"""

import os, json, time, datetime, requests
from pathlib import Path

# ------------------------------
# 1️⃣ Alapbeállítások
# ------------------------------
# Forwarding shim to moved script under EMS_Duty_Moduls
REAL = Path(__file__).resolve().parent / "EMS_Duty_Moduls" / "scripts" / "log_collector_NAS.py"
if REAL.exists():
    import runpy
    runpy.run_path(str(REAL), run_name="__main__")
    raise SystemExit(0)
ROOT = Path("/volume1/homes/Attila_NAS_System/EMS_Duty")
LOG = ROOT / "logs" / "bot.log"
STATE_FILE = ROOT / "collector_state.json"
REASON_FILE = ROOT / "restart_reason.txt"
DM_QUEUE = ROOT / "pending_dm.json"
ENV = ROOT / ".env"

DISCORD_API = "https://discord.com/api/v10"

CRITICAL_KEYS = ["exception", "traceback", "fatal", "critical"]
WARNING_KEYS  = ["error", "warning", "rate limited"]
IGNORE_KEYS   = ["env_update", "file_update", "manual", "restart initial"]
IGNORE_PREFIXES = [
    "[info", "[debug", "[notice", "[startup", "[ok]",
    "gateway:", "connected to gateway", "session id",
    "login using static token", "ready", "shard id"
]

DM_INTERVAL = 300
ADMIN_INTERVAL = 600
QUIET_START = datetime.time(0, 0)
QUIET_END = datetime.time(6, 0)
TOKEN = ADMIN = DM_ID = None

def _parse_time(s):
    try:
        h, m = s.strip().split(":")
        return datetime.time(int(h), int(m))
    except Exception:
        return datetime.time(0, 0)

def load_env():
    global ADMIN, DM_ID, TOKEN, DM_INTERVAL, ADMIN_INTERVAL, QUIET_START, QUIET_END
    env = {}
    try:
        with open(ENV, encoding="utf8") as f:
            for raw in f:
                if "=" in raw:
                    k, v = raw.strip().split("=", 1)
                    env[k.strip()] = v.strip()
    except Exception:
        pass
    ADMIN = env.get("ADMIN_CHANNEL_ID")
    DM_ID = env.get("WATCHDOG_DM_USER_ID")
    TOKEN = env.get("DISCORD_TOKEN")
    DM_INTERVAL = int(env.get("DM_ALERT_INTERVAL", 300))
    ADMIN_INTERVAL = int(env.get("ADMIN_ALERT_INTERVAL", 600))
    if env.get("QUIET_HOURS_START"):
        QUIET_START = _parse_time(env["QUIET_HOURS_START"])
    if env.get("QUIET_HOURS_END"):
        QUIET_END = _parse_time(env["QUIET_HOURS_END"])

# ------------------------------
# 2️⃣ Segédfüggvények (quiet / DM / admin)
# ------------------------------
def quiet_hours():
    now = datetime.datetime.now().time()
    if QUIET_START < QUIET_END:
        return QUIET_START <= now < QUIET_END
    return now >= QUIET_START or now < QUIET_END

def queue_dm(text):
    arr = []
    if DM_QUEUE.exists():
        try:
            arr = json.loads(DM_QUEUE.read_text())
        except Exception:
            arr = []
    arr.append(text)
    DM_QUEUE.write_text(json.dumps(arr, ensure_ascii=False, indent=2))

def send_dm(text):
    if not DM_ID or not TOKEN:
        return
    if quiet_hours():
        queue_dm(text)
        return
    try:
        r = requests.post(f"{DISCORD_API}/users/@me/channels",
                          headers={"Authorization": "Bot " + TOKEN},
                          json={"recipient_id": DM_ID}, timeout=3)
        ch = (r.json() or {}).get("id")
        if ch:
            requests.post(f"{DISCORD_API}/channels/{ch}/messages",
                          headers={"Authorization": "Bot " + TOKEN},
                          json={"content": text[:1900]}, timeout=3)
    except Exception:
        queue_dm(text)

def send_admin(text):
    if not ADMIN or not TOKEN:
        return
    try:
        requests.post(f"{DISCORD_API}/channels/{ADMIN}/messages",
                      headers={"Authorization": "Bot " + TOKEN},
                      json={"content": text[:1900]}, timeout=3)
    except Exception:
        pass

def flush_dm_queue():
    if quiet_hours() or not DM_QUEUE.exists():
        return
    try:
        arr = json.loads(DM_QUEUE.read_text())
    except Exception:
        DM_QUEUE.unlink(missing_ok=True)
        return
    for m in arr:
        send_dm(m)
    DM_QUEUE.unlink(missing_ok=True)

# ------------------------------
# 3️⃣ Log elemzés és állapotkezelés
# ------------------------------
def analyze_logs():
    summary = {"critical": 0, "warning": 0}
    last_time = None
    if not LOG.exists():
        return summary, last_time

    last_checked = None
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as sf:
                state = json.load(sf)
                last_checked = state.get("last_checked")
        except Exception:
            pass

    try:
        text = LOG.read_text(errors="ignore")
    except Exception:
        return summary, last_time

    for line in text.splitlines()[-500:]:
        if last_checked and line[:19].isdigit() and line[:19] <= last_checked:
            continue
        lower = line.lower()
        if any(k in lower for k in IGNORE_KEYS): continue
        if any(p in lower for p in IGNORE_PREFIXES): continue
        if any(k in lower for k in CRITICAL_KEYS):
            summary["critical"] += 1
        elif any(k in lower for k in WARNING_KEYS):
            summary["warning"] += 1
        if "2025-" in line or ":" in line:
            last_time = line.strip()

    # mentés: last_checked frissítése
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as sf:
            state = json.load(sf)
    except Exception:
        state = {}
    state["last_checked"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATE_FILE, "w", encoding="utf-8") as sf:
        json.dump(state, sf)

    return summary, last_time

# ------------------------------
# 4️⃣ Jelentések
# ------------------------------
def send_summaries(summary, last_time):
    total = summary["critical"] + summary["warning"]
    if total == 0:
        return
    msg_dm = (f"❗ Új hibák az elmúlt {DM_INTERVAL//60} percben\n"
              f"Fájl: bot.log\n"
              f"Kritikus: {summary['critical']} | Figyelmeztetés: {summary['warning']}\n")
    msg_admin = (f"📢 Rendszerfigyelő jelentés\n"
                 f"Fájl: bot.log\n"
                 f"Új hibák: {total} ({summary['critical']} kritikus, {summary['warning']} figyelmeztetés)\n")
    if last_time:
        msg_dm += f"Utolsó esemény: {last_time}\n"
        msg_admin += f"Utolsó hiba: {last_time}\n"
    msg_dm += "Ellenőrizd: /EMS_Duty/logs/bot.log"
    msg_admin += f"(Jelentés ideje: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')})"
    send_dm(msg_dm)
    send_admin(msg_admin)

# ------------------------------
# 5️⃣ Restart-figyelés és főciklus (anti-spam logika)
# ------------------------------
def check_restart_reason():
    if not REASON_FILE.exists(): return
    try:
        reason = REASON_FILE.read_text().strip().lower()
    except Exception:
        return
    if reason in ("crash", "core_crash"):
        send_dm(f"🔁 Bot újraindítva hibából eredően.\nIndok: {reason}")

def main():
    load_env()
    while True:
        flush_dm_queue()
        summary, last_time = analyze_logs()

        # állapotfájl beolvasás
        last_reported = None
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as sf:
                    state = json.load(sf)
                    last_reported = state.get("last_reported")
            except Exception:
                pass

        # új hiba? csak akkor küld jelentést
        if last_time and (not last_reported or last_time > last_reported):
            send_summaries(summary, last_time)
            # update last_reported
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as sf:
                    state = json.load(sf)
            except Exception:
                state = {}
            state["last_reported"] = last_time
            with open(STATE_FILE, "w", encoding="utf-8") as sf:
                json.dump(state, sf)

        check_restart_reason()
        time.sleep(60)

if __name__ == "__main__":
    main()
