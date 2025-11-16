#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# # EMS Duty Bot NAS verzió | 2024.11.01
import os, re, json, random, logging, asyncio
from datetime import datetime, timedelta
import datetime as dtmod
from typing import List, Dict, Optional, Tuple
import discord
from discord.ext import commands
from dotenv import load_dotenv
import pytz
from pathlib import Path

# ============ Alap ============
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID"))
DUTY_LOG_CHANNEL_ID = int(os.getenv("DUTY_LOG_CHANNEL_ID"))
WEEKLY_DUTY_CHANNEL_ID = int(os.getenv("WEEKLY_DUTY_CHANNEL_ID"))
CHAT_CHANNEL_ID = int(os.getenv("CHAT_CHANNEL_ID"))
DISPATCHER_CHANNEL_ID = int(os.getenv("DISPATCHER_CHANNEL_ID")) 
SZABADSAG_CHANNEL_ID = int(os.getenv("SZABADSAG_CHANNEL_ID"))   
budapest_tz = pytz.timezone("Europe/Budapest")

VEZETOSSEG = [x.strip() for x in os.getenv("VEZETOSSEG", "").split(",") if x.strip()]
DEDIKALT_RANGOK = [x.strip() for x in os.getenv("DEDIKALT_RANGOK", "").split(",") if x.strip()]

os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("EMS_DUTY_BOT")
logger.setLevel(logging.INFO)
fh = logging.FileHandler("logs/runtime.log", encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s"))
logger.addHandler(fh)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- EMS személy adatbázis betöltése (mention lookup) ---
try:
    with open("ems_person_data.json", "r", encoding="utf-8") as f:
        EMS_PEOPLE = json.load(f)
except:
    EMS_PEOPLE = {}

def get_discord_id_from_norm(name_norm: str) -> Optional[str]:
    """Visszaadja a Discord ID-t a normalizált név alapján."""
    key = name_norm.strip().lower()
    for person in EMS_PEOPLE.values():
        if person.get("KEY","").strip().lower() == key:
            return person.get("DCID")
    return None

# =======================================================
# IDEIGLENES RAW MESSAGE LOGGER (duty-log csatorna teszthez)
# =======================================================
RAW_LOG_FILE = "raw_sniff.log"

@bot.event
async def on_message(message):
    if message.channel.id == int(os.getenv("DUTY_LOG_CHANNEL_ID", "0")):
        try:
            with open(RAW_LOG_FILE, "a", encoding="utf-8") as f:
                f.write("\n==============================\n")
                f.write(f"Timestamp: {message.created_at.isoformat()}\n")
                f.write(f"Message ID: {message.id}\n")
                f.write(f"Author: {message.author} ({message.author.id})\n")
                f.write(f"Display Name: {message.author.display_name}\n")
                f.write(f"Content: {message.content}\n")
                if hasattr(message.author, "roles"):
                    role_ids = [r.id for r in message.author.roles]
                    f.write(f"Roles: {role_ids}\n")
                f.write(f"Raw object: {repr(message)}\n")
        except Exception as e:
            print(f"[RAW LOGGER ERROR] {e}", flush=True)
    await bot.process_commands(message)

# ========= Adattár =========
DUTY_JSON = "duty_log.json"
if os.path.exists(DUTY_JSON):
    with open(DUTY_JSON, "r", encoding="utf-8") as f:
        duty_log = json.load(f)
else:
    duty_log = []

def save_log():
    """Duty-log mentése időrendbe rendezve (timestamp szerint)."""
    try:
        sorted_log = sorted(
            duty_log,
            key=lambda x: x.get("timestamp", "")
        )
        with open(DUTY_JSON, "w", encoding="utf-8") as f:
            json.dump(sorted_log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Hiba a duty_log mentésekor: {e}")

# def save_log():
#     with open(DUTY_JSON, "w", encoding="utf-8") as f:
#         json.dump(duty_log, f, ensure_ascii=False, indent=2)

def normalize_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()

def deduplicate_log():
    # message_id alapján egyedisítés, legfrissebbet tartjuk meg
    seen = {}
    for rec in duty_log:
        mid = rec.get("message_id")
        seen[mid] = rec
    return list(seen.values())

# ========= Discord user ID térkép a betoppanó JSON-ból =========
USER_ID_MAP_FILE = "discord_user_ids.json"  # discord_name_norm -> user_id

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def build_discord_user_id_map_from_betoppano(json_path="betoppano_log.json"):
    """Betoppanó JSON-ból (author + -display/global/username) térkép készítése: név_norm -> user_id."""
    if not os.path.exists(json_path):
        return 0
    with open(json_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    mmap = {}
    for r in rows:
        uid = r.get("author_id")
        if not uid:
            continue
        cands = {
            _norm(r.get("author")),
            _norm(r.get("author_display")),
            _norm(r.get("author_global")),
            _norm(r.get("author_username")),
        }
        for c in cands:
            if c:
                mmap[c] = uid

    with open(USER_ID_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(mmap, f, ensure_ascii=False, indent=2)
    return len(mmap)

# ========= Karakter -> Discord mention leképezés =========
CHAR_TO_DISCORD_NAME_FILE = "char_to_discord_name.json"

def _load_json_or_empty(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def resolve_mention_from_character_name(char_name_display: str) -> str:
    """
    1️⃣ normalizálja a karakternevet (FiveM név)
    2️⃣ char_to_discord_name.json alapján megkeresi a Discord-név normját
    3️⃣ discord_user_ids.json alapján megkeresi az ID-t
    4️⃣ visszaadja <@id> formában, ha minden megvan – különben a sima nevet
    """
    def _norm(s: str):
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    char_to_discord = _load_json_or_empty(CHAR_TO_DISCORD_NAME_FILE)
    discord_ids = _load_json_or_empty(USER_ID_MAP_FILE)

    cn = _norm(char_name_display)
    dn = char_to_discord.get(cn)
    if not dn:
        return char_name_display

    uid = discord_ids.get(_norm(dn))
    return f"<@{uid}>" if uid else char_name_display

# ========= Duty-log feldolgozás =========
def make_person_key(name_norm: str, fivem_name: str) -> str:
    """Stabil személyazonosító létrehozása név + FiveM-név alapján."""
    nn = (name_norm or "").strip().lower()
    fv = (fivem_name or "").strip().lower()
    return f"{nn}|{fv}"

async def process_duty_message(message: discord.Message):
    """A duty-log csatorna embedjeit dolgozzuk fel: 'felvette' ÉS 'leadta a szolgálatot' kártyák."""
    if message.channel.id != DUTY_LOG_CHANNEL_ID:
        return
    if getattr(message.author, "bot", False) is True and not message.embeds:
        return
    if not message.embeds:
        return
    if any(x.get("message_id") == message.id for x in duty_log):
        return

    embed = message.embeds[0]
    title = (embed.title or "").strip()
    description = (embed.description or "")

    # ==============================================================
    # FELVETTE A SZOLGÁLATOT
    # ==============================================================
    if "felvette a szolgálatot" in title.lower():
        try:
            name_part = title.split("(")[0].replace("**", "").strip()
            fivem_part = title.split("(")[1].split(")")[0].strip()
        except Exception:
            return

        position = ""
        for raw in description.split("\n"):
            line = raw.strip()
            if line.startswith("Mentő"):
                position = line

        start_time = message.created_at.astimezone(budapest_tz)
        name_norm = normalize_person_name(name_part)
        person_key = make_person_key(name_norm, fivem_part)

        duty_log.append({
            "message_id": message.id,
            "name": name_part,
            "name_norm": name_norm,
            "fivem_name": fivem_part,
            "person_key": person_key,
            "position": position,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M"),
            "timestamp": start_time.strftime("%Y-%m-%d %H:%M"),
            "type": "felvette"
        })

        duty_log[:] = deduplicate_log()
        save_log()
        return  # ⬅ ne fusson le a "leadta" ág is

    # ==============================================================
    # LEADTA A SZOLGÁLATOT
    # ==============================================================
    if "leadta a szolgálatot" not in title.lower():
        return

    try:
        name_part = title.split("(")[0].replace("**", "").strip()
        fivem_part = title.split("(")[1].split(")")[0].strip()
    except Exception:
        return

    position = ""
    duration = 0
    for raw in description.split("\n"):
        line = raw.strip()
        if line.startswith("Mentő"):
            position = line
        m = re.search(r"szolgálatban töltött idő\s*[:\-]?\s*(\d+)\s*perc", line, flags=re.IGNORECASE)
        if m:
            duration = int(m.group(1))

    end_time = message.created_at.astimezone(budapest_tz)
    start_time = end_time - timedelta(minutes=duration)
    name_norm = normalize_person_name(name_part)
    person_key = make_person_key(name_norm, fivem_part)

    duty_log.append({
        "message_id": message.id,
        "name": name_part,
        "name_norm": name_norm,
        "fivem_name": fivem_part,
        "person_key": person_key,
        "position": position,
        "duration": duration,
        "start_time": start_time.strftime("%Y-%m-%d %H:%M"),
        "end_time": end_time.strftime("%Y-%m-%d %H:%M"),
        "timestamp": end_time.strftime("%Y-%m-%d %H:%M"),
        "type": "leadta"
    })

    duty_log[:] = deduplicate_log()
    save_log()

# ========= Duty-log visszamenőleges beolvasás =========
async def backfill_duty_messages(guild: discord.Guild):
    """Az utóbbi ~35 nap duty-log üzeneteit beolvassuk, hogy a JSON naprakész legyen."""
    channel = guild.get_channel(DUTY_LOG_CHANNEL_ID)
    if not channel:
        logger.error("Duty-log csatorna nem elérhető azonosító alapján.")
        return

    logger.info(f"Üzenetek betöltése: #{channel.name}")
    latest_ts = None
    if duty_log:
        try:
            latest_ts = max(
                dtmod.datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M")
                for r in duty_log
            )
        except Exception:
            latest_ts = None

    after = latest_ts or (dtmod.datetime.now(budapest_tz) - timedelta(days=35))
    # history olvasás, óvatosan a rate limitekkel
    processed = 0
    admin_channel_id = int(os.getenv("ADMIN_CHANNEL_ID", "0"))
    admin_channel = guild.get_channel(admin_channel_id)

    try:
        async for msg in channel.history(limit=None, after=after):
            await process_duty_message(msg)
            processed += 1

            # 🔹 50 üzenetenként jelez az admin csatornára
            if processed % 50 == 0 and admin_channel:
                await admin_channel.send(
                    f"```diff\n+ [INFO] Duty-log feldolgozás folyamatban... ({processed} üzenet beolvasva)\n```"
                )
                # plusz naplóba is
                logger.info(f"Duty-log beolvasás: {processed} üzenet feldolgozva...")

            await asyncio.sleep(0.5)  # rate limit kímélés

        logger.info(f"Duty-log beolvasás kész. Feldolgozott: {processed}")

        # 🔹 Befejezés jelzése az admin csatornára
        if admin_channel:
            await admin_channel.send(
                f"```diff\n+ [OK] Duty-log beolvasás kész ({processed} üzenet feldolgozva).\n```"
            )

    except discord.DiscordException as e:
        logger.warning(f"Backfill közbeni Discord-hiba: {e}")
        if admin_channel:
            await admin_channel.send(
                f"```diff\n- [HIBA] Duty-log beolvasás megszakadt: {e}\n```"
            )
# ==========================================================================
# ============================  PARANCSOK  =================================
# ==========================================================================
# PARANCS METAADAT DECORATOR – automatikus súgóhoz
# ==========================================================================

def help_meta(
    category: str,
    usage: Optional[str] = None,
    short: Optional[str] = None,
    details: Optional[str] = None,
    examples: Optional[List[str]] = None,
):
    """
    Decorator, amivel egy parancsra rá tudod írni:
      - melyik kategóriába tartozik,
      - mi a használati minta,
      - mi a rövid leírás (lista nézethez),
      - mi a részletes leírás (részletes súgóhoz),
      - milyen példákat mutasson a súgó.

    Ha valamit nem adsz meg, a súgó próbál értelmesen tippelni:
      - rövid leírás → a függvény docstringje,
      - részletes leírás → a docstring vagy a rövid leírás,
      - használat → `!<parancsnév>`.
    """
    def decorator(func):
        func.help_category = category
        func.help_usage = usage
        func.help_short = short
        func.help_details = details
        func.help_examples = examples or []
        return func
    return decorator

# ==========================================================================
def require_admin_channel():
    return commands.check(lambda ctx: ctx.channel.id == ADMIN_CHANNEL_ID)
# ---------------------------------------------------------------------------
# PING PARANCS – BOT ELÉRHETŐSÉG ELLENŐRZÉS + SPAM VÉDELEM
# ---------------------------------------------------------------------------

_last_ping = None
@bot.command(name="ping", aliases=["Ping", "PING"])
@require_admin_channel()
@help_meta(
    category="Segédletek",
    usage="!ping",
    short="Ellenőrzi, hogy él-e és válaszol-e a bot.",
    details=(
        "Egyszerű elérhetőségi teszt: visszajelez, hogy fut-e a bot, és megmutatja "
        "a pillanatnyi válaszidőt. Ha túl gyakran pingelik egymás után, akkor "
        "a súgár helyett egy véletlenszerű, vicces ping-pong üzenetet küld."
    ),
    examples=[
        "!ping",
    ],
)
async def ping(ctx):
    """Bot elérhetőségének tesztelése, anti-spam humorral."""
    global _last_ping
    now = datetime.now()

    try:
        # Ha túl gyorsan pingelik → random válasz
        if _last_ping and (now - _last_ping).total_seconds() < 25:
            msg = random.choice([
                ":ping_pong: pong – szerva itt!",
                ":ping_pong: pong – meccslabda!",
                ":ping_pong: pong – csúszott volt!",
                ":ping_pong: pong – megetted a nyesést!",
            ])
            await ctx.send(msg)

            logger.info(f"!ping (spam) – {ctx.author} | válasz: {msg}")
        else:
            latency_ms = round(bot.latency * 1000)
            resp = f"✅ A bot fut! (késleltetés: {latency_ms} ms)"
            await ctx.send(resp)

            logger.info(f"!ping – {ctx.author} | latency: {latency_ms}ms")

        _last_ping = now

    except Exception as e:
        logger.error(f"Ping parancs hiba: {e}")
        await ctx.send("```diff\n- Hiba történt a ping parancs futása közben!\n```")
# ---------------------------------------------------------------------------
# időszakos összegzés helper
def get_time_for_period(start_date, end_date):
    """Összesített szolgálati idők lekérése adott időintervallumra."""
    summary = {}

    for log in duty_log:
        try:
            ts = dtmod.datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
            if start_date <= ts <= end_date:
                name = log.get("name", "Ismeretlen")
                position = log.get("position", "").replace("Mentő - ", "").strip()
                duration = log.get("duration", 0)

                # név + pozíció kulcs alapján összegez
                key = f"{name} – {position}"
                summary[key] = summary.get(key, 0) + duration
        except Exception:
            continue

    # csökkenő sorrend perc szerint
    sorted_summary = sorted(summary.items(), key=lambda x: x[1], reverse=True)

    results = []
    for person, total_minutes in sorted_summary:
        hours = total_minutes // 60
        minutes = total_minutes % 60
        results.append(f"{person}: {hours} óra {minutes} perc")

    return results
# ---------------------------------------------------------------------------
# BOT SZAGLÁSZÓ (SNIFF) PARANCS – DUTY-LOG CSATORNA VIZSGÁLATA
# ---------------------------------------------------------------------------
@bot.command(name="sniff_duty")
@commands.has_permissions(administrator=True)
@help_meta(
    category="Diagnosztika és karbantartás",
    usage="!sniff_duty [limit] [show|silent|raw|all]",
    short="A duty-log csatorna üzeneteinek vizsgálata és mentése.",
    details=(
        "A parancs a Discord duty-log csatorna legutóbbi üzeneteit vizsgálja és "
        "menti TXT és opcionálisan JSON formátumban. Hasznos a duty embedek "
        "diagnosztikájához, formátumhibák, hiányzó mezők vagy beolvasási "
        "anomáliák feltárásához.\n\n"
        "• **limit** – hány üzenetet olvas be (alapértelmezés: 5)\n"
        "• **show** – a teljes tartalmat Discordon is megmutatja\n"
        "• **silent** – nem küld státuszüzeneteket\n"
        "• **raw** – JSON fájlt is készít a beolvasott adatokból\n"
        "• **all** – egyszerre show + raw mód"
    ),
    examples=[
        "!sniff_duty",
        "!sniff_duty 10",
        "!sniff_duty 20 show",
        "!sniff_duty 50 raw",
        "!sniff_duty 100 all",
    ]
)
async def sniff_duty(ctx, limit: int = 5, mode: str = None):
    """Duty-log sniffelő parancs adminoknak."""

    # paraméter módosítók normalizálása
    mode = (mode or "").lower()
    show = mode in ("show", "showme", "all")
    silent = mode == "silent"
    raw = mode in ("raw", "all")

    channel = bot.get_channel(DUTY_LOG_CHANNEL_ID)
# ---------------------------------------------------------------------------
# CHANNEL_INFO PARANCS – CSATORNA TÍPUS ÉS TULAJDONSÁGOK MEGJELENÍTÉSE
# ---------------------------------------------------------------------------
@bot.command(name="channel_info", aliases=["chaninfo", "csatorna"])
@require_admin_channel()
@help_meta(
    category="Diagnosztika és karbantartás",
    usage="!channel_info <channel_id>",
    short="Kiírja egy Discord csatorna típusát és főbb jellemzőit.",
    details=(
        "A parancs segítségével gyorsan ellenőrizhető egy csatorna típusa, "
        "kategóriája, azonosítója és további tulajdonságai. Hasznos hibakereséshez "
        "és csatorna-infrastruktúra vizsgálatához.\n\n"
        "**Mezők:**\n"
        "• csatorna neve\n"
        "• csatorna ID\n"
        "• Python típus (szövegcsatorna, thread, kategória stb.)\n"
        "• thread-ek száma (ha van)\n"
        "• kategória neve (ha a csatorna valamely kategóriában van)"
    ),
    examples=[
        "!channel_info 123456789012345678",
        "!chaninfo 987654321234567890",
        "!csatorna 135791357913579135",
    ]
)
async def channel_info(ctx, channel_id: int = None):
    """Csatorna típusának és jellemzőinek kiírása"""
    try:
        if channel_id is None:
            await ctx.send("Használat: `!chaninfo <channel_id>`  (pl.: !chaninfo 1349829361649324173)")
            return

        ch = bot.get_channel(channel_id)
        if not ch:
            await ctx.send(f"❌ Nem találom a csatornát ID alapján: `{channel_id}`")
            return

        msg = []
        msg.append(f"📎 **Channel**: {ch.name}")
        msg.append(f"🆔 ID: `{ch.id}`")
        msg.append(f"🏷️ Típus: `{type(ch)}`")

        # Threads
        if hasattr(ch, 'threads'):
            msg.append(f"🧵 Threads: `{len(ch.threads)}`")

        # Parent category
        if hasattr(ch, 'category') and ch.category:
            msg.append(f"📂 Kategória: {ch.category.name}")

        await ctx.send("\n".join(msg))

    except Exception as e:
        await ctx.send(f"⚠️ Hiba: `{e}`")

# ---------------------------------------------------------------------------
# SZOLGÁLAT PARANCS – IDŐSZAK SZOLGÁLATI IDEJÉNEK LEKÉRÉSE
# ---------------------------------------------------------------------------
@bot.command(name="szolgalat", aliases=["szolgálat", "Szolgálat"])
@require_admin_channel()
@help_meta(
    category="Szolgálati riportok",
    usage="!szolgalat <kezdet_dátum> <kezdet_idő> <vég_dátum> <vég_idő>",
    short="Összegzi egy tetszőleges időszak szolgálati idejét személyenként.",
    details=(
        "A parancs egy tetszőlegesen megadott időintervallumra kiszámítja minden EMS "
        "dolgozó szolgálatban töltött idejét. A bemenet két dátum–idő pár:\n\n"
        "**Formátum:** `YYYY-MM-DD HH:MM`\n"
        "• <kezdet_dátum> <kezdet_idő>\n"
        "• <vég_dátum> <vég_idő>\n\n"
        "A bot a megadott intervallum összes szolgálati bejegyzését feldolgozza, majd "
        "összegzi a hozzájuk tartozó perceket, és az eredményt órára–percre lebontva "
        "listázza ki minden érintett személy esetén.\n\n"
        "A futtatás során először megjelenik egy ellenőrző üzenet, majd:\n"
        "```\n"
        "- [INFO] Feldolgozás indítása...\n"
        "```\n"
        "Ezután a bot elkészíti a jelentést, és a következő formátumban adja vissza:\n"
        "**Szolgálati idők <kezdés> és <vég> között:**\n"
        "<név> – <rang>: <óra> óra <perc> perc\n\n"
        "A lekérés végén a bot a következő záróüzenetet küldi:\n"
        "```\n"
        "📦 Mindenki a helyén, indulhat a műszak!\n"
        "+ [OK] Jelentés elkészült. Minden adat naprakész.\n"
        "```\n\n"
        "A parancs automatikusan több üzenetre bontja a kimenetet, ha az meghaladja a "
        "Discord 2000 karakteres limitjét."
    ),
    examples=[
        "!szolgalat 2025-10-01 00:00 2025-10-02 00:00",
        (
            "Minta kimenet:\n"
            "```\n"
            "🔍 Ellenőrzöm a szolgálati beosztásokat...\n"
            "- [INFO] Feldolgozás indítása...\n\n"
            "Szolgálati idők 2025-10-01 00:00 és 2025-10-02 00:00 között:\n"
            "Rumli Freeman – Gyakornok: 5 óra 52 perc\n"
            "Dr. Cormac Murhpy – Orvos: 4 óra 14 perc\n"
            "Dr. Water White – Orvos: 3 óra 44 perc\n"
            "Dr. Rick Deckard – Igazgató-helyettes: 3 óra 38 perc\n"
            "...\n\n"
            "📦 Mindenki a helyén, indulhat a műszak!\n"
            "+ [OK] Jelentés elkészült. Minden adat naprakész.\n"
            "```"
        )
    ]
)
async def szolgalat(ctx, kezdet: str, kezdet_ido: str, veg: str, veg_ido: str):
    try:
        start_str = f"{kezdet} {kezdet_ido}"
        end_str = f"{veg} {veg_ido}"
        start_date = dtmod.datetime.strptime(start_str, "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
        end_date = dtmod.datetime.strptime(end_str, "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)

        await ctx.send("🔍 Ellenőrzöm a szolgálati beosztásokat...\n```diff\n- [INFO] Feldolgozás indítása...\n```")
        await asyncio.sleep(1.0)

        results = get_time_for_period(start_date, end_date)
        response = "\n".join(results) if results else "Nincs adat az adott időszakra."

        header = f"**Szolgálati idők {start_str} és {end_str} között:**"
        text = f"{header}\n{response}"
        if len(text) > 2000:
            parts = [text[i:i+2000] for i in range(0, len(text), 2000)]
            for idx, part in enumerate(parts, 1):
                await ctx.send(part)
                if idx < len(parts):
                    await ctx.send("```diff\n- [INFO] További adatok betöltése...\n```")
        else:
            await ctx.send(text)

        await ctx.send("📦 Mindenki a helyén, indulhat a műszak!\n```diff\n+ [OK] Jelentés elkészült. Minden adat naprakész.\n```")

    except ValueError:
        await ctx.send("Hibás dátumformátum! Használat: `!szolgalat YYYY-MM-DD HH:MM YYYY-MM-DD HH:MM`")
# ---------------------------------------------------------------------------
# SZEMÉLY PARANCS – ADOTT SZEMÉLY ÖSSZES SZOLGÁLATI IDEJE
# ---------------------------------------------------------------------------
@bot.command(name="szemely", aliases=["személy", "Személy"])
@require_admin_channel()
@help_meta(
    category="Szolgálati riportok",
    usage="!szemely <Név>",
    short="Kilistázza egy adott személy összes rögzített szolgálati időpontját.",
    details=(
        "A parancs egy EMS dolgozó minden szolgálati bejegyzését lekéri a duty-log "
        "adatbázisból. A név nem érzékeny az ékezetekre vagy kis-/nagybetűkre; "
        "a bot automatikusan normalizálja.\n\n"
        "A kimenet minden szolgálati időtartamot megjelenít START–END formátumban, "
        "és kiszámítja az adott bejegyzés hosszát óra–perc bontásban.\n\n"
        "A futtatás során először egy véletlenszerűen kiválasztott előkészítő üzenet "
        "jelenik meg (pl. „📖 Adatok betöltése…”) majd:\n"
        "```\n"
        "- [INFO] Feldolgozás indítása...\n"
        "```\n"
        "Ezután időrendben felsorolja az összes szolgálati bejegyzést.\n\n"
        "A lekérés végén a bot így jelzi a sikeres befejezést:\n"
        "```\n"
        "+ [OK] Lekérés befejezve. Adatok megjelenítve.\n"
        "```\n\n"
        "A parancs automatikus üzenetdarabolást használ, ha a kimenet meghaladja "
        "a Discord 2000 karakteres limitjét."
    ),
    examples=[
        "!szemely Minta Péter",
        (
            "Minta kimenet:\n"
            "```\n"
            "🧾 Egy pillanat, összegzem Dr. Rick Deckard beosztásait...\n"
            "- [INFO] Feldolgozás indítása...\n\n"
            "Minta Péter szolgálati időpontjai:\n"
            "2025-08-24 12:13 - 2025-08-24 13:43  1 óra 30 perc\n"
            "2025-08-24 14:47 - 2025-08-24 20:38  5 óra 51 perc\n"
            "2025-08-25 18:22 - 2025-08-25 21:54  3 óra 32 perc\n"
            "...\n\n"
            "+ [OK] Lekérés befejezve. Adatok megjelenítve.\n"
            "```"
        )
    ]
)
async def szemely(ctx, *, nev: str):
    target = normalize_person_name(nev)
    matches = [r for r in duty_log if r.get("name_norm") == target]
    if not matches:
        await ctx.send(f"```diff\n- [INFO] Nincs adat {nev} nevű személyről.\n```")
        return

    # időtartamok sorolása (start-end)
    lines = []
    for r in matches:
        try:
            st = dtmod.datetime.strptime(r["start_time"], "%Y-%m-%d %H:%M")
            et = dtmod.datetime.strptime(r["end_time"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        dur = int(r.get("duration", 0))
        h, m = divmod(dur, 60)
        lines.append(f"{st:%Y-%m-%d %H:%M} - {et:%Y-%m-%d %H:%M}  {h} óra {m} perc")

    intro = random.choice([
        f"🔍 Keresem {nev} szolgálati naplóit...",
        f"📖 {nev} adatai betöltése folyamatban...",
        f"🧾 Egy pillanat, összegzem {nev} beosztásait...",
    ])
    await ctx.send(intro + "\n```diff\n- [INFO] Feldolgozás indítása...\n```")
    await asyncio.sleep(1.0)

    response = "\n".join(lines) if lines else "Nincs megjeleníthető adat."
    if len(response) > 2000:
        for i in range(0, len(response), 2000):
            await ctx.send(response[i:i+2000])
    else:
        await ctx.send(f"**{nev} szolgálati időpontjai:**\n{response}")

    await ctx.send("```diff\n+ [OK] Lekérés befejezve. Adatok megjelenítve.\n```")

# ---------------------------------------------------------------------------
# SZEMÉLY NAPI PARANCS – ADOTT SZEMÉLY NAPI SZOLGÁLATI IDEJE
# ---------------------------------------------------------------------------
@bot.command(
    name="szemely_napi",
    aliases=["személy napi", "szemely napi", "személy_napi", "Személy napi"]
)
@require_admin_channel()
@help_meta(
    category="Szolgálati riportok",
    usage="!szemely_napi <Név>",
    short="Egy adott dolgozó napi bontású, összesített szolgálati idejét jeleníti meg.",
    details=(
        "A parancs kilistázza egy EMS dolgozó minden olyan napját, amikor szolgálati idő "
        "lett rögzítve, és napokra bontva összegzi az adott napra eső perceket.\n\n"
        "A név nem érzékeny kis-/nagybetűre vagy az ékezetekre; a bot automatikusan "
        "normalizálja.\n\n"
        "A futtatás során a bot először jelzi az összesítés indítását:\n"
        "```\n"
        "- [INFO] Napi összesítés indítása...\n"
        "```\n"
        "Ezután időrendben felsorolja az érintett napokat, és feltünteti az adott napra "
        "eső teljes szolgálati időt óra–perc formában.\n\n"
        "Végül a folyamatot az alábbi üzenettel zárja:\n"
        "```\n"
        "+ [OK] Napi jelentés elkészült.\n"
        "```\n\n"
        "A kimenet 2000 karakter felett automatikusan több Discord-üzenetre bontva jelenik meg."
    ),
    examples=[
        "!szemely_napi Minta Péter",
        (
            "Minta kimenet:\n"
            "```\n"
            "- [INFO] Napi összesítés indítása...\n\n"
            "Kiss Péter napi összesített szolgálati ideje:\n"
            "2025-08-24: 7 óra 21 perc\n"
            "2025-08-25: 3 óra 32 perc\n"
            "2025-08-26: 8 óra 14 perc\n\n"
            "+ [OK] Napi jelentés elkészült.\n"
            "```"
        )
    ]
)
async def szemely_napi(ctx, *, nev: str):
    target = normalize_person_name(nev)
    matches = [r for r in duty_log if r.get("name_norm") == target]
    if not matches:
        await ctx.send(f"```diff\n- [INFO] Nincs adat {nev} nevű személyről.\n```")
        return

    day_totals = {}
    for r in matches:
        try:
            et = dtmod.datetime.strptime(r["end_time"], "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
        except Exception:
            continue
        dur = int(r.get("duration", 0))
        day = et.date()
        day_totals[day] = day_totals.get(day, 0) + dur

    lines = []
    for day in sorted(day_totals.keys()):
        h, m = divmod(day_totals[day], 60)
        lines.append(f"{day}: {h} óra {m} perc")

    await ctx.send("```diff\n- [INFO] Napi összesítés indítása...\n```")
    await asyncio.sleep(0.8)

    response = "\n".join(lines) if lines else "Nincs megjeleníthető adat."

    if len(response) > 2000:
        for i in range(0, len(response), 2000):
            await ctx.send(response[i:i+2000])
    else:
        await ctx.send(f"**{nev} napi összesített szolgálati ideje:**\n{response}")

    await ctx.send("```diff\n+ [OK] Napi jelentés elkészült.\n```")

# ---------------------------------------------------------------------------
# NAPI PARANCS – ADOTT NAP SZOLGÁLATÁNAK LEKÉRÉSE
# ---------------------------------------------------------------------------
@bot.command(name="napi", aliases=["Napi"])
@require_admin_channel()
@help_meta(
    category="Szolgálati riportok",
    usage="!napi <YYYY-MM-DD>",
    short="Megmutatja, hogy egy adott napon kik dolgoztak és mennyi szolgálati időt teljesítettek.",
    details=(
        "A parancs lekérdezi az adott napon (00:00–24:00 között) lezárt szolgálati "
        "bejegyzéseket, és kiszámítja minden dolgozó aznapra eső szolgálati idejét.\n\n"
        "A nap meghatározása:\n"
        "• kezdete: 00:00\n"
        "• vége: 24:00\n\n"
        "A szolgálati bejegyzések az `end_time` mező alapján kerülnek az adott naphoz. "
        "A bot minden dolgozó mellé kiírja a beosztását és az adott napra jutó teljes "
        "szolgálati időt, órában és percben.\n\n"
        "Az eredmény az alábbi formátumban jelenik meg:\n"
        "**YYYY.MM.DD. szolgálat:**\n"
        "<Név> <Beosztás>: <óra> óra <perc> perc.\n\n"
        "A kimenet automatikusan több üzenetre osztódik, ha meghaladja a Discord "
        "2000 karakteres üzenetlimitet."
    ),
    examples=[
        "!napi 2025-10-01",
        (
            "Minta kimenet:\n"
            "```\n"
            "2025.10.01. szolgálat:\n"
            "Chris Lockwood Mentő – Gyakornok: 1 óra 0 perc.\n"
            "Dr. Cormac Murhpy Mentő – Orvos: 1 óra 5 perc.\n"
            "Dr. Ráduly Zalán Mentő – Igazgató-helyettes: 2 óra 10 perc.\n"
            "Philadelphia De Blanca Mentő – Mentőtisz: 0 óra 1 perc.\n"
            "...\n"
            "Rumli Freeman Mentő – Gyakornok: 5 óra 52 perc.\n"
            "```"
        )
    ]
)
async def napi(ctx, datum: str):
    """Adott napon kik dolgoztak és mennyit (leadás szerint zárva)."""
    try:
        day_start = dtmod.datetime.strptime(datum, "%Y-%m-%d").replace(tzinfo=budapest_tz)
        day_end = day_start + timedelta(days=1)
    except ValueError:
        await ctx.send("Hibás dátumformátum! Használat: `!napi YYYY-MM-DD`")
        return

    entries = []
    for r in duty_log:
        try:
            et = dtmod.datetime.strptime(r["end_time"], "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
        except Exception:
            continue

        if day_start <= et < day_end:
            dur = int(r.get("duration", 0))
            h, m = divmod(dur, 60)
            entries.append(
                f"{r.get('name','Ismeretlen')} {r.get('position','')}: {h} óra {m} perc."
            )

    if not entries:
        await ctx.send(f"Nincs adat {datum} napra.")
        return

    lines = [f"**{day_start:%Y.%m.%d.} szolgálat:**"] + entries
    response = "\n".join(lines)

    if len(response) > 2000:
        for i in range(0, len(response), 2000):
            await ctx.send(response[i:i+2000])
    else:
        await ctx.send(response)
# ---------------------------------------------------------------------------
# FRISSÍTÉS MAG - központi logika (core)
# ---------------------------------------------------------------------------
async def run_frissites_core(full_mode: bool = False, ctx=None):
    """A frissítés logikai magja – mind parancs, mind automatikus futáshoz."""
    try:
        logger.info(f"[CORE] Frissítés indítása | mód: {'TELJES' if full_mode else 'normál'}")

        channel = bot.get_channel(DUTY_LOG_CHANNEL_ID)
        if not channel:
            msg = f"Duty-log csatorna nem elérhető (ID={DUTY_LOG_CHANNEL_ID})"
            logger.error(msg)
            if ctx:
                await ctx.send(f"```diff\n- [HIBA] {msg}\n```")
            return False

# -------------------------------------------------------------------
# TELJES MÓD (ha pl. JSON sérült vagy manuális rebuild)
# -------------------------------------------------------------------
        if full_mode:
            logger.warning("TELJES rebuild indult duty_log.json-ra!")
            if ctx:
                await ctx.send("```diff\n- [INFO] Teljes újraépítés mód aktiválva...\n```")
            try:
                if os.path.exists("duty_log.json"):
                    os.remove("duty_log.json")
                    duty_log.clear()
                    logger.info("Régi duty_log.json törölve")
                    if ctx:
                        await ctx.send("```diff\n- [INFO] Régi duty_log.json törölve.\n```")
                else:
                    logger.info("duty_log.json nem létezett, új építés indul.")
                    if ctx:
                        await ctx.send("```diff\n- [INFO] duty_log.json nem létezett, új építés indul.\n```")
            except Exception as e:
                logger.exception(f"Nem sikerült törölni a duty_log.json-t: {e}")
                if ctx:
                    await ctx.send(f"```diff\n- [HIBA] duty_log.json törlése nem sikerült: {e}\n```")

            after = None  # teljes újraépítés → minden üzenet
        else:
# ----------------------------------------------------------------
# NORMÁL FRISSÍTÉS: csak az utóbbi ~40 nap üzenetei
# ----------------------------------------------------------------
            after = dtmod.datetime.now(budapest_tz) - timedelta(days=40)
            if duty_log:
                try:
                    latest_ts = max(
                        dtmod.datetime.strptime(l["timestamp"], "%Y-%m-%d %H:%M")
                        for l in duty_log if "timestamp" in l
                    )
                    after = latest_ts - timedelta(minutes=120)
                except Exception:
                    logger.warning("Timestamp parsing hiba – fallback 40 napra.")
            if ctx:
                await ctx.send("```diff\n- [INFO] Üzenetek beolvasása a Discordról...\n```")
            logger.info("Duty-log beolvasás indul (normál frissítés).")

# -------------------------------------------------------------------
# BEOLVASÁS / FELDOLGOZÁS
# -------------------------------------------------------------------
        new_processed = 0
        async for msg in channel.history(limit=None, after=after):
            before_len = len(duty_log)
            await process_duty_message(msg)
            if len(duty_log) > before_len:
                new_processed += 1

        duty_log[:] = deduplicate_log()
        save_log()
        total = len(duty_log)

        msg_ok = (
            f"```diff\n+ [OK] Frissítés befejezve.\n"
            f"+ Új üzenetek: {new_processed}\n"
            f"+ Összesen: {total} rekord\n```"
        )
        logger.info(f"[CORE] Frissítés OK – új: {new_processed}, össz: {total}")
        if ctx:
            await ctx.send(msg_ok)

        return True

    except Exception as e:
        logger.exception(f"Frissítés hiba: {e}")
        if ctx:
            await ctx.send(f"```diff\n- [HIBA] Frissítés közben hiba történt: {e}\n```")
        return False

# ---------------------------------------------------------------------------
# FRISSÍTÉS / TELJES FRISSÍTÉS PARANCS (a core hívásával)
# ---------------------------------------------------------------------------
@bot.command(name="frissites", aliases=["frissítés", "frissités", "Frissítés", "frissites_full", "frissítés_full"])
@require_admin_channel()
@help_meta(
    category="Diagnosztika és karbantartás",
    usage="!frissites [teljes|full]",
    short="Duty-log frissítése a Discord duty-log csatornából.",
    details=(
        "Az EMS Duty bot belső duty-log adatbázisát frissíti a Discord duty-log "
        "csatorna üzenetei alapján. Alapértelmezésben csak az új, még nem importált "
        "üzeneteket dolgozza fel. Ha `teljes` vagy `full` módot adsz meg, akkor a bot "
        "a teljes csatorna-előzményt átnézi, és újraszámolja a mentett duty-időket. "
        "A parancs a frakciószabályzat szerinti hivatalos szolgálati idő elszámolás "
        "technikai alapját biztosítja."
    ),
    examples=[
        "!frissites",
        "!frissites teljes",
        "!frissites full",
    ],
)
async def frissites(ctx, mod: str = None):
    """Duty-log frissítése ('teljes' paraméterrel teljes újraépítés)."""
    full_mode = mód and mód.lower() == "teljes"
    await ctx.send("```diff\n- [INFO] Adatbázis frissítés indítása...\n```")
    await run_frissites_core(full_mode, ctx)

# ---------------------------------------------------------------------------
# HETI TOP PARANCSOK (heti_top + mehet)
# ---------------------------------------------------------------------------

# ==== Globális állapotváltozók ====
last_weekly_report_text = None
last_weekly_report_author = None
last_weekly_report_timestamp = None
last_weekly_report_offset = 0


def format_duration(minutes: int) -> str:
    """Óra:perc formázás."""
    h, m = divmod(minutes, 60)
    return f"{h} óra {m} perc"


def build_weekly_report(het_kezdete, het_vege, data):
    """Összeállítja a heti jelentés szövegét Discord-barát formában."""
    ossz_idoperc = {}
    utolso_rang = {}

    # ---- Adatok összegzése időtartomány szerint ----
    for entry in data:
        if "duration" not in entry:
            continue
        ts = dtmod.datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
        if not (het_kezdete <= ts < het_vege):
            continue

        name = entry.get("name_norm")
        position = entry.get("position", "")
        duration = int(entry.get("duration", 0))
        if not name:
            continue

        ossz_idoperc[name] = ossz_idoperc.get(name, 0) + duration
        utolso_rang[name] = position

    rangblokkok = {r: {} for r in DEDIKALT_RANGOK}
    vezetoi_blokk = {}

    for name_norm, perc in ossz_idoperc.items():
        pos = utolso_rang.get(name_norm, "Ismeretlen").replace("Mentő - ", "").strip()
        if any(v.lower() in pos.lower() for v in VEZETOSSEG):
            vezetoi_blokk[name_norm] = (perc, pos)
            continue
        talalat = None
        for r in DEDIKALT_RANGOK:
            if r.lower() in pos.lower():
                talalat = r
                break
        if talalat:
            rangblokkok[talalat][name_norm] = perc
        else:
            rangblokkok.setdefault("Ismeretlen", {})[name_norm] = perc

    # ---- Fejléc ----
    lines = []
    lines.append(f"📊 **Szolgálati idők**")
    lines.append(f"🗓️ {het_kezdete:%Y-%m-%d} és {het_vege:%Y-%m-%d} között")
    lines.append("──────────────────────────────")

    # ---- Rangblokkok ----
    for rang in DEDIKALT_RANGOK:
        taglista = rangblokkok.get(rang, {})
        if not taglista:
            continue

        lines.append("──────────────────────────────")
        lines.append(f"🏷️ **@{rang}**")
        lines.append("──────────────────────────────")

        for name, perc in sorted(taglista.items(), key=lambda x: x[1], reverse=True):
            dcid = get_discord_id_from_norm(name)
            mention = f"<@{dcid}>" if dcid else name  # fallback névre, ha nincs ID
            lines.append(f"> {mention} – {format_duration(perc)}")

        lines.append("")  # üres sor a rangok között

    # ---- Vezetőség ----
    if vezetoi_blokk:
        lines.append("──────────────────────────────")
        lines.append("👔 **Vezetőség**")
        lines.append("──────────────────────────────")
        for name, (perc, pos) in sorted(vezetoi_blokk.items(), key=lambda x: x[1][0], reverse=True):
            dcid = get_discord_id_from_norm(name)
            mention = f"<@{dcid}>" if dcid else name
            lines.append(f"> {mention} – {pos} – {format_duration(perc)}")
        lines.append("")

    # ---- TOP3 prémium ----
    dedikalt_sum = {n: p for r in rangblokkok.values() for n, p in r.items()}
    top3 = sorted(dedikalt_sum.items(), key=lambda x: x[1], reverse=True)[:3]
    premiumok = ["💰 *$3000 prémium*", "💰 *$2000 prémium*", "💰 *$1000 prémium*"]
    helyezes_ikon = ["🥇", "🥈", "🥉"]

    if top3:
        lines.append("\n🏆 **A hét legaktívabb mentősei:**")
        lines.append("──────────────────────────────")
        for i, (name, perc) in enumerate(top3):
            dcid = get_discord_id_from_norm(name)
            mention = f"<@{dcid}>" if dcid else name
            h, m = divmod(perc, 60)
            lines.append(
                f"{helyezes_ikon[i]} {mention}\n"
                f"\u2003**{h} óra {m} perc** {premiumok[i]}"
            )

            lines.append("")  # üres sor a helyezések között
        lines.append("──────────────────────────────")

    # ----- Záró üzenet -----
    lines.append("──────────────────────────────")
    lines.append("🙏 *Ha valaki eltérést tapasztal, jelezze a vezetőség felé.*")
    lines.append("")
    lines.append("💚 *Köszönjük a szolgálatot, minden mentősünknek!*")
    lines.append("")
    lines.append("<@315862356175486997>")
    lines.append("──────────────────────────────")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# !heti_top PARANCS – HETI TOPLISTA ELŐNÉZET
# ---------------------------------------------------------------------------
@bot.command(
    name="heti_top",
    aliases=["Heti Top", "heti top", "HETI_TOP", "Heti_Top"]
)
@require_admin_channel()
@help_meta(
    category="Szolgálati riportok",
    usage="!heti_top [offset]",
    short="Heti toplista előnézetet készít az admin csatornára.",
    details=(
        "A parancs legenerálja az adott hét EMS szolgálati toplistáját az **admin "
        "csatornára**, hogy a vezetőség ellenőrizhesse a publikálás előtt.\n\n"
        "**Működés:**\n"
        "• az aktuális hét (hétfő 00:00 → vasárnap 23:59) adatait összegzi\n"
        "• negatív offsettel korábbi hetek kérhetők le (pl. `-1` = előző hét)\n"
        "• pozitív offsettel jövőbeli hetek NEM léteznek, de engedélyezett az eltolás\n"
        "• a generált jelentés NEM kerül automatikusan publikálásra\n"
        "• a publikálást a **!mehet** parancs végzi\n\n"
        "A parancs a jelentést eltárolja belső változókban, hogy a `!mehet` "
        "közzé tudja tenni a megfelelő csatornában."
    ),
    examples=[
        "!heti_top",
        "!heti_top 0",
        "!heti_top -1",
        "!heti_top 1",
        "# majd publikálás:",
        "!mehet",
    ]
)
async def heti_top(ctx, offset: int = 0):
    """Heti toplista előnézete az admin csatornán."""
    global last_weekly_report_text, last_weekly_report_author
    global last_weekly_report_timestamp, last_weekly_report_offset

    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("```diff\n- [HIBA] Ezt a parancsot csak az admin csatornán lehet használni.\n```")
        return

    JSON_FILE = "duty_log.json"
    if not os.path.exists(JSON_FILE):
        await ctx.send(f"```diff\n- [HIBA] A {JSON_FILE} nem található.\n```")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Időintervallum számítása (aktuális hét hétfő–vasárnap)
    ma = dtmod.datetime.now(budapest_tz)
    napok_vasarnapig = (ma.weekday() + 1) % 7
    het_vege = (ma - timedelta(days=napok_vasarnapig)).replace(hour=0, minute=0, second=0, microsecond=0)
    het_kezdete = het_vege - timedelta(days=7)

    # Offset kezelése
    if offset != 0:
        het_kezdete += timedelta(days=7 * offset)
        het_vege += timedelta(days=7 * offset)

    szoveg = build_weekly_report(het_kezdete, het_vege, data)

    # Utolsó jelentés eltárolása
    last_weekly_report_text = szoveg
    last_weekly_report_author = ctx.author.id
    last_weekly_report_timestamp = dtmod.datetime.now(budapest_tz)
    last_weekly_report_offset = offset

    await ctx.send(
        "```diff\n+ [INFO] Heti toplista előnézet generálva. "
        "Használd a !mehet parancsot a közzétételhez.\n```"
    )
    await ctx.send(szoveg)

# ---------------------------------------------------------------------------
# !mehet PARANCS – HETI TOPLISTA PUBLIKÁLÁSA
# ---------------------------------------------------------------------------
@bot.command(name="mehet", aliases=["Mehet", "MEHET"])
@require_admin_channel()
@help_meta(
    category="Szolgálati riportok",
    usage="!mehet",
    short="A legutóbb generált heti toplista publikálása.",
    details=(
        "A parancs a `!heti_top` által legenerált toplistát átmásolja a "
        "hivatalos **heti-munkaidők** csatornára.\n\n"
        "A működés feltételei:\n"
        "• csak az admin csatornán futtatható\n"
        "• csak az a személy publikálhatja, aki a toplistát generálta\n"
        "• a toplista **max. 24 órája készült**, különben újra kell generálni\n"
        "• csak az **aktuális hét** toplistája tehető közzé (offset=0)\n\n"
        "Sikeres publikálás után a bot törli a korábbi toplista-adatokat a "
        "memóriából."
    ),
    examples=[
        "!heti_top      # előnézet generálása",
        "!mehet         # publikálás",
    ]
)
async def mehet(ctx):
    """Elküldi az utolsó generált heti toplistát a heti-munkaidők csatornára."""
    global last_weekly_report_text, last_weekly_report_author
    global last_weekly_report_timestamp, last_weekly_report_offset

    if ctx.channel.id != ADMIN_CHANNEL_ID:
        await ctx.send("```diff\n- [HIBA] Ez a parancs csak az admin csatornán működik.\n```")
        return

    if not last_weekly_report_text:
        await ctx.send(
            "```diff\n- [HIBA] Nincs elérhető heti toplista. "
            "+ Használd először a !heti_top parancsot.\n```"
        )
        return

    now = dtmod.datetime.now(budapest_tz)
    if last_weekly_report_timestamp:
        diff_hours = (now - last_weekly_report_timestamp).total_seconds() / 3600
        if diff_hours > 24:
            logger.warning(
                f"[WEEKLY_REPORT_BLOCKED] {ctx.author} – toplista 24 órán túl: {diff_hours:.2f} óra"
            )
            await ctx.send(
                "```diff\n- [HIBA] A toplista több mint 24 órája készült, ezért nem publikálható.\n"
                "+ Kérlek, generálj új toplistát a !heti_top paranccsal.\n```"
            )
            return

    if last_weekly_report_offset != 0:
        logger.warning(
            f"[WEEKLY_REPORT_BLOCKED] {ctx.author} – próbált publikálni offset={last_weekly_report_offset}"
        )
        await ctx.send(
            "```diff\n- [HIBA] Csak az aktuális heti toplista publikálható.\n"
            "+ Az előző hetek (pl. -1, -2) csak előnézetként tekinthetők meg.\n```"
        )
        return

    if ctx.author.id != last_weekly_report_author:
        await ctx.send(
            "```diff\n- [HIBA] Csak az a személy publikálhatja, aki generálta a toplistát.\n```"
        )
        return

    channel = bot.get_channel(WEEKLY_DUTY_CHANNEL_ID)
    if not channel:
        await ctx.send("```diff\n- [HIBA] A heti-munkaidők csatorna nem található.\n```")
        return

    await channel.send(last_weekly_report_text)
    await ctx.send("✅ Heti jelentés átmásolva a heti-munkaidők csatornára.")
    logger.info(
        f"[WEEKLY_REPORT_PUBLISHED] {ctx.author} – toplista sikeresen publikálva."
    )

    # Memória ürítése
    last_weekly_report_text = None
    last_weekly_report_author = None
    last_weekly_report_timestamp = None
    last_weekly_report_offset = 0

# ---------------------------------------------------------------------------
# JELEN PARANCS – AKTUÁLISAN SZOLGÁLATBAN LÉVŐK LEKÉRÉSE
# ---------------------------------------------------------------------------
@bot.command(
    name="jelen",
    aliases=["Jelen", "JELEN", "Szolgálatban", "szolgálatban", "szolgalatban"]
)
@require_admin_channel()
@help_meta(
    category="Szolgálati riportok",
    usage="!jelen",
    short="Megmutatja, hogy kik vannak jelenleg szolgálatban a legfrissebb adatok alapján.",
    details=(
        "A parancs megvizsgálja az elmúlt 48 óra duty-log üzeneteit, frissíti a belső "
        "adatbázist, majd kilistázza, hogy kik vannak **aktuálisan szolgálatban**.\n\n"
        "**A működés fő lépései:**\n"
        "1) Az elmúlt 2 nap összes duty-log üzenetének feldolgozása.\n"
        "2) A frissített `duty_log.json` betöltése.\n"
        "3) Csak az utolsó ismert státusz alapján „felvette” állapotú személyek "
        "kiszűrése.\n"
        "4) Duplikátumok eltávolítása.\n"
        "5) Rangsorrend szerinti rendezés (vezetők → dedikált rangok → mindenki más).\n"
        "6) Figyelmeztetés, ha valaki a megengedett maximális óraszám felett van "
        "szolgálatban (‼️ ikon + óra kiírása).\n\n"
        "**Kimeneti formátum:**\n"
        "A bot először jelzi a frissítés indítását:\n"
        "```\n"
        "🔄 Adatbázis frissítése folyamatban...\n"
        "✅ Frissítés kész (XX üzenet, YY.s alatt).\n"
        "```\n"
        "Majd egy táblázatszerű listában megjeleníti az aktívakat:\n"
        "```\n"
        "Szolgálatban van N fő az elmúlt 48 órát figyelembe véve:\n"
        "✅ Név1 | Rang | 2025-11-14 17:01\n"
        "‼️ Név2 | Rang | 2025-11-14 10:22 ⚠️ (13h)\n"
        "...\n"
        "```\n\n"
        "**Ikonok jelentése:**\n"
        "• ✅ – normál szolgálatban\n"
        "• ‼️ – túl hosszú szolgálat (túllépte a MAX_ON_DUTY_HOURS értéket)\n"
        "• ⚠️ – megjelenik a pontos szolgálatban töltött óraszám\n\n"
        "A parancs automatikusan igazítja a név- és rangoszlop szélességét a "
        "táblázatos, áttekinthető megjelenítéshez."
    ),
    examples=[
        "!jelen",
        "!szolgálatban",
        "!Jelen",
        (
            "Minta kimenet:\n"
            "```\n"
            "🔄 Adatbázis frissítése folyamatban a pontos eredmény elérése végett...\n"
            "✅ Frissítés kész (46 üzenet, 9.9 s alatt).\n\n"
            "Szolgálatban van 1 fő az elmúlt 48 órát figyelembe véve:\n"
            "✅ Dr. Hans Heinkel Hesserschmit | Szakorvos | 2025-11-14 17:01\n"
            "```"
        )
    ]
)
async def jelen(ctx):
    """Valós adatokból mutatja, kik vannak szolgálatban, előtte 2 napos frissítéssel."""
    import json
    import asyncio
    from datetime import datetime, timedelta

    DUTY_JSON = "duty_log.json"
    await ctx.send("🔄 Adatbázis frissítése folyamatban a pontos eredmény elérése végett...")

    # --- 1️⃣ Duty-log frissítés az utolsó 2 napból ---
    processed = 0
    start_time = dtmod.datetime.now(budapest_tz)
    try:
        channel = bot.get_channel(int(os.getenv("DUTY_LOG_CHANNEL_ID")))
        if channel:
            after = dtmod.datetime.now(budapest_tz) - timedelta(days=2)
            async for msg in channel.history(limit=None, after=after):
                await process_duty_message(msg)
                processed += 1
                if processed % 200 == 0:
                    await ctx.send(f"📥 {processed} üzenet feldolgozva...")
                await asyncio.sleep(0.2)
            elapsed = (dtmod.datetime.now(budapest_tz) - start_time).total_seconds()
            await ctx.send(f"✅ Frissítés kész ({processed} üzenet, {elapsed:.1f} s alatt).")
        else:
            await ctx.send("⚠️ Duty-log csatorna nem található, frissítés kihagyva.")
    except Exception as e:
        await ctx.send(f"⚠️ Duty-log frissítés sikertelen: {e}")
        logger.warning(f"[JELEN] Duty-log frissítés sikertelen: {e}")

    # --- 2️⃣ JSON betöltés ---
    if not os.path.exists(DUTY_JSON):
        await ctx.send(f"```diff\n- [HIBA] {DUTY_JSON} fájl nem található.\n```")
        return

    with open(DUTY_JSON, "r", encoding="utf-8") as f:
        entries = json.load(f)

    # --- 3️⃣ Csak az utolsó 2 napból származó bejegyzéseket nézzük ---
    cutoff = dtmod.datetime.now(budapest_tz) - timedelta(days=2)
    recent_entries = []
    for e in entries:
        try:
            ts = dtmod.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
            if ts >= cutoff:
                recent_entries.append(e)
        except Exception:
            continue

    # fallback 5 napra
    if not recent_entries:
        cutoff = dtmod.datetime.now(budapest_tz) - timedelta(days=5)
        for e in entries:
            try:
                ts = dtmod.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
                if ts >= cutoff:
                    recent_entries.append(e)
            except Exception:
                continue

    # --- 4️⃣ Aktív személyek kiszűrése ---
    vezetoseg = [x.strip() for x in os.getenv("VEZETOSSEG", "").split(",") if x.strip()]
    dedikalt = [x.strip() for x in os.getenv("DEDIKALT_RANGOK", "").split(",") if x.strip()]

    state = {}
    for e in sorted(recent_entries, key=lambda x: x.get("timestamp", "")):
        key = e.get("person_key") or e.get("name_norm")
        if key:
            state[key] = e.get("type")

    active = [
        e for e in recent_entries
        if (e.get("person_key") or e.get("name_norm")) in state
        and state[e.get("person_key") or e.get("name_norm")] == "felvette"
        and e.get("type") == "felvette"
    ]

    # --- 5️⃣ Duplikátumok eltávolítása ---
    seen = {}
    for e in sorted(active, key=lambda x: x.get("timestamp", "")):
        key = e.get("person_key") or e.get("name_norm")
        seen[key] = e
    active = list(seen.values())

    if not active:
        await ctx.send("```diff\n- Jelenleg senki sincs szolgálatban!\n```")
        return

    # --- 6️⃣ Rangsorrend és formázás ---
    def rank_priority(position: str) -> int:
        pos = position.lower()
        for i, r in enumerate(vezetoseg):
            if r.lower() in pos:
                return i
        base = len(vezetoseg)
        for j, r in enumerate(dedikalt):
            if r.lower() in pos:
                return base + j
        return base + len(dedikalt) + 999

    active_sorted = sorted(active, key=lambda e: rank_priority(e.get("position", "")))

    lines = [f"Szolgálatban van {len(active_sorted)} fő az elmúlt 48 órát figyelembe véve:"]
    max_name_len = max(len(e.get("name", "")) for e in active_sorted)
    max_rank_len = max(len(e.get("position", "").replace("Mentő - ", "").strip()) for e in active_sorted)
    limit_hours = int(os.getenv("MAX_ON_DUTY_HOURS", "12"))

    for e in active_sorted:
        name = e.get("name", "")
        position = (
            e.get("position", "")
            .replace("Mentő - ", "")
            .replace("Igazgató-helyettes", "Ig. helyettes")
            .replace("Osztályvezető-helyettes", "Osztv. helyettes")
            .strip()
        )
        start_time = e.get("start_time", e.get("timestamp", ""))
        emoji = "✅"
        warning = ""

        try:
            start_dt = dtmod.datetime.strptime(start_time, "%Y-%m-%d %H:%M").replace(tzinfo=budapest_tz)
            diff_hours = (dtmod.datetime.now(budapest_tz) - start_dt).total_seconds() / 3600
            if diff_hours > limit_hours:
                emoji = "‼️"
                warning = f" ⚠️ ({int(diff_hours)}h)"
        except Exception:
            pass

        lines.append(
            f"{emoji} {name.ljust(max_name_len)} | {position.ljust(max_rank_len - 5)} | {start_time}{warning}"
        )

    msg = "```\n" + "\n".join(lines) + "\n```"
    await ctx.send(msg)

# ===========================================================================
# TESZT JELEN PARANCS – HAMIS JSON ÉS UTOLSÓ N ESEMÉNY ALAPJÁN
# ---------------------------------------------------------------------------

@bot.command(
    name="teszt_jelen",
    aliases=["teszt jelen", "Teszt jelen", "TESZT_JELEN"]
)
@require_admin_channel()
@help_meta(
    category="Admin funkciók",
    usage="!teszt_jelen",
    short="A !jelen parancs működésének bemutatása tesztadatokkal.",
    details=(
        "A parancs kizárólag akkor aktív, ha a környezeti változó "
        "`TEST_MODE=1`. Ekkor a bot N utolsó eseményt tölt be egy "
        "tesztfájlból (alapértelmezetten: `hamis_duty_log.json`), és "
        "ezekből próbálja meghatározni, kik vannak 'szolgálatban'.\n\n"
        "Ez a parancs NEM olvas Discord duty-log üzeneteket, semmilyen módon "
        "nem módosítja az éles adatbázist. Célja kizárólag a vezetők számára "
        "a !jelen parancs működésének demonstrálása olyan helyzetben, amikor "
        "valójában nincs aktív szolgálat.\n\n"
        "**A működés lépései:**\n"
        "• hamis duty-log beolvasása (TEST_MODE_FILE)\n"
        "• az utolsó N rekord kiválasztása (TEST_MODE_RECORD_LIMIT)\n"
        "• státusz meghatározása az utolsó esemény elve alapján\n"
        "• rang szerinti rendezés (VEZETOSSEG / DEDIKALT_RANGOK)\n"
        "• az eredmény formázása a !jelen kimenetéhez hasonlóan"
    ),
    examples=[
        "!teszt_jelen",
        "# ha TEST_MODE=0 → jelzi, hogy a teszt mód inaktív"
    ]
)
async def teszt_jelen(ctx):
    """Teszt üzem: hamis_duty_log.json alapján mutatja a szolgálatban lévőket, frissítés nélkül."""
    TEST_MODE = int(os.getenv("TEST_MODE", "0"))
    if TEST_MODE != 1:
        await ctx.send("⚠️ Teszt mód ki van kapcsolva (`TEST_MODE=0`).")
        return

    TEST_FILE = os.getenv("TEST_MODE_FILE", "hamis_duty_log.json")
    LIMIT = int(os.getenv("TEST_MODE_RECORD_LIMIT", "10"))

    if not os.path.exists(TEST_FILE):
        await ctx.send(f"```diff\n- [TESZT HIBA] Teszt fájl nem található: {TEST_FILE}\n```")
        return

    # Hamis duty log beolvasása
    try:
        with open(TEST_FILE, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as e:
        await ctx.send(f"```diff\n- [TESZT HIBA] JSON olvasási hiba: {e}\n```")
        return

    # Utolsó N rekord
    entries = entries[-LIMIT:]

    # Ranglisták (ENV változókból)
    VEZETOSSEG = [x.strip() for x in os.getenv("VEZETOSSEG", "").split(",") if x.strip()]
    DEDIKALT_RANGOK = [x.strip() for x in os.getenv("DEDIKALT_RANGOK", "").split(",") if x.strip()]

    # Utolsó esemény elve: aki utoljára "felvette", az aktív
    state = {}
    for e in entries:
        key = e.get("person_key") or e.get("name_norm")
        if key:
            state[key] = e

    active = [v for v in state.values() if v.get("type") == "felvette"]

    if not active:
        await ctx.send(f"🧪 ```diff\n- TESZT: senki sincs szolgálatban (utolsó {LIMIT} esemény alapján)\n```")
        return

    # Rendezés rang szerint
    def rank_priority_test(position):
        pos = (position or "").lower()
        for i, r in enumerate(VEZETOSSEG):
            if r.lower() in pos:
                return i
        base = len(VEZETOSSEG)
        for j, r in enumerate(DEDIKALT_RANGOK):
            if r.lower() in pos:
                return base + j
        return base + len(DEDIKALT_RANGOK) + 999

    active_sorted = sorted(active, key=lambda x: rank_priority_test(x.get("position", "")))

    # Hamis frissítés imitáció
    await ctx.send("🔧 Teszt adatbázis-frissítés folyamatban…")
    await asyncio.sleep(1)
    await ctx.send(f"✅ Teszt frissítés kész ({len(entries)} teszt esemény feldolgozva).")

    # Formázás
    lines = [f"🧪 TESZT – Szolgálatban van {len(active_sorted)} fő (utolsó {LIMIT} esemény alapján):"]
    for e in active_sorted:
        name = e.get("name", "")
        pos = e.get("position", "").replace("Mentő - ", "").strip()
        ts = e.get("start_time", e.get("timestamp", ""))
        lines.append(f"✅ {name:<22} | {pos:<19} | {ts}")

    msg = "```\n" + "\n".join(lines) + "\n```"
    await ctx.send(msg)

# ===========================================================================
# RESTART PARANCS – A BOT ÚJRAINDÍTÁSA WATCHDOG FELÜGYELET ALATT
# ===========================================================================
@bot.command(name="restart", aliases=["RESTART", "Restart", "ujraindit", "újraindít", "Újraindít"])
@require_admin_channel()
@help_meta(
    category="Diagnosztika és karbantartás",
    usage="!restart",
    short="Manuális bot-újraindítás a NAS watchdog rendszerével.",
    details=(
        "A parancs az EMS Duty Bot azonnali újraindítását kezdeményezi. "
        "A folyamat biztonságosan leállítja a futó példányt, majd a NAS "
        "watchdog (hotloader) pár másodpercen belül újraindítja a botot.\n\n"
        "A parancs **csak admin csatornáról** működik, és használata előtt "
        "ellenőrizni kell, hogy nincs-e futásban kritikus adatfrissítés.\n\n"
        "A parancs létrehozza a `restart_reason.txt` fájlt, hogy a watchdog "
        "meg tudja különböztetni a manuális és hibás leállásokat."
    ),
    examples=[
        "!restart",
        "!ujraindit",
        "!Újraindít",
    ]
)
async def restart(ctx):
    """A bot manuális újraindítása NAS watchdog felügyelettel."""
    try:
        await ctx.send("```diff\n- [INFO] EMS bot újraindítása folyamatban...\n```")

        # 🔹 restart indok lementése, hogy a watchdog tudja mi történt
        with open("restart_reason.txt", "w", encoding="utf-8") as f:
            f.write("manual")

        logger.info("Manuális újraindítás kezdeményezve az admin csatornáról.")

        os._exit(41)  # watchdog újraindítja

    except Exception as e:
        await ctx.send(f"```diff\n- [HIBA] Nem sikerült az újraindítás: {e}\n```")
        logger.error(f"Újraindítás hiba: {e}")

# ---------------------------------------------------------------------------
# BETOPPANÓ EXPORT PARANCS – nap / intervallum / teljes export
# ---------------------------------------------------------------------------
@bot.command(
    name="betoppano_export",
    aliases=["betoppano export", "betoppanó"]
)
@require_admin_channel()
@help_meta(
    category="Admin funkciók",
    usage="!betoppano_export [YYYY-MM-DD] [YYYY-MM-DD]",
    short="A #betoppanó csatorna üzeneteinek exportálása (nap / tartomány / teljes).",
    details=(
        "A parancs a #betoppanó csatorna üzeneteit exportálja JSON fájlba. "
        "Háromféle módon használható:\n\n"
        "1) **Teljes export:**\n"
        "   `!betoppano_export`\n"
        "   → minden üzenet mentése\n\n"
        "2) **Napi export:**\n"
        "   `!betoppano_export YYYY-MM-DD`\n"
        "   → csak az adott nap üzenetei mentődnek\n\n"
        "3) **Intervallum export:**\n"
        "   `!betoppano_export YYYY-MM-DD YYYY-MM-DD`\n"
        "   → az első és második nap közötti üzenetek mentése\n\n"
        "A rendszer automatikusan kezeli a különböző kötőjelet (\"-\", \"–\", \"—\"), "
        "és létrehozza az *exports/* mappát, ha nem létezik.\n\n"
        "Az eredmény egy jól olvasható UTF-8 JSON fájl, időbélyegekkel, szerzővel, "
        "tartalommal és mention-listával."
    ),
    examples=[
        "!betoppano_export",
        "!betoppano_export 2025-01-01",
        "!betoppano_export 2025-01-01 2025-01-07",
        "!betoppanó 2025-02-02 – 2025-02-05",
    ]
)
async def betoppano_export(ctx, *args):
    """Letölti a #betoppanó csatorna üzeneteit, opcionális dátumszűréssel."""
    channel_id = 1280885410960113768  # betoppanó
    ch = bot.get_channel(channel_id)
    if not ch:
        await ctx.send(f"```diff\n- [HIBA] Betoppanó csatorna nem található (ID: {channel_id}).\n```")
        return

    # Segéd: YYYY-MM-DD parse
    def parse_ymd(s):
        try:
            return dtmod.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=budapest_tz)
        except Exception:
            return None

    # Argumentum normalizálás
    args_norm = [a.strip() for a in args if a.strip()]

    # Formátum: YYYY-MM-DD - YYYY-MM-DD
    if len(args_norm) == 3 and args_norm[1] in ("-", "–", "—"):
        args_norm = [args_norm[0], args_norm[2]]

    after_dt_utc = None
    before_dt_utc = None

    # Export logika
    if len(args_norm) == 0:
        mode_text = "teljes export"
        export_file = "exports/betoppano_full.json"

    elif len(args_norm) == 1:
        d1 = parse_ymd(args_norm[0])
        if not d1:
            await ctx.send(f"```diff\n- [HIBA] Hibás dátum: {args_norm[0]} (ÉÉÉÉ-HH-NN)\n```")
            return

        d2 = d1 + timedelta(days=1)
        after_dt_utc = d1.astimezone(pytz.utc)
        before_dt_utc = d2.astimezone(pytz.utc)

        mode_text = f"napi export: {d1.strftime('%Y-%m-%d')}"
        export_file = f"exports/betoppano_{d1.strftime('%Y_%m_%d')}.json"

    elif len(args_norm) == 2:
        d1 = parse_ymd(args_norm[0])
        d2 = parse_ymd(args_norm[1])
        if not d1 or not d2:
            await ctx.send("```diff\n- [HIBA] Hibás dátumtartomány (ÉÉÉÉ-HH-NN ...)\n```")
            return

        # ha a tartomány fordított
        if d2 < d1:
            d1, d2 = d2, d1

        after_dt_utc = d1.astimezone(pytz.utc)
        before_dt_utc = (d2 + timedelta(days=1)).astimezone(pytz.utc)

        mode_text = f"intervallum: {d1:%Y-%m-%d} → {d2:%Y-%m-%d}"
        export_file = (
            f"exports/betoppano_{d1.strftime('%Y_%m_%d')}"
            f"_{d2.strftime('%Y_%m_%d')}.json"
        )
    else:
        await ctx.send("```diff\n- [HIBA] Használat: !betoppano_export [YYYY-MM-DD] [YYYY-MM-DD]\n```")
        return

    # Mappa biztosítása
    os.makedirs("exports", exist_ok=True)

    await ctx.send(
        f"```diff\n- [INFO] Üzenetek letöltése a #{ch.name} csatornáról… ({mode_text})```"
    )

    # Üzenetek gyűjtése
    def clean_name(s):
        if not s:
            return None
        return "".join(ch for ch in s if ch.isprintable() and ord(ch) < 0xFFFF)

    entries = []
    history_kwargs = {"limit": None, "oldest_first": True}
    if after_dt_utc:
        history_kwargs["after"] = after_dt_utc
    if before_dt_utc:
        history_kwargs["before"] = before_dt_utc

    async for msg in ch.history(**history_kwargs):
        entries.append({
            "id": msg.id,
            "author": str(msg.author),
            "author_id": getattr(msg.author, "id", None),
            "author_display": clean_name(getattr(msg.author, "display_name", None)),
            "content": msg.content,
            "created_at": msg.created_at.astimezone(budapest_tz).strftime("%Y-%m-%d %H:%M:%S"),
            "mentions": [m.id for m in msg.mentions],
        })

    # Mentés
    with open(export_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    await ctx.send(f"```diff\n+ [OK] {len(entries)} üzenet mentve → {export_file}```")

# ---------------------------------------------------------------------------
# DIAGNOSZTIKA PARANCS – KONZISZTENCIA ELLENŐRZÉS
# ---------------------------------------------------------------------------
@bot.command(name="diagnosztika", aliases=["diag"])
@require_admin_channel()
@help_meta(
    category="Diagnosztika és karbantartás",
    usage="!diagnosztika",
    short="A bot adatfájljainak konzisztencia-ellenőrzése.",
    details=(
        "A parancs ellenőrzi a bothoz tartozó három kulcsfontosságú adatfájl "
        "létezését és tartalmát:\n"
        "• betoppano_log.json\n"
        "• discord_user_ids.json\n"
        "• char_to_discord_name.json\n\n"
        "A vizsgálat kiterjed a JSON formátumra, a beolvashatóságra, az elemszámra "
        "és az adatkapcsolatok konzisztenciájára is (pl. létező Discord-névhez "
        "tartozik-e ID-térképi bejegyzés)."
    ),
    examples=[
        "!diagnosztika",
        "!diag",
    ]
)
async def diagnosztika(ctx):
    """Gyors ellenőrzés: betoppano_log.json, discord_user_ids.json, char_to_discord_name.json konzisztencia."""
    import json

    files = {
        "betoppano_log.json": None,
        "discord_user_ids.json": None,
        "char_to_discord_name.json": None,
    }

    # Ellenőrizzük a fájlok meglétét és tartalmát
    for fname in files:
        if not os.path.exists(fname):
            files[fname] = f"❌ Nem található"
            continue
        try:
            with open(fname, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    files[fname] = f"✅ {len(data)} elem"
                elif isinstance(data, dict):
                    files[fname] = f"✅ {len(data)} kulcs"
                else:
                    files[fname] = f"⚠️ Ismeretlen formátum"
        except Exception as e:
            files[fname] = f"❌ Hiba beolvasáskor: {e}"

    # Kapcsolati arányok (ha minden megvan)
    found_pairs = 0
    missing_in_ids = 0
    if os.path.exists("char_to_discord_name.json") and os.path.exists("discord_user_ids.json"):
        try:
            with open("char_to_discord_name.json", "r", encoding="utf-8") as f:
                char_map = json.load(f)
            with open("discord_user_ids.json", "r", encoding="utf-8") as f:
                id_map = json.load(f)

            for char_name, discord_name in char_map.items():
                if discord_name.lower().strip() in id_map:
                    found_pairs += 1
                else:
                    missing_in_ids += 1
        except Exception:
            pass

    summary = (
        "```diff\n"
        f"+ betoppano_log.json: {files['betoppano_log.json']}\n"
        f"+ discord_user_ids.json: {files['discord_user_ids.json']}\n"
        f"+ char_to_discord_name.json: {files['char_to_discord_name.json']}\n"
        "-------------------------------------\n"
        f"+ Összerendelések OK: {found_pairs}\n"
        f"- Hiányzó Discord-név az ID-térképből: {missing_in_ids}\n"
        "```"
    )
    await ctx.send(summary)

# ---------------------------------------------------------------------------
# KARAKTER- ÉS DISCORD NÉV ÖSSZEKAPCSOLÁSA PARANCS
# ---------------------------------------------------------------------------
@bot.command(
    name="pair_char",
    aliases=["pair", "charpair", "karakter_osszekotes"]
)
@require_admin_channel()
@help_meta(
    category="Adatkezelés",
    usage='!pair_char "FiveM név" "Discord név"',
    short="Összekapcsol egy FiveM karakternevet egy Discord névvel.",
    details=(
        "A parancs összeköti egy EMS dolgozó **FiveM karakternevét** a "
        "Discord nevükkel. Az összerendelések a "
        "`char_to_discord_name.json` fájlban tárolódnak.\n\n"
        "**A működés:**\n"
        "• két paraméter szükséges: FiveM név és Discord név\n"
        "• a bot normalizálja a neveket (kisbetű, felesleges szóközök törlése)\n"
        "• ha a név új → hozzáadás\n"
        "• ha már létezik → jelzi, hogy nincs változás\n"
        "• ha eltér → frissítés (régi érték is megjelenik)\n\n"
        "Ez a parancs alapvető ahhoz, hogy a szolgálati riportok helyes "
        "személynévhez tudják kötni a duty-időket."
    ),
    examples=[
        '!pair_char "Dr. Water White" "Gery"',
        '!pair "John Stone" "LeaderMilan"',
        '!karakter_osszekotes "Kovacs Bela" "Kovi"',
    ]
)
async def pair_char(ctx, fivem_nev: str = None, discord_nev: str = None):
    """
    FiveM karakter és Discord név összekapcsolása.
    Használat:
    !pair_char "FiveM név" "Discord név"
    """
    CHAR_TO_DISCORD_NAME_FILE = "char_to_discord_name.json"

    # --- alapellenőrzés ---
    if not fivem_nev or not discord_nev:
        await ctx.send(
            "```diff\n- Használat: !pair_char \"FiveM név\" \"Discord név\"\n"
            "+ Példa: !pair_char \"Dr. Water White\" \"Gery\"\n```"
        )
        return

    # --- normalizáló belső segéd ---
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    fivem_norm = _norm(fivem_nev)
    discord_norm = _norm(discord_nev)

    # --- JSON beolvasás vagy új létrehozás ---
    if os.path.exists(CHAR_TO_DISCORD_NAME_FILE):
        try:
            with open(CHAR_TO_DISCORD_NAME_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            mapping = {}
    else:
        mapping = {}

    # --- állapotváltozás detektálása ---
    previous = mapping.get(fivem_norm)
    mapping[fivem_norm] = discord_norm

    # --- fájl mentés ---
    try:
        with open(CHAR_TO_DISCORD_NAME_FILE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
    except Exception as e:
        await ctx.send(f"```diff\n- Mentési hiba: {e}\n```")
        return

    # --- visszajelzés ---
    if previous is None:
        msg = f"+ Hozzáadva: {fivem_norm} → {discord_norm}"
    elif previous == discord_norm:
        msg = f"= Már létezik: {fivem_norm} → {discord_norm}"
    else:
        msg = f"~ Frissítve: {fivem_norm} → {discord_norm} (régi: {previous})"

    await ctx.send(f"```diff\n{msg}\n```")

# ---------------------------------------------------------------------------
# KARAKTER- ÉS DISCORD NÉV PÁROSÍTÁSOK LISTÁZÁSA PARANCS
# ---------------------------------------------------------------------------
@bot.command(
    name="char_lista",
    aliases=["charlist", "karakter_lista", "lista_char"]
)
@require_admin_channel()
@help_meta(
    category="Adatkezelés",
    usage="!char_lista",
    short="Listázza a FiveM ↔ Discord névpárosításokat.",
    details=(
        "A parancs megjeleníti az összes olyan párosítást, amelyet a "
        "`!pair_char` segítségével hoztak létre. Az adatokat a "
        "`char_to_discord_name.json` fájlból olvassa ki.\n\n"
        "**A működés:**\n"
        "• ha a fájl nem létezik → jelzi, hogy még nem történt összerendelés\n"
        "• ha üres → megjeleníti, hogy nincs adat\n"
        "• ha sok a rekord → 1800 karakterenként darabolja a kimenetet\n\n"
        "Formátum:\n"
        "`FiveM karakter név → Discord név`\n\n"
        "Kizárólag admin csatornán használható."
    ),
    examples=[
        "!char_lista",
        "!karakter_lista",
        "!lista_char",
    ]
)
async def char_lista(ctx):
    """Megjeleníti a FiveM karakter ↔ Discord név párosításokat."""
    CHAR_TO_DISCORD_NAME_FILE = "char_to_discord_name.json"

    # --- Fájl ellenőrzés ---
    if not os.path.exists(CHAR_TO_DISCORD_NAME_FILE):
        await ctx.send(
            "```diff\n- A char_to_discord_name.json fájl még nem létezik.\n"
            "+ Használd előbb a !pair_char parancsot a létrehozásához.\n```"
        )
        return

    # --- JSON beolvasás ---
    try:
        with open(CHAR_TO_DISCORD_NAME_FILE, "r", encoding="utf-8") as f:
            mapping = json.load(f)
    except Exception as e:
        await ctx.send(f"```diff\n- Hiba a fájl beolvasásakor: {e}\n```")
        return

    if not mapping:
        await ctx.send("```diff\n- A fájl üres, még nincsenek párosítások.\n```")
        return

    # --- Lista előkészítés ---
    lines = [
        f"+ {char} → {discord}"
        for char, discord in sorted(mapping.items())
    ]
    output = "\n".join(lines)

    # --- Hosszú kimenet darabolása ---
    chunks = [output[i:i+1800] for i in range(0, len(output), 1800)]

    for idx, part in enumerate(chunks, start=1):
        header = (
            f"```diff\n"
            f"# FiveM ↔ Discord párosítások ({idx}/{len(chunks)})\n"
            f"{part}\n"
            f"```"
        )
        await ctx.send(header)

# ---------------------------------------------------------------------------
# AUTOMATIKUS NAPI FRISSÍTÉS (04:00)
# ---------------------------------------------------------------------------
async def auto_refresh_task():
    """Minden nap 04:00-kor automatikus adatbázis-frissítés."""
    await bot.wait_until_ready()

    while not bot.is_closed():
        now = dtmod.datetime.now(budapest_tz)
        target = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if target <= now:
            target += dtmod.timedelta(days=1)
        wait_seconds = (target - now).total_seconds()

        logger.info(f"[AUTO_REFRESH_WAIT] Következő frissítés: {target}")
        await asyncio.sleep(wait_seconds)

        admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
        timestamp = dtmod.datetime.now(budapest_tz).strftime("%Y-%m-%d %H:%M:%S")

        try:
            if admin_channel:
                await admin_channel.send("```diff\n- [INFO] Napi automatikus frissítés indul (04:00)...\n```")

            start_time = dtmod.datetime.now(budapest_tz)
            success = await run_frissites_core(full_mode=False)
            duration = (dtmod.datetime.now(budapest_tz) - start_time).total_seconds()

            if admin_channel:
                if success:
                    await admin_channel.send(f"```diff\n+ [OK] Automatikus frissítés befejezve ({duration:.1f} mp)\n```")
                else:
                    await admin_channel.send(f"```diff\n- [HIBA] Automatikus frissítés közben hiba történt\n```")

            logger.info(f"[AUTO_REFRESH_END] {timestamp} – sikeres: {success} ({duration:.1f} mp).")

        except Exception as e:
            logger.exception(f"[AUTO_REFRESH_ERROR] {timestamp}: {e}")
            if admin_channel:
                await admin_channel.send(f"```diff\n- [HIBA] Automatikus frissítés sikertelen: {e}\n```")
# ---------------------------------------------------------------------------
# AUTOMATIKUS NAPI FRISSÍTÉS – INFORMÁCIÓS (PSZEUDO) PARANCS
# ---------------------------------------------------------------------------
@bot.command(
    name="auto_refresh_info",
    aliases=["auto_refresh", "autorefresh", "auto-refresh"]
)
@help_meta(
    category="Diagnosztika és karbantartás",
    usage="Automatikus – nem manuális parancs",
    short="Minden nap 04:00-kor automatikusan frissíti a duty-adatbázist.",
    details=(
        "Ez egy háttérben futó automatikus folyamat, amely minden nap "
        "**pontosan 04:00-kor** lefut. Feladata:\n"
        "• részleges duty-adatbázis frissítés (`run_frissites_core`) futtatása\n"
        "• az admin csatornába státusz üzenetek küldése\n"
        "• a hibák naplózása és visszajelzése\n\n"
        "Ez a funkció **nem indítható manuálisan**, a bot automatikusan kezeli.\n"
        "A parancs csak információt szolgáltat a működéséről."
    ),
    examples=[
        "!auto_refresh_info",
        "!auto_refresh",
    ]
)
async def auto_refresh_info(ctx):
    """Háttérfolyamat súgó-bejegyzése: napi automatikus 04:00 frissítés."""
    await ctx.send(
        "```diff\n"
        "- Ez egy automatikus háttérfolyamat.\n"
        "+ A bot minden nap 04:00-kor frissíti az adatbázist.\n"
        "+ Manuális indítás nem szükséges.\n"
        "```"
    )
# ===========================================================================
# AUTOMATIKUS SÚGÓ PARANCS – !sugo és !sugo <parancs>
# ---------------------------------------------------------------------------

async def send_long(ctx, text: str):
    """Discord 2000 karakter limit kezelése."""
    limit = 2000
    for i in range(0, len(text), limit):
        await ctx.send(text[i:i+limit])


# Új kategóriasorrend – végleges
HELP_CATEGORY_ORDER = [
    "Segédletek",
    "Diagnosztika és karbantartás",
    "Szolgálati riportok",
    "Admin funkciók",
    "Adatkezelés",
]


def _get_cmd_category(cmd) -> str:
    """Parancs kategóriájának kinyerése (decorator alapján, vagy alapértelmezéssel)."""
    return getattr(cmd.callback, "help_category", "Egyéb")


def _get_cmd_short(cmd) -> str:
    """Rövid leírás: decorator short, vagy docstring első sora, vagy a név."""
    short = getattr(cmd.callback, "help_short", None)
    if short:
        return short

    doc = (cmd.callback.__doc__ or "").strip()
    if doc:
        return doc.splitlines()[0].strip()

    return f"{cmd.name} parancs."


def _get_cmd_details(cmd) -> str:
    """Részletes leírás: decorator details, vagy teljes docstring, vagy a rövid leírás."""
    details = getattr(cmd.callback, "help_details", None)
    if details:
        return details

    doc = (cmd.callback.__doc__ or "").strip()
    if doc:
        return doc

    return _get_cmd_short(cmd)


def _get_cmd_usage(cmd) -> str:
    """Használati minta: decorator usage, vagy !<név>."""
    usage = getattr(cmd.callback, "help_usage", None)
    if usage:
        return usage
    return f"!{cmd.name}"


def _get_cmd_examples(cmd) -> List[str]:
    """Példák: decorator examples vagy üres lista."""
    return getattr(cmd.callback, "help_examples", [])


def _iter_visible_commands():
    """
    Csak azokat a parancsokat adja vissza, amelyek:
      - nincsenek elrejtve (hidden=False),
      - nem belső/technikai parancsok,
      - nem ez a sugo parancs.
    """
    SKIP = {"help"}  # más pluginok által regisztrált help parancsok kihagyása

    for cmd in bot.commands:
        if cmd.hidden:
            continue
        if cmd.name in SKIP:
            continue
        yield cmd

@bot.command(name="sugo", aliases=["súgó", "Súgó", "sugó", "Sugó", "SUGO"])
@help_meta(
    category="Segédletek",
    usage="!sugo [parancs]",
    short="Áttekintést ad a bot parancsairól.",
    details=(
        "A bot beépített súgórendszere. Kétféleképpen használható:\n\n"
        "• `!sugo` – az összes parancs rövid listája kategóriákba rendezve\n"
        "• `!sugo <parancs>` – részletes információ az adott parancsról\n\n"
        "A súgó automatikusan a regisztrált parancsok alapján épül fel."
    ),
    examples=[
        "!sugo",
        "!sugo ping",
        "!sugo heti_top",
    ]
)
async def sugo(ctx, parancs_nev: Optional[str] = None):
    """
    Súgó:
      - !sugo                → rövid lista kategóriák szerint
      - !sugo <parancs>      → részletes leírás, argumentumok, példák
    """

    # ------------------------------------------------------------------
    # RÉSZLETES MÓD: !sugo <parancs>
    # ------------------------------------------------------------------
    if parancs_nev:
        keresett = parancs_nev.lstrip("!").lower()
        cmd = bot.get_command(keresett)

        if cmd is None:
            await ctx.send(f"```diff\n- Ismeretlen parancs a súgóban: {parancs_nev}\n```")
            return

        cat = _get_cmd_category(cmd)
        details = _get_cmd_details(cmd)
        usage = _get_cmd_usage(cmd)
        examples = _get_cmd_examples(cmd)

        lines = [
            f"📘 **Súgó – `{cmd.name}`**",
            f"Kategória: **{cat}**",
            "",
            f"Leírás:\n{details}",
            "",
            f"Használat: `{usage}`",
        ]

        if cmd.aliases:
            aliasok = ", ".join(f"`{a}`" for a in cmd.aliases)
            lines.append(f"Aliasok: {aliasok}")

        if examples:
            lines.append("")
            lines.append("Példák:")
            for ex in examples:
                lines.append(f"  • `{ex}`")

        await send_long(ctx, "\n".join(lines))
        return

    # ------------------------------------------------------------------
    # RÖVID LISTA – !sugo
    # ------------------------------------------------------------------
    cats: dict[str, list] = {}
    for cmd in _iter_visible_commands():
        cat = _get_cmd_category(cmd)
        cats.setdefault(cat, []).append(cmd)

    # Rendezés a megadott kategóriasorrend szerint
    ordered_cats: dict[str, list] = {}

    for cat in HELP_CATEGORY_ORDER:
        if cat in cats:
            ordered_cats[cat] = cats.pop(cat)

    # A maradék kategóriák (egyéb) ABC sorrendben
    for cat in sorted(cats.keys()):
        ordered_cats[cat] = cats[cat]

    # Parancsok ABC sorrendben kategórián belül
    for cat, cmd_list in ordered_cats.items():
        ordered_cats[cat] = sorted(cmd_list, key=lambda c: c.name.lower())

    lines = [
        "**📚 EMS Duty Bot – parancsok áttekintése**",
        "_Részletes leírás: `!sugo <parancs>`_",
    ]

    for cat, cmd_list in ordered_cats.items():
        lines.append("")
        lines.append(f"**{cat}**")
        for cmd in cmd_list:
            short = _get_cmd_short(cmd)
            alias_str = ""
            if cmd.aliases:
                alias_str = " _(alias: " + ", ".join(cmd.aliases) + ")_"
            lines.append(f"• `!{cmd.name}`{alias_str} – {short}")
# 🔽 ITT A DOKSILINK – EZT KELL HOZZÁADNI
    lines.append("")
    lines.append("**EMS_Duty – Bot NAS-ról letölthető dokumentáció:**")
    lines.append("[EMS_DUTY_BOT_DOKUMENTACIO.txt](https://gofile.me/7hOpv/ZkVrkYLB1)")
    lines.append("")
    lines.append("**EMS_Duty – Bot dokumentáció Google Drive felületen:**")
    lines.append("[EMS_DUTY_BOT_DOKUMENTACIO.txt](https://drive.google.com/file/d/1bwaXTGLIYBc4rUV92Jvn8TCst19usSbU/view?usp=sharing)")
    await send_long(ctx, "\n".join(lines))

# ---------------------------------------------------------------------------
# PARANCSOK REGISZTRÁLÁSA ÉS NAPLÓZÁS
# ---------------------------------------------------------------------------
print("Regisztrált parancsok:", [c.name for c in bot.commands])
logger.info(f"Regisztrált parancsok: {[c.name for c in bot.commands]}")

# ---------------------------------------------------------------------------
# ASZINKRON KEZDŐ HOOK (discord.py 2.4+)
# ---------------------------------------------------------------------------
@bot.event
async def setup_hook():
    """Háttérfeladatok, pl. automatikus frissítés indítása."""
    asyncio.create_task(auto_refresh_task())
    logger.info("Automatikus frissítés ütemezve (setup_hook).")

# ---------------------------------------------------------------------------
# HIBAKERESŐ ESEMÉNYKEZELŐ
# ---------------------------------------------------------------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("```diff\n- [HIBA] Ismeretlen parancs! Használd a !súgó-t.\n```")
        return
    logger.error(f"Hiba a parancsban: {error}")
    await ctx.send("```diff\n- [HIBA] A parancs végrehajtása során hiba történt.\n```")
@bot.event
async def on_ready():
    logger.info(f"Bejelentkezve mint: {bot.user}")
    duty_log[:] = deduplicate_log()
    save_log()
    for guild in bot.guilds:
        await backfill_duty_messages(guild)
    admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
    if admin_channel:
        reason = ems_read_restart_reason()

        msg_map = {
            "initial":     "✅ EMS bot elindult és készen áll a parancsokra!",
            "file_update": "♻️ EMS bot újraindult (fájl frissítve).",
            "env_update":  "⚙️ EMS bot újraindult (beállítások frissítve).",
            "crash":       "❗ EMS bot újraindult egy váratlan hiba után.",
            "manual":      "🔁 EMS bot manuálisan újraindítva."
        }
        reason_text = msg_map.get(reason, "✅ EMS bot újraindult.")
        welcome_text = f"**{reason_text}**\nHasználd a `!súgó` parancsot a funkciók listájához."

        try:
            # utolsó üzenet törlése, ha ugyanaz (dupla post elkerülése)
            last_message = None
            async for msg in admin_channel.history(limit=1):
                last_message = msg
                break

            if last_message and last_message.author == bot.user and last_message.content.strip() == welcome_text.strip():
                await last_message.delete()

            await admin_channel.send(welcome_text)

        except Exception as e:
            logger.error(f"Üdvözlő üzenet küldési hiba: {e}")
    else:
        logger.error("Admin csatorna nem elérhető — ellenőrizd az ADMIN_CHANNEL_ID-t.")

# ---------------------------------------------------------------------------
# Újraindítás ok beolvasása + resetelése (dupla üzenet ellen)
# ---------------------------------------------------------------------------
def ems_read_restart_reason():
    root = Path(__file__).parent
    reason_file = root / "logs" / "restart_reason.txt"

    if not reason_file.exists():
        return "initial"

    try:
        reason = reason_file.read_text().strip()
    except:
        return "initial"

    # töröljük file-t, hogy ne ismételje üzenetet
    try:
        reason_file.unlink()
    except:
        pass

    return reason or "initial"

# ---------------------------------------------------------------------------
# BOT INDÍTÁS (NAS környezet)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("❌ Hiba: DISCORD_TOKEN nincs beállítva az .env-ben!")

    logger.info("EMS Duty Bot indítása NAS környezetben...")
    bot.run(TOKEN)
# ---------------------------------------------------------------------------