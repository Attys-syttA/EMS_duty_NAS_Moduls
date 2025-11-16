from pathlib import Path

# Shared application state
ROOT = Path("/volume1/homes/Attila_NAS_System/EMS_Duty")
# duty_log: in-memory list of processed duty entries
duty_log = []
EMS_PEOPLE = {}
BOT = None
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Add other runtime fields as needed
