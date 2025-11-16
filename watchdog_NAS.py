#!/bin/python3
"""
EMS Duty Watchdog – Synology NAS version
Monitors bot file/env changes and restarts on crash or update
"""

import os, subprocess, time, json, requests, datetime
from pathlib import Path

#------------------------------
# Alapútvonalak és konstansok
#------------------------------
ROOT = Path("/volume1/homes/Attila_NAS_System/EMS_Duty")
ENV = ROOT / ".env"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

WATCHDOG_LOG = LOG_DIR / "watchdog.log"
BOT_LOG = LOG_DIR / "bot.log"
PENDING_DM = ROOT / "pending_dm.json"
REASON_FILE = LOG_DIR / "restart_reason.txt"

# Bot főfájl betöltése .env-ből, ha van
BOT = Path(os.getenv("BOT_FILE", "EMS_Duty_NAS_251114.py"))
BOT = ROOT / BOT
BOT_EXEC = "/bin/python3"  # Synology python

ADMIN_CHANNEL = None
DM_TARGET = None

QUIET_START = datetime.time(0, 0)
QUIET_END = datetime.time(6, 0)

DISCORD_API = "https://discord.com/api/v10"

bot_proc = None
bot_ts = None
env_ts = None

#------------------------------
# Log Collector paraméterek
#------------------------------
LOG_COLLECTOR_SCRIPT = ROOT / "EMS_Duty_Moduls" / "scripts" / "log_collector_NAS.py"
log_collector_proc = None
EVENTS_DIR = ROOT / "events"
EVENTS_DIR.mkdir(exist_ok=True)
EVENT_FILE = EVENTS_DIR / "watchdog_event.json"


#------------------------------
# Naplózás és forgatás
#------------------------------
def log(msg):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
        f.write(f"{now} | WATCHDOG | {msg}\n")
    print(msg)


def rotate_if_big(path, limit=500_000):
    if path.exists() and path.stat().st_size > limit:
        path.rename(path.with_suffix(".log.old"))


#------------------------------
# ENV betöltés és beállítás
#------------------------------
def _parse_time(s: str) -> datetime.time:
    h, m = s.strip().split(":")
    return datetime.time(int(h), int(m))


def load_env_all():
    global ADMIN_CHANNEL, DM_TARGET, QUIET_START, QUIET_END, BOT

    env = {}
    try:
        with open(ENV, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except:
        log("WARNING: Unable to read .env")

    ADMIN_CHANNEL = env.get("ADMIN_CHANNEL_ID")
    DM_TARGET = env.get("WATCHDOG_DM_USER_ID")

    token = env.get("DISCORD_TOKEN")
    if token:
        os.environ["DISCORD_TOKEN"] = token

    if env.get("QUIET_HOURS_START"):
        QUIET_START = _parse_time(env["QUIET_HOURS_START"])
    if env.get("QUIET_HOURS_END"):
        QUIET_END = _parse_time(env["QUIET_HOURS_END"])

    if env.get("BOT_FILE"):
        BOT = ROOT / env["BOT_FILE"]
    else:
        versions = sorted(
            ROOT.glob("EMS_Duty_NAS_*.py"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        BOT = versions[0] if versions else (ROOT / "EMS_Duty_NAS.py")

    log(f"ENV loaded | admin={ADMIN_CHANNEL} dm={DM_TARGET} quiet={QUIET_START}-{QUIET_END} bot={BOT.name}")


#------------------------------
# Csendes időszakok kezelése
#------------------------------
def quiet_hours() -> bool:
    now = datetime.datetime.now().time()
    if QUIET_START < QUIET_END:
        return QUIET_START <= now < QUIET_END
    return now >= QUIET_START or now < QUIET_END


#------------------------------
# DM Queue / Flush kezelése
#------------------------------
def dm_queue(text):
    arr = []
    if PENDING_DM.exists():
        try:
            arr = json.loads(PENDING_DM.read_text())
        except:
            arr = []
    arr.append(text)
    PENDING_DM.write_text(json.dumps(arr, ensure_ascii=False, indent=2))


def flush_dm_queue():
    if quiet_hours() or not PENDING_DM.exists():
        return

    try:
        arr = json.loads(PENDING_DM.read_text())
    except:
        PENDING_DM.unlink(missing_ok=True)
        return

    for m in arr:
        # opcionális: DM vagy admin üzenetküldés
        pass

    PENDING_DM.unlink(missing_ok=True)


#------------------------------
# Bot vezérlés / újraindítás
#------------------------------
def write_reason(reason_key: str):
    """Map watchdog events → bot readable restart reason"""
    REASON_FILE.write_text(reason_key)


def start_bot(reason_key):
    global bot_proc, bot_ts, env_ts
    write_reason(reason_key)

    log_file = open(BOT_LOG, "a", encoding="utf-8", buffering=1)
    bot_proc = subprocess.Popen(
        [BOT_EXEC, str(BOT)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    bot_ts = BOT.stat().st_mtime
    env_ts = ENV.stat().st_mtime if ENV.exists() else None
    log(f"Bot started ({reason_key})")


def restart_bot(reason_key):
    global bot_proc
    if bot_proc:
        bot_proc.terminate()
        try:
            bot_proc.wait(timeout=5)
        except:
            bot_proc.kill()
    start_bot(reason_key)


#------------------------------
# Log Collector indítás / újraindítás
#------------------------------
def start_log_collector():
    """Indítja a log_collector_NAS.py-t, ha létezik"""
    global log_collector_proc
    if not LOG_COLLECTOR_SCRIPT.exists():
        log("[WARN] log_collector_NAS.py nem található – logfigyelés kikapcsolva.")
        return None

    exe = BOT_EXEC
    log(f"Log collector indítása: {LOG_COLLECTOR_SCRIPT.name}")
    log_collector_proc = subprocess.Popen(
        [exe, str(LOG_COLLECTOR_SCRIPT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return log_collector_proc


def restart_log_collector():
    """Leállítja és újraindítja a log collectort"""
    global log_collector_proc
    if log_collector_proc:
        try:
            log_collector_proc.terminate()
            log_collector_proc.wait(timeout=3)
        except:
            try:
                log_collector_proc.kill()
            except:
                pass
    start_log_collector()


#------------------------------
# Fő ciklus (Main loop)
#------------------------------
def main():
    load_env_all()
    start_bot("initial")
    start_log_collector()
    # --- init watched modules timestamps (commands folder, core) ---
    commands_dir = ROOT / "EMS_Duty_Moduls" / "commands"
    if not hasattr(main, "_commands_ts"):
        main._commands_ts = {}
        if commands_dir.exists():
            for p in commands_dir.glob("*.py"):
                main._commands_ts[str(p)] = p.stat().st_mtime
    if not hasattr(main, "_core_ts"):
        core_file = ROOT / (os.getenv("BOT_FILE") or "EMS_Duty_NAS_251114.py")
        main._core_ts = core_file.stat().st_mtime if core_file.exists() else None
    if not hasattr(main, "_event_ts"):
        main._event_ts = EVENT_FILE.stat().st_mtime if EVENT_FILE.exists() else None

    while True:
        rotate_if_big(WATCHDOG_LOG)
        rotate_if_big(BOT_LOG)
        flush_dm_queue()

        # --- Bot állapotellenőrzés
        if bot_proc and bot_proc.poll() is not None:
            rc = bot_proc.poll()
            if rc == 41:
                restart_bot("manual")
            else:
                restart_bot("crash")

        # --- Fájlmódosítás figyelése
        elif BOT.exists() and BOT.stat().st_mtime != bot_ts:
            restart_bot("file_update")

        # --- Modular commands watcher (restarts on commands/ changes)
        if commands_dir.exists():
            changed = False
            for p in commands_dir.glob("*.py"):
                ts = p.stat().st_mtime
                if str(p) not in main._commands_ts:
                    main._commands_ts[str(p)] = ts
                    changed = True
                elif main._commands_ts.get(str(p)) != ts:
                    main._commands_ts[str(p)] = ts
                    changed = True
            # removed files
            removed = [k for k in list(main._commands_ts.keys()) if not Path(k).exists()]
            if removed:
                for k in removed:
                    del main._commands_ts[k]
                changed = True
            if changed:
                log("[INFO] commands/ vagy modul változott – bot újraindítás...")
                restart_bot("commands_update")

        # --- ENV módosulás kezelése
        elif ENV.exists() and ENV.stat().st_mtime != env_ts:
            load_env_all()
            restart_bot("env_update")
            restart_log_collector()

        # --- Core file watcher (module side update)
        core_path = ROOT / (os.getenv("BOT_FILE") or "EMS_Duty_NAS_251114.py")
        if core_path.exists():
            core_ts = core_path.stat().st_mtime
            if main._core_ts is None:
                main._core_ts = core_ts
            elif core_ts != main._core_ts:
                log("[INFO] core bot file módosult – újraindítás...")
                main._core_ts = core_ts
                restart_bot("core_update")

        # --- Event file processing – a watchdog event fájl triggereli az akciót
        if EVENT_FILE.exists():
            try:
                current_event_ts = EVENT_FILE.stat().st_mtime
                if main._event_ts is None:
                    main._event_ts = current_event_ts
                elif current_event_ts != main._event_ts:
                    main._event_ts = current_event_ts
                    # process event JSON content
                    try:
                        payload = json.loads(EVENT_FILE.read_text(encoding="utf-8"))
                        action = payload.get("action")
                        reason = payload.get("reason", "event_trigger")
                        if action == "restart":
                            log(f"[EVENT] Watchdog event restart trigger: {reason}")
                            restart_bot(reason)
                        # Remove or archive event file to avoid repeat
                        try:
                            EVENT_FILE.unlink()
                        except:
                            pass
                    except Exception as e:
                        log(f"[WARN] Failed to parse event file: {e}")
            except Exception:
                pass

        # --- Log collector állapotfigyelés
        if log_collector_proc and log_collector_proc.poll() is not None:
            rc = log_collector_proc.poll()
            log(f"Log collector leállt (ret={rc}), újraindítás...")
            start_log_collector()

        # --- Log collector fájlmódosulás figyelése
        elif LOG_COLLECTOR_SCRIPT.exists():
            current_ts = LOG_COLLECTOR_SCRIPT.stat().st_mtime
            if not hasattr(main, "_collector_ts"):
                main._collector_ts = current_ts
            elif current_ts != main._collector_ts:
                log("[INFO] log_collector_NAS.py módosult – újraindítás...")
                main._collector_ts = current_ts
                restart_log_collector()

        time.sleep(5)


#------------------------------
# Főbelépési pont
#------------------------------
if __name__ == "__main__":
    main()
# End of file
