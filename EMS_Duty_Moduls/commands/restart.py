import os
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

class RestartCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers

    @commands.command(name="restart", aliases=["RESTART", "Restart", "ujraindit", "újraindít", "Újraindít"]) 
    @require_admin_channel()
    @help_meta(
        category="Diagnosztika és karbantartás",
        usage="!restart",
        short="Manuális bot-újraindítás a NAS watchdog rendszerével.",
    )
    async def restart(self, ctx):
        try:
            await ctx.send("```diff\n- [INFO] EMS bot újraindítása folyamatban...\n```")
            reason_file = self.state.ROOT / 'logs' / 'restart_reason.txt'
            reason_file.write_text('manual')
            os._exit(41)
        except Exception as e:
            await ctx.send(f"```diff\n- [HIBA] Nem sikerült az újraindítás: {e}\n```")


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(RestartCog(bot, state, helpers))
