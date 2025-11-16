import asyncio
from discord.ext import commands
from typing import Optional
from ..helpers import help_meta

HELP_CATEGORY_ORDER = [
    "Segédletek",
    "Diagnosztika és karbantartás",
    "Szolgálati riportok",
    "Admin funkciók",
    "Adatkezelés",
]


def _get_cmd_category(cmd) -> str:
    return getattr(cmd.callback, "help_category", "Egyéb")


def _get_cmd_short(cmd) -> str:
    short = getattr(cmd.callback, "help_short", None)
    if short:
        return short
    doc = (cmd.callback.__doc__ or "").strip()
    if doc:
        return doc.splitlines()[0].strip()
    return f"{cmd.name} parancs."


def _get_cmd_details(cmd) -> str:
    details = getattr(cmd.callback, "help_details", None)
    if details:
        return details
    doc = (cmd.callback.__doc__ or "").strip()
    if doc:
        return doc
    return _get_cmd_short(cmd)


def _get_cmd_usage(cmd) -> str:
    usage = getattr(cmd.callback, "help_usage", None)
    if usage:
        return usage
    return f"!{cmd.name}"


def _get_cmd_examples(cmd) -> list:
    return getattr(cmd.callback, "help_examples", [])


class SugoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="sugo", aliases=["súgó", "Súgó", "sugó", "Sugó", "SUGO"])
    @help_meta(
        category="Segédletek",
        usage="!sugo [parancs]",
        short="Áttekintést ad a bot parancsairól.",
    )
    async def sugo(self, ctx, parancs_nev: Optional[str] = None):
        if parancs_nev:
            keresett = parancs_nev.lstrip("!").lower()
            cmd = self.bot.get_command(keresett)
            if cmd is None:
                await ctx.send(f"```diff\n- Ismeretlen parancs a súgóban: {parancs_nev}\n```")
                return
            cat = _get_cmd_category(cmd)
            details = _get_cmd_details(cmd)
            usage = _get_cmd_usage(cmd)
            examples = _get_cmd_examples(cmd)
            lines = [
                f"📘 **Súgó – `{cmd.name}`**",
                f"Kategória: **{cat}**",
                "",
                f"Leírás:\n{details}",
                "",
                f"Használat: `{usage}`",
            ]
            if cmd.aliases:
                aliasok = ", ".join(f"`{a}`" for a in cmd.aliases)
                lines.append(f"Aliasok: {aliasok}")
            if examples:
                lines.append("")
                lines.append("Példák:")
                for ex in examples:
                    lines.append(f"  • `{ex}`")
            await ctx.send("\n".join(lines))
            return

        # short listing
        cats = {}
        for cmd in self.bot.commands:
            if cmd.hidden:
                continue
            if cmd.name == "help":
                continue
            cat = _get_cmd_category(cmd)
            cats.setdefault(cat, []).append(cmd)

        ordered_cats = {}
        for cat in HELP_CATEGORY_ORDER:
            if cat in cats:
                ordered_cats[cat] = cats.pop(cat)
        for cat in sorted(cats.keys()):
            ordered_cats[cat] = cats[cat]
        for cat, cmd_list in ordered_cats.items():
            ordered_cats[cat] = sorted(cmd_list, key=lambda c: c.name.lower())

        lines = [
            "**📚 EMS Duty Bot – parancsok áttekintése**",
            "_Részletes leírás: `!sugo <parancs>`_",
        ]
        for cat, cmd_list in ordered_cats.items():
            lines.append("")
            lines.append(f"**{cat}**")
            for cmd in cmd_list:
                short = _get_cmd_short(cmd)
                alias_str = ""
                if cmd.aliases:
                    alias_str = " _(alias: " + ", ".join(cmd.aliases) + ")_"
                lines.append(f"• `!{cmd.name}`{alias_str} – {short}")
        await ctx.send("\n".join(lines))


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(SugoCog(bot))
