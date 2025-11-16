import os, json, re, asyncio
from pathlib import Path
import datetime as dtmod
from typing import List

from . import state

DUTY_JSON = "duty_log.json"

def save_log():
    try:
        sorted_log = sorted(state.duty_log, key=lambda x: x.get("timestamp", ""))
        with open(DUTY_JSON, "w", encoding="utf-8") as f:
            json.dump(sorted_log, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def deduplicate_log(logs: List[dict]) -> List[dict]:
    seen = {}
    for rec in logs:
        mid = rec.get("message_id")
        if mid:
            seen[mid] = rec
    return list(seen.values())


def normalize_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def make_person_key(name_norm: str, fivem_name: str) -> str:
    nn = (name_norm or "").strip().lower()
    fv = (fivem_name or "").strip().lower()
    return f"{nn}|{fv}"

# Minimal process_duty_message – in modular setup, more features can be added

def process_duty_message(msg, add_to_state=True):
    # msg is a discord.Message-like object or a dict with embed
    try:
        embed = None
        if hasattr(msg, 'embeds') and msg.embeds:
            embed = msg.embeds[0]
        elif isinstance(msg, dict):
            embed = msg.get('embed')
        else:
            return False
        title = (getattr(embed, 'title', None) or embed.get('title', '')).strip()
    except Exception:
        return False

    # More complete detection: parse description for position and duration
    if "felvette a szolgálatot" in title.lower():
        # parse name and fivem
        try:
            name_part = title.split("(")[0].replace("**", "").strip()
            fivem_part = title.split("(")[1].split(")")[0].strip()
        except Exception:
            return False
        # description: may contain position line (e.g., 'Mentő - ...')
        description = ""
        try:
            description = getattr(embed, 'description', None) or (embed.get('description') if isinstance(embed, dict) else "")
        except Exception:
            description = ""

        position = ""
        if description:
            for raw in description.split("\n"):
                line = raw.strip()
                if line.startswith("Mentő"):
                    position = line

        # Prefer message.created_at if available
        created_at = getattr(msg, 'created_at', None) or (msg.get('created_at') if isinstance(msg, dict) else None)
        start_time = (created_at or dtmod.datetime.now()).strftime("%Y-%m-%d %H:%M")
        name_norm = normalize_person_name(name_part)
        person_key = make_person_key(name_norm, fivem_part)
        rec = {
            "message_id": getattr(msg, 'id', None) or msg.get('id'),
            "name": name_part,
            "name_norm": name_norm,
            "fivem_name": fivem_part,
            "position": position,
            "person_key": person_key,
            "start_time": start_time,
            "timestamp": start_time,
            "type": "felvette",
        }
        if add_to_state:
            state.duty_log.append(rec)
            state.duty_log[:] = deduplicate_log(state.duty_log)
            save_log()
        return True

    if "leadta a szolgálatot" in title.lower():
        # handle end
        try:
            name_part = title.split("(")[0].replace("**", "").strip()
            fivem_part = title.split("(")[1].split(")")[0].strip()
        except Exception:
            return False
        description = ""
        try:
            description = getattr(embed, 'description', None) or (embed.get('description') if isinstance(embed, dict) else "")
        except Exception:
            description = ""

        position = ""
        duration = 0
        for raw in (description or "").split("\n"):
            line = raw.strip()
            if line.startswith("Mentő"):
                position = line
            m = re.search(r"szolgálatban töltött idő\s*[:\-]?\s*(\d+)\s*perc", line, flags=re.IGNORECASE)
            if m:
                duration = int(m.group(1))

        end_dt = getattr(msg, 'created_at', None) or (msg.get('created_at') if isinstance(msg, dict) else None) or dtmod.datetime.now()
        end_time = end_dt.strftime("%Y-%m-%d %H:%M")
        start_time_val = end_dt - dtmod.timedelta(minutes=duration)
        start_time = start_time_val.strftime("%Y-%m-%d %H:%M")
        name_norm = normalize_person_name(name_part)
        person_key = make_person_key(name_norm, fivem_part)
        rec = {
            "message_id": getattr(msg, 'id', None) or msg.get('id'),
            "name": name_part,
            "name_norm": name_norm,
            "fivem_name": fivem_part,
            "position": position,
            "person_key": person_key,
            "end_time": end_time,
            "timestamp": end_time,
            "type": "leadta",
            "duration": duration,
        }
        if add_to_state:
            state.duty_log.append(rec)
            state.duty_log[:] = deduplicate_log(state.duty_log)
            save_log()
        return True

    return False


def get_time_for_period(start_date, end_date):
    """Összesített szolgálati idők lekérése adott időintervallumra (percben).
    Returns a list of formatted strings "<name> – <position>: X óra Y perc" sorted by descending minutes.
    """
    summary = {}

    for log in state.duty_log:
        try:
            ts = dtmod.datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M")
            if start_date <= ts <= end_date:
                name = log.get("name", "Ismeretlen")
                position = log.get("position", "").replace("Mentő - ", "").strip()
                duration = int(log.get("duration", 0))

                key = f"{name} – {position}"
                summary[key] = summary.get(key, 0) + duration
        except Exception:
            continue

    sorted_summary = sorted(summary.items(), key=lambda x: x[1], reverse=True)
    results = []
    for person, total_minutes in sorted_summary:
        hours = total_minutes // 60
        minutes = total_minutes % 60
        results.append(f"{person}: {hours} óra {minutes} perc")
    return results


async def backfill_duty_messages(channel, after=None, max_messages=None):
    """Beolvassa a duty channel history-ját és meghívja process_duty_message minden üzenetre.
    `after` is a datetime or None, `max_messages` optionally limits how many messages to read.
    Returns processed count.
    """
    processed = 0
    processed_loop = 0
    async for msg in channel.history(limit=max_messages or None, after=after):
        process_duty_message(msg)
        processed += 1
        processed_loop += 1
        if processed_loop % 50 == 0:
            await asyncio.sleep(0.5)
    return processed
