import os, json, datetime, logging, re
import pytz
from pathlib import Path
from discord.ext import commands
from typing import Optional

from . import state

logger = logging.getLogger("EMS_DUTY_CORE")

# Help meta decorator

def help_meta(category: str, usage: Optional[str] = None, short: Optional[str] = None, details: Optional[str] = None, examples: Optional[list] = None):
    def decorator(func):
        func.help_category = category
        func.help_usage = usage
        func.help_short = short
        func.help_details = details
        func.help_examples = examples or []
        return func
    return decorator


# Admin channel requirement (reads env variable set by core)

def require_admin_channel():
    return commands.check(lambda ctx: ctx.channel.id == int(os.getenv("ADMIN_CHANNEL_ID", "0")))


# Minimal environment loader

def load_env(env_path: Path):
    env = {}
    try:
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                if "=" in raw and not raw.strip().startswith("#"):
                    k, v = raw.strip().split("=", 1)
                    env[k.strip()] = v.strip()
    except Exception as e:
        logger.warning(f"ENV load failed: {e}")
    return env


# Small helpers

def normalize_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} óra {m} perc"
