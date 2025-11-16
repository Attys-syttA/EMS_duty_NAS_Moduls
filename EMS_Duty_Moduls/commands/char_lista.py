import os, json
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

CHAR_TO_DISCORD_NAME_FILE = "char_to_discord_name.json"

class CharListCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="char_lista", aliases=["charlist", "karakter_lista", "lista_char"])
    @require_admin_channel()
    @help_meta(
        category="Adatkezelés",
        usage="!char_lista",
        short="Listázza a FiveM ↔ Discord névpárosításokat.",
    )
    async def char_lista(self, ctx):
        if not os.path.exists(CHAR_TO_DISCORD_NAME_FILE):
            await ctx.send("```diff\n- A char_to_discord_name.json fájl még nem létezik.\n```")
            return
        try:
            with open(CHAR_TO_DISCORD_NAME_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception as e:
            await ctx.send(f"```diff\n- Hiba a fájl beolvasásakor: {e}\n```")
            return

        if not mapping:
            await ctx.send("```diff\n- A fájl üres, még nincsenek párosítások.\n```")
            return

        lines = [f"+ {char} → {discord}" for char, discord in sorted(mapping.items())]
        output = "\n".join(lines)
        chunks = [output[i:i+1800] for i in range(0, len(output), 1800)]
        for idx, part in enumerate(chunks, start=1):
            header = (
                f"```diff\n# FiveM ↔ Discord párosítások ({idx}/{len(chunks)})\n{part}\n```"
            )
            await ctx.send(header)


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(CharListCog(bot))
