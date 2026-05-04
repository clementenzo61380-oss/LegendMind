"""Recap hebdomadaire des attaques faibles — envoyé chaque lundi matin.

Pour chaque joueur Legend I ayant reçu au moins un DM ATTACK_LOW_GAIN
dans la semaine écoulée, ce service :

1. Agrège les feedbacks de `attack_feedback` (timing / funnel / execution…).
2. Reconstitue les jours problématiques depuis `player_snapshots` (jours où
   le gain moyen était < ATTACK_WEAK_GAIN_THRESHOLD).
3. Construit un embed Discord avec :
   - Distribution des erreurs (camembert textuel)
   - Jours problématiques de la semaine
   - Conseil prioritaire basé sur la catégorie la plus fréquente
   - Tendance d'amélioration (semaine N vs N−1)
4. Envoie le DM et enregistre dans `alert_history` pour la déduplication.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, time, timedelta, timezone

import discord

from constants import (
    ATTACK_RECAP_ALERT_KEY,
    ATTACK_WEAK_GAIN_THRESHOLD,
    COLOR_INFO,
    COLOR_WARNING,
    LeagueType,
)
from services.db import Repository

log = logging.getLogger(__name__)

_WEEKDAY_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

_FEEDBACK_LABELS: dict[str, str] = {
    "timing":    "⏱️ Fail timing",
    "funnel":    "🔀 Funnel raté",
    "execution": "💥 Erreur d'exéc.",
    "other":     "❓ Autre",
    "false_pos": "✅ Faux positif",
}

_PRIORITY_TIPS: dict[str, str] = {
    "timing": (
        "**Focus semaine : Timing**\n"
        "Avant chaque attaque, attends que :\n"
        "• Le CC soit entièrement sorti et éliminé.\n"
        "• La Queen walk ait sécurisé au moins 1 compartiment.\n"
        "• Tous tes héros soient disponibles.\n"
        "👉 Regarde 1–2 replays de tes attaques timing cette semaine."
    ),
    "funnel": (
        "**Focus semaine : Funnel**\n"
        "Le funnel est la base de toute attaque 3 étoiles :\n"
        "• 2 troupes de funnel (giants/super-barbs) sur chaque flanc d'entrée.\n"
        "• Ton armée principale doit rentrer **au centre**, pas sur les bords.\n"
        "• Regarde où tes troupes partent en debut d'attaque — si elles longent\n"
        "  les bords, le funnel était raté.\n"
        "👉 Entraîne-toi sur des bases villages amis cette semaine."
    ),
    "execution": (
        "**Focus semaine : Exécution**\n"
        "L'exécution se prépare AVANT d'appuyer 'Attaquer' :\n"
        "• Identifie où tu placeras chaque sort **avant** de lancer.\n"
        "• Compte les cases : une rage couvre 5×5, un saut 4 cases.\n"
        "• Ne pose jamais un sort 'à l'instinct' — toujours une cible précise.\n"
        "👉 Utilise le mode spectateur pour planifier 1 attaque à l'avance."
    ),
    "other": (
        "**Focus semaine : Analyse**\n"
        "Plusieurs causes différentes cette semaine. Regarde tes 3 pires\n"
        "attaques en replay et identifie le moment exact où ça a failli.\n"
        "👉 Note le pattern — il sera presque toujours le même."
    ),
    "false_pos": (
        "**Bonne semaine !**\n"
        "Tes attaques faibles étaient en réalité justifiées (bases défensives).\n"
        "Continue sur cette lancée."
    ),
}


class WeeklyAttackRecapService:
    """Calcule et envoie le recap d'attaque du lundi matin."""

    def __init__(self, bot: discord.Client, repository: Repository) -> None:
        self._bot = bot
        self._repo = repository

    async def run(self) -> int:
        """Envoie le recap à tous les joueurs éligibles.

        Returns le nombre de DMs envoyés avec succès.
        """
        now = datetime.now(timezone.utc)
        # Fenêtre : lun 00h00 → dim 23h59 de la semaine passée.
        this_monday = _last_monday(now)
        last_monday = this_monday - timedelta(days=7)
        sent = 0

        # Tous les joueurs Legend I actifs avec alertes activées.
        candidates = await self._repo.list_active_legend_players_in_tier(
            LeagueType.LEGEND_I,
        )
        for tag, discord_user_id, name, _tier in candidates:
            prefs = await self._repo.get_preferences(discord_user_id)
            if not prefs.enable_alerts or not prefs.alert_on_defense:
                continue
            if await self._repo.has_attack_recap_been_sent_this_week(
                tag, this_monday
            ):
                continue

            feedbacks = await self._repo.get_attack_feedback_since(tag, last_monday)
            snaps_raw = await self._repo.get_snapshots_since(tag, last_monday)
            snapshots: list[object] = list(snaps_raw)

            # Besoin d'au moins un feedback OU un jour problématique.
            weak_days = _find_weak_days(snapshots)
            if not feedbacks and not weak_days:
                continue

            embed = _build_recap_embed(
                name=name or tag,
                tag=tag,
                feedbacks=feedbacks,
                weak_days=weak_days,
                week_start=last_monday,
                week_end=this_monday - timedelta(seconds=1),
            )
            if await self._send(discord_user_id, embed):
                await self._repo.record_alert(
                    tag, ATTACK_RECAP_ALERT_KEY, discord_user_id,
                    f"recap_lundi_{this_monday.date().isoformat()}",
                )
                sent += 1
                # Throttle : 0.25 s entre chaque DM.
                import asyncio

                await asyncio.sleep(0.25)

        return sent

    async def _send(self, discord_user_id: int, embed: discord.Embed) -> bool:
        user: discord.User | discord.Member | None = self._bot.get_user(
            discord_user_id
        )
        if user is None:
            try:
                user = await self._bot.fetch_user(discord_user_id)
            except (discord.NotFound, discord.HTTPException):
                return False
        try:
            await user.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _last_monday(now: datetime) -> datetime:
    """Dernier lundi 00:00 UTC (= début de la semaine en cours)."""
    days_since_monday = now.weekday()  # 0 = Monday
    return datetime.combine(
        (now - timedelta(days=days_since_monday)).date(),
        time(0),
        tzinfo=timezone.utc,
    )


def _find_weak_days(snapshots: "list[object]") -> list[tuple[str, float]]:
    """Retourne [(label_jour, avg_gain), ...] pour les jours < seuil."""
    from constants import ATTACK_WEAK_GAIN_THRESHOLD

    # Group snapshots by UTC day, keep highest attacks_done and trophies_gained
    by_day: dict[str, dict[str, int]] = {}
    for _s in snapshots:
        from models import LegendSnapshot as _LS
        if not isinstance(_s, _LS):
            continue
        key = _s.captured_at.strftime("%Y-%m-%d")
        if key not in by_day:
            by_day[key] = {
                "max_attacks": 0,
                "max_gained": 0,
                "weekday": _s.captured_at.weekday(),
            }
        by_day[key]["max_attacks"] = max(by_day[key]["max_attacks"], _s.attacks_done)
        by_day[key]["max_gained"] = max(by_day[key]["max_gained"], _s.trophies_gained)

    # Sort by date, compute daily deltas
    sorted_days = sorted(by_day.items())
    weak: list[tuple[str, float]] = []
    prev_attacks = prev_gained = 0
    for date_str, data in sorted_days:
        delta_attacks = max(0, data["max_attacks"] - prev_attacks)
        delta_gained = max(0, data["max_gained"] - prev_gained)
        # Guard: if attacks reset (new day) but attacks_done went from high to low,
        # that means a new CoC day — delta_attacks may be full daily count.
        if delta_attacks > 0:
            avg = delta_gained / delta_attacks
            if avg < ATTACK_WEAK_GAIN_THRESHOLD:
                wd = _WEEKDAY_FR[data["weekday"]]
                weak.append((f"{wd} {date_str[8:10]}/{date_str[5:7]}", avg))
        prev_attacks = data["max_attacks"]
        prev_gained = data["max_gained"]
    return weak


def _build_recap_embed(
    *,
    name: str,
    tag: str,
    feedbacks: list[dict[str, object]],
    weak_days: list[tuple[str, float]],
    week_start: datetime,
    week_end: datetime,
) -> discord.Embed:
    total_fb = len(feedbacks)
    has_fb = total_fb > 0

    color = COLOR_WARNING if (weak_days or has_fb) else COLOR_INFO

    embed = discord.Embed(
        title="📊 Recap attaques — semaine passée",
        description=(
            f"**{name}** (`{tag}`)  ·  "
            f"Semaine du {week_start.strftime('%d/%m')} au {week_end.strftime('%d/%m/%Y')}"
        ),
        color=color,
    )

    # ── Jours problématiques ──────────────────────────────────────────────
    if weak_days:
        lines = "\n".join(
            f"• **{label}** — gain moy. **{avg:.0f} tr./attaque**"
            for label, avg in weak_days
        )
        embed.add_field(
            name=f"📅 Jours sous le seuil ({ATTACK_WEAK_GAIN_THRESHOLD} tr.)",
            value=lines,
            inline=False,
        )
    else:
        embed.add_field(
            name="📅 Jours problématiques",
            value="✅ Aucun — toutes les journées étaient au-dessus du seuil.",
            inline=False,
        )

    # ── Distribution des feedbacks ────────────────────────────────────────
    if has_fb:
        counts = Counter(str(f["feedback"]) for f in feedbacks)
        total = sum(counts.values())
        fb_lines: list[str] = []
        for fb_key in ["timing", "funnel", "execution", "other", "false_pos"]:
            n = counts.get(fb_key, 0)
            if n == 0:
                continue
            pct = n / total
            bar_len = max(1, round(pct * 10))
            bar = "█" * bar_len + "░" * (10 - bar_len)
            label = _FEEDBACK_LABELS.get(fb_key, fb_key)
            fb_lines.append(f"`{bar}` {label} — **{n}** ({pct:.0%})")
        embed.add_field(
            name=f"🗳️ Tes feedbacks ({total_fb} attaques notées)",
            value="\n".join(fb_lines),
            inline=False,
        )

        # Priority tip: most frequent non-false_pos category
        real_errors = {k: v for k, v in counts.items() if k != "false_pos"}
        if real_errors:
            top_error = max(real_errors, key=lambda k: real_errors[k])
            tip = _PRIORITY_TIPS.get(top_error, _PRIORITY_TIPS["other"])
            embed.add_field(name="🎯 Conseil prioritaire de la semaine", value=tip, inline=False)
    else:
        embed.add_field(
            name="🗳️ Feedbacks",
            value=(
                "Aucun feedback enregistré cette semaine.\n"
                "Active **`/ping`** et clique les boutons après chaque DM "
                "d'attaque faible pour obtenir des conseils personnalisés."
            ),
            inline=False,
        )

    # ── Sparkline des gains par jour ──────────────────────────────────────
    if weak_days:
        gains = [avg for _, avg in weak_days]
        blocks = "▁▂▃▄▅▆▇█"
        lo, hi = 0, max(ATTACK_WEAK_GAIN_THRESHOLD, max(gains, default=1))
        sparkline = "".join(
            blocks[min(len(blocks) - 1, int(g / hi * (len(blocks) - 1)))]
            for _, g in weak_days
        )
        embed.add_field(
            name="📈 Tendance gains (jours faibles)",
            value=f"`{sparkline}`  (bas=faible, haut=proche du seuil)",
            inline=False,
        )

    embed.set_footer(
        text=(
            "Recap généré chaque lundi matin · "
            "Détail via /carnet · "
            "Désactive avec /ping actif:False"
        )
    )
    return embed
