import os, json, asyncio
from discord.ext import commands
from datetime import timedelta
import datetime as dtmod

from ..helpers import help_meta, require_admin_channel
from ..processing import process_duty_message, deduplicate_log, save_log

class FrissitesCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers

    async def run_frissites_core(self, full_mode: bool = False, ctx=None):
        channel = self.bot.get_channel(int(os.getenv("DUTY_LOG_CHANNEL_ID", "0")))
        if not channel:
            if ctx:
                await ctx.send("```diff\n- [HIBA] Duty-log csatorna nem elérhető.\n```")
            return False

        after = None
        if not full_mode:
            after = dtmod.datetime.now(dtmod.timezone.utc) - timedelta(days=40)
            if self.state.duty_log:
                try:
                    latest_ts = max(dtmod.datetime.strptime(l["timestamp"], "%Y-%m-%d %H:%M") for l in self.state.duty_log if "timestamp" in l)
                    after = latest_ts - timedelta(minutes=120)
                except Exception:
                    pass

        new_processed = 0
        processed_loop = 0
        async for msg in channel.history(limit=None, after=after):
            before_len = len(self.state.duty_log)
            process_duty_message(msg)
            if len(self.state.duty_log) > before_len:
                new_processed += 1
            processed_loop += 1
            # Throttle to avoid Discord API rate limits
            if processed_loop % 50 == 0:
                await asyncio.sleep(0.5)
        self.state.duty_log[:] = deduplicate_log(self.state.duty_log)
        save_log()
        if ctx:
            await ctx.send(f"```diff\n+ [OK] Frissítés befejezve. Új: {new_processed} rekord\n```")
        return True

    @commands.command(name="frissites", aliases=["frissítés", "frissités", "Frissítés", "frissites_full", "frissítés_full"])
    @require_admin_channel()
    @help_meta(
        category="Diagnosztika és karbantartás",
        usage="!frissites [teljes|full]",
        short="Duty-log frissítése a Discord duty-log csatornából.",
    )
    async def frissites(self, ctx, mod: str = None):
        full_mode = (mod or "").lower() in ("teljes", "full")
        await ctx.send("```diff\n- [INFO] Adatbázis frissítés indítása...\n```")
        await self.run_frissites_core(full_mode=full_mode, ctx=ctx)


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(FrissitesCog(bot, state, helpers))
