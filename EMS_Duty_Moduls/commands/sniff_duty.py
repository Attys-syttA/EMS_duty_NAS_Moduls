import os, json
import asyncio
from discord.ext import commands
from ..helpers import help_meta

class SniffDutyCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot

    @commands.command(name="sniff_duty")
    @commands.has_permissions(administrator=True)
    @help_meta(
        category="Diagnosztika és karbantartás",
        usage="!sniff_duty [limit] [show|silent|raw|all]",
        short="A duty-log csatorna üzeneteinek vizsgálata és mentése.",
    )
    async def sniff_duty(self, ctx, limit: int = 5, mode: str = None):
        mode = (mode or "").lower()
        show = mode in ("show", "all")
        raw = mode in ("raw", "all")
        channel = self.bot.get_channel(int(os.getenv("DUTY_LOG_CHANNEL_ID", "0")))
        if not channel:
            await ctx.send("Duty-log csatorna nem található.")
            return

        entries = []
        async for msg in channel.history(limit=limit):
            entries.append({
                "id": msg.id,
                "author": str(msg.author),
                "content": msg.content,
                "embeds": [e.to_dict() for e in msg.embeds],
                "created_at": msg.created_at.isoformat(),
            })
            # small throttle
            await asyncio.sleep(0.05)

        # Save to files
        if raw:
            os.makedirs("exports", exist_ok=True)
            with open("exports/sniff_duty.json", "w", encoding="utf-8") as f:
                json.dump(entries, f, ensure_ascii=False, indent=2)

        if show:
            for e in entries:
                await ctx.send(f"{e['created_at']} | {e['author']} | {e['content']}")

        await ctx.send(f"✅ Sniff kész. {len(entries)} üzenet. (raw={raw})")


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(SniffDutyCog(bot, state, helpers))
