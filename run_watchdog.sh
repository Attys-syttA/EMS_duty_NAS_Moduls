#!/bin/bash
# EMS Duty Watchdog indító script Synology NAS-hoz

cd /volume1/homes/Attila_NAS_System/EMS_Duty

# Biztonság kedvéért PATH kiegészítés (Synology saját python miatt)
export PATH=/usr/local/bin:/usr/bin:/bin

# Napló mappa létrehozás (ha nincs)
mkdir -p logs

# Futás backgroundban - logba irányítás
nohup /bin/python3 watchdog_NAS.py >> logs/watchdog_boot.log 2>&1 &
