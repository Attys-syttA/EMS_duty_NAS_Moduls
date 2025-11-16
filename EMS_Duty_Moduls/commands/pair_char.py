import os, json, re
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel

CHAR_TO_DISCORD_NAME_FILE = "char_to_discord_name.json"

class PairCharCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="pair_char", aliases=["pair", "charpair", "karakter_osszekotes"])
    @require_admin_channel()
    @help_meta(
        category="Adatkezelés",
        usage='!pair_char "FiveM név" "Discord név"',
        short="Összekapcsol egy FiveM karakternevet egy Discord névvel.",
    )
    async def pair_char(self, ctx, fivem_nev: str = None, discord_nev: str = None):
        if not fivem_nev or not discord_nev:
            await ctx.send("```diff\n- Használat: !pair_char \"FiveM név\" \"Discord név\"\n```")
            return

        def _norm(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip().lower())

        fivem_norm = _norm(fivem_nev)
        discord_norm = _norm(discord_nev)

        if os.path.exists(CHAR_TO_DISCORD_NAME_FILE):
            with open(CHAR_TO_DISCORD_NAME_FILE, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        else:
            mapping = {}

        previous = mapping.get(fivem_norm)
        mapping[fivem_norm] = discord_norm

        with open(CHAR_TO_DISCORD_NAME_FILE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

        if previous is None:
            msg = f"+ Hozzáadva: {fivem_norm} → {discord_norm}"
        elif previous == discord_norm:
            msg = f"= Már létezik: {fivem_norm} → {discord_norm}"
        else:
            msg = f"~ Frissítve: {fivem_norm} → {discord_norm} (régi: {previous})"

        await ctx.send(f"```diff\n{msg}\n```")


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(PairCharCog(bot))
