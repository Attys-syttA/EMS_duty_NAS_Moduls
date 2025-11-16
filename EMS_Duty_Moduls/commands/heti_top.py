import json, os
import datetime as dtmod
from discord.ext import commands
from ..helpers import help_meta, require_admin_channel
from ..helpers import normalize_person_name

DEDIKALT_RANGOK = [x.strip() for x in os.getenv("DEDIKALT_RANGOK", "").split(",") if x.strip()]
VEZETOSSEG = [x.strip() for x in os.getenv("VEZETOSSEG", "").split(",") if x.strip()]

class HetiTopCog(commands.Cog):
    def __init__(self, bot, state, helpers):
        self.bot = bot
        self.state = state
        self.helpers = helpers
        self.last_weekly_report_text = None
        self.last_weekly_report_author = None
        self.last_weekly_report_timestamp = None
        self.last_weekly_report_offset = 0

    def format_duration(self, minutes: int) -> str:
        h, m = divmod(minutes, 60)
        return f"{h} óra {m} perc"

    def build_weekly_report(self, het_kezdete, het_vege, data):
        ossz_idoperc = {}
        utolso_rang = {}
        for entry in data:
            if "duration" not in entry:
                continue
            try:
                ts = dtmod.datetime.strptime(entry["timestamp"], "%Y-%m-%d %H:%M")
            except Exception:
                continue
            if not (het_kezdete <= ts < het_vege):
                continue
            name = entry.get("name_norm")
            pos = entry.get("position", "")
            dur = int(entry.get("duration", 0))
            if not name:
                continue
            ossz_idoperc[name] = ossz_idoperc.get(name, 0) + dur
            utolso_rang[name] = pos

        rangblokkok = {r: {} for r in DEDIKALT_RANGOK}
        vezetoi_blokk = {}
        for name_norm, perc in ossz_idoperc.items():
            pos = utolso_rang.get(name_norm, "Ismeretlen").replace("Mentő - ", "").strip()
            if any(v.lower() in pos.lower() for v in VEZETOSSEG):
                vezetoi_blokk[name_norm] = (perc, pos)
                continue
            talalat = None
            for r in DEDIKALT_RANGOK:
                if r.lower() in pos.lower():
                    talalat = r
                    break
            if talalat:
                rangblokkok[talalat][name_norm] = perc
            else:
                rangblokkok.setdefault("Ismeretlen", {})[name_norm] = perc

        lines = []
        lines.append(f"📊 **Szolgálati idők**")
        lines.append(f"🗓️ {het_kezdete:%Y-%m-%d} és {het_vege:%Y-%m-%d} között")
        lines.append("──────────────────────────────")

        for rang in DEDIKALT_RANGOK:
            taglista = rangblokkok.get(rang, {})
            if not taglista:
                continue
            lines.extend(["──────────────────────────────", f"🏷️ **@{rang}**", "──────────────────────────────"])
            for name, perc in sorted(taglista.items(), key=lambda x: x[1], reverse=True):
                dcid = None
                mention = f"<@{dcid}>" if dcid else name
                lines.append(f"> {mention} – {self.format_duration(perc)}")
            lines.append("")

        if vezetoi_blokk:
            lines.extend(["──────────────────────────────", "👔 **Vezetőség**", "──────────────────────────────"])
            for name, (perc, pos) in sorted(vezetoi_blokk.items(), key=lambda x: x[1][0], reverse=True):
                dcid = None
                mention = f"<@{dcid}>" if dcid else name
                lines.append(f"> {mention} – {pos} – {self.format_duration(perc)}")
            lines.append("")

        dedikalt_sum = {n: p for r in rangblokkok.values() for n, p in r.items()}
        top3 = sorted(dedikalt_sum.items(), key=lambda x: x[1], reverse=True)[:3]
        if top3:
            lines.extend(["\n🏆 **A hét legaktívabb mentősei:**", "──────────────────────────────"])
            premiumok = ["💰 *$3000 prémium", "💰 *$2000 prémium", "💰 *$1000 prémium"]
            for i, (name, perc) in enumerate(top3):
                mention = name
                h, m = divmod(perc, 60)
                lines.append(f"{['🥇','🥈','🥉'][i]} {mention}\n\u2003**{h} óra {m} perc**\t{premiumok[i]}")

        lines.extend(["──────────────────────────────", "🙏 *Ha valaki eltérést tapasztal, jelezze a vezetőség felé.*", "", "💚 *Köszönjük a szolgálatot, minden mentősünknek!*", "", "──────────────────────────────"])
        return "\n".join(lines)

    @commands.command(name="heti_top", aliases=["Heti Top", "heti top", "HETI_TOP", "Heti_Top"])
    @require_admin_channel()
    @help_meta(
        category="Szolgálati riportok",
        usage="!heti_top [offset]",
        short="Heti toplista előnézetet készít az admin csatornára.",
    )
    async def heti_top(self, ctx, offset: int = 0):
        JSON_FILE = "duty_log.json"
        if not os.path.exists(JSON_FILE):
            await ctx.send(f"```diff\n- [HIBA] A {JSON_FILE} nem található.\n```")
            return
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ma = dtmod.datetime.now()
        napok_vasarnapig = (ma.weekday() + 1) % 7
        het_vege = (ma - dtmod.timedelta(days=napok_vasarnapig)).replace(hour=0, minute=0, second=0, microsecond=0)
        het_kezdete = het_vege - dtmod.timedelta(days=7)
        if offset != 0:
            het_kezdete += dtmod.timedelta(days=7*offset)
            het_vege += dtmod.timedelta(days=7*offset)
        szoveg = self.build_weekly_report(het_kezdete, het_vege, data)
        self.last_weekly_report_text = szoveg
        self.last_weekly_report_author = ctx.author.id
        self.last_weekly_report_timestamp = dtmod.datetime.now()
        self.last_weekly_report_offset = offset
        await ctx.send("```diff\n+ [INFO] Heti toplista előnézet generálva. Használd a !mehet parancsot a közzétételhez.\n```")
        await ctx.send(szoveg)

    @commands.command(name="mehet", aliases=["Mehet", "MEHET"])
    @require_admin_channel()
    @help_meta(category="Szolgálati riportok", usage="!mehet", short="A legutóbb generált heti toplista publikálása.")
    async def mehet(self, ctx):
        if not self.last_weekly_report_text:
            await ctx.send("```diff\n- [HIBA] Nincs elérhető heti toplista. Használd előbb a !heti_top parancsot.\n```")
            return
        now = dtmod.datetime.now()
        if (now - self.last_weekly_report_timestamp).total_seconds() / 3600 > 24:
            await ctx.send("```diff\n- [HIBA] A toplista több mint 24 órája készült, ezért nem publikálható.\n```")
            return
        if self.last_weekly_report_offset != 0:
            await ctx.send("```diff\n- [HIBA] Csak az aktuális heti toplista publikálható.\n```")
            return
        if ctx.author.id != self.last_weekly_report_author:
            await ctx.send("```diff\n- [HIBA] Csak az a személy publikálhatja, aki generálta a toplistát.\n```")
            return
        channel_id = int(os.getenv("WEEKLY_DUTY_CHANNEL_ID", "0"))
        ch = self.bot.get_channel(channel_id)
        if not ch:
            await ctx.send("```diff\n- [HIBA] A heti-munkaidők csatorna nem található.\n```")
            return
        await ch.send(self.last_weekly_report_text)
        await ctx.send("✅ Heti jelentés átmásolva a heti-munkaidők csatornára.")


def setup(bot=None, state=None, helpers=None):
    bot.add_cog(HetiTopCog(bot, state, helpers))
