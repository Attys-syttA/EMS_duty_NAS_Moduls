#!/bin/bash
# ==========================================================
# EMS Duty - Teljes újraindító script (NAS környezethez)
# ----------------------------------------------------------
# • Leállítja az Attila_NAS_System user Python folyamatait
# • Elindítja a run_watchdog.sh-t háttérben
# • Ellenőrzi, hogy a watchdog, bot és collector újraindultak-e
# • A teljes futás minden kimenetét a restart.log-ba menti
# ==========================================================

ROOT="/volume1/homes/Attila_NAS_System/EMS_Duty"
LOGFILE="$ROOT/logs/restart.log"

# --- minden kimenetet logolunk ---
exec > >(tee -a "$LOGFILE") 2>&1
echo ""
echo "🔁 EMS Duty Restart indítva: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Logfájl: $LOGFILE"
echo "------------------------------------------"

echo "🔴 EMS Duty folyamatok leállítása..."

# Saját Python folyamatok leállítása (rendszer folyamatok érintetlenek maradnak)
ps aux | grep Attila | grep python | awk '{print $2}' | xargs kill -9 2>/dev/null

sleep 3
echo "✅ Minden felhasználói Python folyamat leállítva."

# Watchdog indítása háttérben
echo "🚀 Watchdog újraindítása..."
nohup /bin/bash "$ROOT/run_watchdog.sh" >> "$LOGFILE" 2>&1 &

sleep 6  # kis várakozás, amíg a watchdog elindítja a botot és collectort

# Ellenőrzés: watchdog, bot és collector futnak-e?
echo ""
echo "🔎 Folyamatok ellenőrzése:"
echo "------------------------------------------"
ps aux | grep Attila | grep python | grep -E "watchdog_NAS|EMS_Duty_NAS_|log_collector_NAS" | awk '{printf "%-8s %-70s\n", $2, substr($0, index($0,$11))}'
echo "------------------------------------------"

# Kiértékelés
if ps aux | grep -q "watchdog_NAS.py" && ps aux | grep -q "log_collector_NAS.py" && ps aux | grep -q "EMS_Duty_NAS_"; then
    echo "✅ Minden EMS Duty komponens sikeresen elindult!"
else
    echo "⚠️  Figyelem: Nem minden komponens indult el megfelelően!"
    echo "   Részletek: $LOGFILE"
fi

echo "------------------------------------------"
echo "🔚 Restart folyamat befejezve: $(date '+%Y-%m-%d %H:%M:%S')"
echo "------------------------------------------"
