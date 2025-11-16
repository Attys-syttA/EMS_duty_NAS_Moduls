import json
import datetime as dtmod
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

class SzemelyCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers

    @commands.command(name="szemely", aliases=["személy", "Személy"])
    @require_admin_channel()
    @help_meta(
        category="Szolgálati riportok",
        usage="!szemely <Név>",
        short="Kilistázza egy adott személy összes rögzített szolgálati időpontját.",
    )
    async def szemely(self, ctx, *, nev: str):
        target = self.helpers.normalize_person_name(nev)
        matches = [r for r in self.state.duty_log if r.get("name_norm") == target]
        if not matches:
            await ctx.send(f"```diff\n- [INFO] Nincs adat {nev} nevű személyről.\n```")
            return
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
        intro = f"🧾 Egy pillanat, összegzem {nev} beosztásait..."
        await ctx.send(intro + "\n```diff\n- [INFO] Feldolgozás indítása...\n```")
        await ctx.send("\n".join(lines))
        await ctx.send("```diff\n+ [OK] Lekérés befejezve. Adatok megjelenítve.\n```")


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(SzemelyCog(bot, state, helpers))
