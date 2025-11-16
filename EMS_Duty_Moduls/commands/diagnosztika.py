import os, json
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

class DiagnosztikaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="diagnosztika", aliases=["diag"])
    @require_admin_channel()
    @help_meta(
        category="Diagnosztika és karbantartás",
        usage="!diagnosztika",
        short="A bot adatfájljainak konzisztencia-ellenőrzése.",
    )
    async def diagnosztika(self, ctx):
        files = {
            "betoppano_log.json": None,
            "discord_user_ids.json": None,
            "char_to_discord_name.json": None,
        }
        for fname in files:
            if not os.path.exists(fname):
                files[fname] = "❌ Nem található"
                continue
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        files[fname] = f"✅ {len(data)} elem"
                    elif isinstance(data, dict):
                        files[fname] = f"✅ {len(data)} kulcs"
                    else:
                        files[fname] = f"⚠️ Ismeretlen formátum"
            except Exception as e:
                files[fname] = f"❌ Hiba beolvasáskor: {e}"

        # Count pairs
        found_pairs = 0
        missing_in_ids = 0
        if os.path.exists("char_to_discord_name.json") and os.path.exists("discord_user_ids.json"):
            try:
                with open("char_to_discord_name.json", "r", encoding="utf-8") as f:
                    char_map = json.load(f)
                with open("discord_user_ids.json", "r", encoding="utf-8") as f:
                    id_map = json.load(f)
                for char_name, discord_name in char_map.items():
                    if discord_name.lower().strip() in id_map:
                        found_pairs += 1
                    else:
                        missing_in_ids += 1
            except Exception:
                pass

        summary = (
            "```diff\n"
            f"+ betoppano_log.json: {files['betoppano_log.json']}\n"
            f"+ discord_user_ids.json: {files['discord_user_ids.json']}\n"
            f"+ char_to_discord_name.json: {files['char_to_discord_name.json']}\n"
            "-------------------------------------\n"
            f"+ Összerendelések OK: {found_pairs}\n"
            f"- Hiányzó Discord-név az ID-térképből: {missing_in_ids}\n"
            "```"
        )
        await ctx.send(summary)


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(DiagnosztikaCog(bot))
