import random
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

class PingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_ping = None

    @commands.command(name="ping", aliases=["Ping", "PING"])
    @require_admin_channel()
    @help_meta(
        category="Segédletek",
        usage="!ping",
        short="Ellenőrzi, hogy él-e és válaszol-e a bot.",
        details="Egyszerű elérhetőségi teszt; spam-védelem véletlenszerű válasszal.",
        examples=["!ping"],
    )
    async def ping(self, ctx):
        now = ctx.message.created_at
        if self._last_ping and (now - self._last_ping).total_seconds() < 25:
            msg = random.choice([
                ":ping_pong: pong – szerva itt!",
                ":ping_pong: pong – meccslabda!",
                ":ping_pong: pong – csúszott volt!",
                ":ping_pong: pong – megetted a nyesést!",
            ])
            await ctx.send(msg)
        else:
            latency_ms = round(self.bot.latency * 1000)
            await ctx.send(f"✅ A bot fut! (késleltetés: {latency_ms} ms)")
        self._last_ping = now

def setup(bot=None, state=None, helpers=None):
    bot.add_cog(PingCog(bot))
