import os
import json
from datetime import datetime
import datetime as dtmod
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel
from ..processing import get_time_for_period

class SzolgalatCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers

    @commands.command(name="szolgalat", aliases=["szolgálat", "Szolgálat"])
    @require_admin_channel()
    @help_meta(
        category="Szolgálati riportok",
        usage="!szolgalat <kezdet_dátum> <kezdet_idő> <vég_dátum> <vég_idő>",
        short="Összegzi egy tetszőleges időszak szolgálati idejét személyenként.",
    )
    async def szolgalat(self, ctx, kezdet: str, kezdet_ido: str, veg: str, veg_ido: str):
        try:
            start_str = f"{kezdet} {kezdet_ido}"
            end_str = f"{veg} {veg_ido}"
            start_date = dtmod.datetime.strptime(start_str, "%Y-%m-%d %H:%M")
            end_date = dtmod.datetime.strptime(end_str, "%Y-%m-%d %H:%M")
        except ValueError:
            await ctx.send("Hibás dátumformátum! Használat: `!szolgalat YYYY-MM-DD HH:MM YYYY-MM-DD HH:MM`")
            return

        results = get_time_for_period(start_date, end_date)
        if not results:
            await ctx.send("Nincs adat az adott időszakra.")
            return
        text = "\n".join(results)
        if len(text) > 2000:
            for i in range(0, len(text), 2000):
                await ctx.send(text[i:i+2000])
        else:
            await ctx.send(f"**Szolgálati idők {start_str} és {end_str} között:**\n{text}")

        await ctx.send("📦 Mindenki a helyén, indulhat a műszak!\n```diff\n+ [OK] Jelentés elkészült. Minden adat naprakész.\n```")


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(SzolgalatCog(bot, state, helpers))
