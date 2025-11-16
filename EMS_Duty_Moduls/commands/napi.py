import os
import json
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel
import datetime as dtmod

class NapiCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers

    @commands.command(name="napi", aliases=["Napi"])
    @require_admin_channel()
    @help_meta(category="Szolgálati riportok", usage="!napi <YYYY-MM-DD>", short="Megmutatja, hogy egy adott napon kik dolgoztak és mennyi szolgálati időt teljesítettek.")
    async def napi(self, ctx, datum: str):
        try:
            day_start = dtmod.datetime.strptime(datum, "%Y-%m-%d")
            day_end = day_start + dtmod.timedelta(days=1)
        except ValueError:
            await ctx.send("Hibás dátumformátum! Használat: `!napi YYYY-MM-DD`")
            return

        entries = []
        for r in self.state.duty_log:
            try:
                et = dtmod.datetime.strptime(r["end_time"], "%Y-%m-%d %H:%M")
            except Exception:
                continue
            if day_start <= et < day_end:
                dur = int(r.get("duration", 0))
                h, m = divmod(dur, 60)
                entries.append(f"{r.get('name','Ismeretlen')} {r.get('position','')}: {h} óra {m} perc.")

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


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(NapiCog(bot, state, helpers))
