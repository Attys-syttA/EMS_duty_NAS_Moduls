import json
from pathlib import Path
import subprocess
import sys

def test_send_watchdog_event_creates_file(tmp_path, monkeypatch):
    root = Path('.').resolve()
    ev_dir = root / 'events'
    ev_file = ev_dir / 'watchdog_event.json'
    if ev_file.exists():
        ev_file.unlink()
    # run helper script
    rc = subprocess.call([sys.executable, 'EMS_Duty_Moduls/scripts/send_watchdog_event.py', '--action', 'restart', '--reason', 'pytest'])
    assert rc == 0
    assert ev_file.exists()
    payload = json.loads(ev_file.read_text(encoding='utf-8'))
    assert payload['action'] == 'restart'
    assert payload['reason'] == 'pytest'
    # cleanup
    ev_file.unlink()
