import os, sys, importlib, logging, asyncio
from pathlib import Path
from dotenv import load_dotenv
import discord
import json
from discord.ext import commands

from . import state
from . import helpers
from .hotloader import watch_and_reload

ROOT = state.ROOT
LOG_DIR = state.LOG_DIR

# Configure logging
logger = logging.getLogger("EMS_DUTY_CORE")
logger.setLevel(logging.INFO)
log_file = LOG_DIR / "runtime_modular.log"
fh = logging.FileHandler(log_file, encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s"))
logger.addHandler(fh)

# Load .env
load_dotenv(ROOT / ".env")
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID", "0"))
DUTY_LOG_CHANNEL_ID = int(os.getenv("DUTY_LOG_CHANNEL_ID", "0"))

# Create bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Setup shared state
state.BOT = bot
# Load EMS_PEOPLE if exists
try:
    with open(ROOT / "ems_person_data.json", encoding="utf-8") as f:
        state.EMS_PEOPLE = json.load(f)
except Exception:
    state.EMS_PEOPLE = {}

# Dynamic command loader

def load_command_modules():
    commands_dir = Path(__file__).parent / "commands"
    sys.path.insert(0, str(commands_dir.parent))
    for p in commands_dir.glob("*.py"):
        if p.name.startswith("__"):
            continue
        mod_name = f"EMS_Duty_Moduls.commands.{p.stem}"
        try:
            logger.info(f"Importing command module: {mod_name}")
            mod = importlib.import_module(mod_name)
            # Each module may provide setup(bot, state, helpers) function
            if hasattr(mod, "setup"):
                mod.setup(bot=bot, state=state, helpers=helpers)
                logger.info(f"Loaded module: {mod_name}")
        except Exception as e:
            logger.exception(f"Failed to import {mod_name}: {e}")


# Register help command anew if needed; helper functions will provide same behavior

# Hotloader stub (watch for file changes)

async def hotloader_task(interval: int = 5):
    """Simple hotloader: reimports command modules when files change.
    This is a lightweight stub to show the structure; more robust watchers can be added.
    """
    import time
    last_ts = {}
    commands_dir = Path(__file__).parent / "commands"
    # delegate to dedicated hotloader
    await watch_and_reload(commands_dir, interval=interval)


# Bot setup hook
@bot.event
async def setup_hook():
    logger.info("Setting up modular bot...")
    # Start hotloader
    asyncio.create_task(hotloader_task())


# On ready completion
@bot.event
async def on_ready():
    logger.info(f"Bot ready — user: {bot.user}")


def run():
    # Import commands
    load_command_modules()
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN not set in .env")
    bot.run(TOKEN)


if __name__ == "__main__":
    run()
