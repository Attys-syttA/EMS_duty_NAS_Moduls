import os, json
import asyncio
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

class TesztJelenCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers

    @commands.command(name="teszt_jelen", aliases=["teszt jelen", "Teszt jelen", "TESZT_JELEN"]) 
    @require_admin_channel()
    @help_meta(category="Admin funkciók", usage="!teszt_jelen", short="A !jelen parancs működésének bemutatása tesztadatokkal.")
    async def teszt_jelen(self, ctx):
        TEST_MODE = int(os.getenv("TEST_MODE", "0"))
        if TEST_MODE != 1:
            await ctx.send("⚠️ Teszt mód ki van kapcsolva (`TEST_MODE=0`).")
            return

        TEST_FILE = os.getenv("TEST_MODE_FILE", "hamis_duty_log.json")
        LIMIT = int(os.getenv("TEST_MODE_RECORD_LIMIT", "10"))

        if not os.path.exists(TEST_FILE):
            await ctx.send(f"```diff\n- [TESZT HIBA] Teszt fájl nem található: {TEST_FILE}\n```")
            return

        try:
            with open(TEST_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception as e:
            await ctx.send(f"```diff\n- [TESZT HIBA] JSON olvasási hiba: {e}\n```")
            return

        entries = entries[-LIMIT:]

        VEZETOSSEG = [x.strip() for x in os.getenv("VEZETOSSEG", "").split(",") if x.strip()]
        DEDIKALT_RANGOK = [x.strip() for x in os.getenv("DEDIKALT_RANGOK", "").split(",") if x.strip()]

        state = {}
        for e in entries:
            key = e.get("person_key") or e.get("name_norm")
            if key:
                state[key] = e

        active = [v for v in state.values() if v.get("type") == "felvette"]

        if not active:
            await ctx.send(f"🧪 ```diff\n- TESZT: senki sincs szolgálatban (utolsó {LIMIT} esemény alapján)\n```")
            return

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

        await ctx.send("🔧 Teszt adatbázis-frissítés folyamatban…")
        await asyncio.sleep(1)
        await ctx.send(f"✅ Teszt frissítés kész ({len(entries)} teszt esemény feldolgozva).")

        lines = [f"🧪 TESZT – Szolgálatban van {len(active_sorted)} fő (utolsó {LIMIT} esemény alapján):"]
        for e in active_sorted:
            name = e.get("name", "")
            pos = e.get("position", "").replace("Mentő - ", "").strip()
            ts = e.get("start_time", e.get("timestamp", ""))
            lines.append(f"✅ {name:<22} | {pos:<19} | {ts}")

        msg = "```\n" + "\n".join(lines) + "\n```"
        await ctx.send(msg)


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(TesztJelenCog(bot, state, helpers))
