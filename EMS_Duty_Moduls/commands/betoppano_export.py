import os, json
import pytz
import asyncio
import datetime as dtmod
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

class BetoppanoExportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="betoppano_export", aliases=["betoppano export", "betoppano"])
    @require_admin_channel()
    @help_meta(
        category="Admin funkciók",
        usage="!betoppano_export [YYYY-MM-DD] [YYYY-MM-DD]",
        short="A #betoppanó csatorna üzeneteinek exportálása.",
    )
    async def betoppano_export(self, ctx, *args):
        channel_id = 1280885410960113768  # betoppanó default
        ch = self.bot.get_channel(channel_id)
        if not ch:
            await ctx.send(f"```diff\n- [HIBA] Betoppanó csatorna nem található (ID: {channel_id}).\n```")
            return

        def parse_ymd(s):
            try:
                return dtmod.datetime.strptime(s, "%Y-%m-%d")
            except Exception:
                return None

        args_norm = [a.strip() for a in args if a.strip()]
        after_dt_utc = None
        before_dt_utc = None
        if len(args_norm) == 0:
            export_file = "exports/betoppano_full.json"
            mode_text = "teljes export"
        elif len(args_norm) == 1:
            d1 = parse_ymd(args_norm[0])
            if not d1:
                await ctx.send(f"```diff\n- [HIBA] Hibás dátum: {args_norm[0]}\n```")
                return
            after_dt_utc = d1.astimezone(pytz.utc)
            before_dt_utc = (d1 + dtmod.timedelta(days=1)).astimezone(pytz.utc)
            export_file = f"exports/betoppano_{d1.strftime('%Y_%m_%d')}.json"
            mode_text = f"napi export: {d1.strftime('%Y-%m-%d')}"
        elif len(args_norm) == 2:
            d1 = parse_ymd(args_norm[0])
            d2 = parse_ymd(args_norm[1])
            if not d1 or not d2:
                await ctx.send("```diff\n- [HIBA] Hibás dátumtartomány (ÉÉÉÉ-HH-NN ...).\n```")
                return
            if d2 < d1:
                d1, d2 = d2, d1
            after_dt_utc = d1.astimezone(pytz.utc)
            before_dt_utc = (d2 + dtmod.timedelta(days=1)).astimezone(pytz.utc)
            export_file = f"exports/betoppano_{d1.strftime('%Y_%m_%d')}_{d2.strftime('%Y_%m_%d')}.json"
            mode_text = f"intervallum: {d1:%Y-%m-%d} → {d2:%Y-%m-%d}"
        else:
            await ctx.send("```diff\n- [HIBA] Használat: !betoppano_export [YYYY-MM-DD] [YYYY-MM-DD]\n```")
            return

        os.makedirs("exports", exist_ok=True)
        await ctx.send(f"```diff\n- [INFO] Üzenetek letöltése a #{ch.name} csatornáról… ({mode_text})```")

        entries = []
        history_kwargs = {"limit": None, "oldest_first": True}
        if after_dt_utc:
            history_kwargs["after"] = after_dt_utc
        if before_dt_utc:
            history_kwargs["before"] = before_dt_utc

        async for msg in ch.history(**history_kwargs):
            entries.append({
                "id": msg.id,
                "author": str(msg.author),
                "author_id": getattr(msg.author, "id", None),
                "author_display": getattr(msg.author, "display_name", None),
                "content": msg.content,
                "created_at": msg.created_at.astimezone(pytz.timezone("Europe/Budapest")).strftime("%Y-%m-%d %H:%M:%S"),
                "mentions": [m.id for m in msg.mentions],
            })
            # small sleep to avoid hitting rate limits for long histories
            if len(entries) % 50 == 0:
                await asyncio.sleep(0.2)

        with open(export_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

        await ctx.send(f"```diff\n+ [OK] {len(entries)} üzenet mentve → {export_file}```")


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(BetoppanoExportCog(bot))
