from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

class ChannelInfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="channel_info", aliases=["chaninfo", "csatorna"])
    @require_admin_channel()
    @help_meta(
        category="Diagnosztika és karbantartás",
        usage="!channel_info <channel_id>",
        short="Kiírja egy Discord csatorna típusát és főbb jellemzőit.",
    )
    async def channel_info(self, ctx, channel_id: int = None):
        if channel_id is None:
            await ctx.send("Használat: `!chaninfo <channel_id>`  (pl.: !chaninfo 1349829361649324173)")
            return
        ch = self.bot.get_channel(channel_id)
        if not ch:
            await ctx.send(f"❌ Nem találom a csatornát ID alapján: `{channel_id}`")
            return
        msg = []
        msg.append(f"📎 **Channel**: {ch.name}")
        msg.append(f"🆔 ID: `{ch.id}`")
        msg.append(f"🏷️ Típus: `{type(ch)}`")
        if hasattr(ch, 'threads'):
            msg.append(f"🧵 Threads: `{len(ch.threads)}`")
        if hasattr(ch, 'category') and ch.category:
            msg.append(f"📂 Kategória: {ch.category.name}")
        await ctx.send("\n".join(msg))


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(ChannelInfoCog(bot))
