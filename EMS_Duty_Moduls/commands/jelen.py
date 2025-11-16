import os, json, asyncio
from discord.ext import commands
from datetime import datetime, timedelta
import datetime as dtmod
from ..helpers import help_meta, require_admin_channel

class JelenCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers

    @commands.command(
        name="jelen",
        aliases=["Jelen", "JELEN", "Szolgálatban", "szolgálatban", "szolgalatban"],
    )
    @require_admin_channel()
    @help_meta(
        category="Szolgálati riportok",
        usage="!jelen",
        short="Megmutatja, hogy kik vannak jelenleg szolgálatban a legfrissebb adatok alapján.",
    )
    async def jelen(self, ctx):
        DUTY_JSON = "duty_log.json"
        await ctx.send("🔄 Adatbázis frissítése folyamatban a pontos eredmény elérése végett...")

        # For simplicity: read duty_log.json (assumes it's up-to-date)
        if not os.path.exists(DUTY_JSON):
            await ctx.send(f"```diff\n- [HIBA] {DUTY_JSON} fájl nem található.\n```")
            return
        with open(DUTY_JSON, "r", encoding="utf-8") as f:
            entries = json.load(f)

        cutoff = dtmod.datetime.now(dtmod.timezone.utc) - timedelta(days=2)
        recent_entries = []
        for e in entries:
            try:
                ts = dtmod.datetime.strptime(e.get("timestamp"), "%Y-%m-%d %H:%M")
                ts = ts.replace(tzinfo=dtmod.timezone.utc)
                if ts >= cutoff:
                    recent_entries.append(e)
            except Exception:
                continue

        if not recent_entries:
            await ctx.send("```diff\n- Jelenleg senki sincs szolgálatban!\n```")
            return

        state_map = {}
        for e in sorted(recent_entries, key=lambda x: x.get("timestamp", "")):
            key = e.get("person_key") or e.get("name_norm")
            if key:
                state_map[key] = e.get("type")

        active = [e for e in recent_entries if ((e.get("person_key") or e.get("name_norm")) in state_map and state_map[e.get("person_key") or e.get("name_norm")] == "felvette" and e.get("type") == "felvette")]

        if not active:
            await ctx.send("```diff\n- Jelenleg senki sincs szolgálatban!\n```")
            return

        # Remove duplicates by person_key
        seen = {}
        for e in sorted(active, key=lambda x: x.get("timestamp", "")):
            key = e.get("person_key") or e.get("name_norm")
            seen[key] = e
        active = list(seen.values())

        lines = [f"Szolgálatban van {len(active)} fő az elmúlt 48 órát figyelembe véve:"]
        max_name_len = max(len(e.get("name", "")) for e in active)
        max_rank_len = max(len(e.get("position", "").replace("Mentő - ", "").strip()) for e in active)

        for e in active:
            name = e.get("name", "")
            position = e.get("position", "").replace("Mentő - ", "").strip()
            start_time = e.get("start_time", e.get("timestamp", ""))
            lines.append(f"✅ {name.ljust(max_name_len)} | {position.ljust(max_rank_len)} | {start_time}")

        msg = "```\n" + "\n".join(lines) + "\n```"
        await ctx.send(msg)


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(JelenCog(bot, state, helpers))
