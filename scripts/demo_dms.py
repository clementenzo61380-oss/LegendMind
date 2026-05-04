#!/usr/bin/env python3
"""LegendMind V3 — Aperçu visuel des DMs Discord.

Affiche dans le terminal une simulation des 3 types de DMs :
  1. Défense subie (DEFENSE_TAKEN)
  2. Attaque faible détectée (ATTACK_LOW_GAIN) — nouvelle fonctionnalité
  3. Recap hebdomadaire Legend II/III (WEEKLY_RECAP)

Aucune connexion Discord, DB ou API requise.
"""
from __future__ import annotations

# ruff: noqa: E402
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(width=90)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers — simuler l'apparence d'un embed Discord dans le terminal
# ─────────────────────────────────────────────────────────────────────────────
COLOR_WARNING = 0xF39C12
COLOR_INFO = 0x3498DB
COLOR_SUCCESS = 0x2ECC71

def _hex_to_rgb(color: int) -> tuple[int, int, int]:
    return (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF


def _rich_color(hex_color: int) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgb({r},{g},{b})"


def _bar(hex_color: int, width: int = 2) -> str:
    c = _rich_color(hex_color)
    return f"[{c}]{'█' * width}[/{c}]"


def discord_embed(
    *,
    title: str,
    description: str,
    fields: list[tuple[str, str, bool]] | None = None,
    footer: str = "",
    color: int = COLOR_INFO,
    author: str = "LegendMind#2398",
    thumbnail: str = "🏆",
) -> Panel:
    """Render a Discord embed as a Rich Panel."""
    c = _rich_color(color)
    body_lines: list[str] = []

    # Author
    body_lines.append(f"[dim]🤖 {author}[/dim]\n")

    # Title
    body_lines.append(f"[bold {c}]{title}[/bold {c}]\n")

    # Description
    body_lines.append(description)

    # Fields
    if fields:
        body_lines.append("")
        for fname, fvalue, inline in fields:  # noqa: F841 — inline unused in terminal
            body_lines.append(f"\n[bold]{fname}[/bold]")
            body_lines.append(fvalue)

    # Footer
    if footer:
        body_lines.append(f"\n[dim]{footer}[/dim]")

    body = "\n".join(body_lines)

    return Panel(
        body,
        border_style=c,
        expand=True,
        padding=(1, 2),
        subtitle="[dim]📱 DM Discord[/dim]",
    )


# ─────────────────────────────────────────────────────────────────────────────
# DM 1 — Défense subie (DEFENSE_TAKEN)
# ─────────────────────────────────────────────────────────────────────────────
def dm_defense_taken() -> Panel:
    trophies_lost = 38
    trophies_before = 6_247
    trophies_after = trophies_before - trophies_lost

    return discord_embed(
        title="🛡️ Défense subie",
        description=(
            f"Tu viens de perdre **{trophies_lost}** trophées "
            f"(passé de **{trophies_before:,}** à **{trophies_after:,}**).\n\n"
            f"**Attaque estimée** : ⭐⭐⭐ 3 étoiles • destruction ~100 %\n"
            f"_Estimé d'après les trophées perdus — l'API CoC_\n"
            f"_n'expose pas le détail des défenses subies._"
        ),
        fields=[
            (
                "📊 Contexte",
                (
                    "Tu es à **6 209** trophées — à **209** au-dessus\n"
                    "du seuil de relégation (6 000). Continue à attaquer."
                ),
                False,
            ),
        ],
        footer="🕐 Prochain reset Legend : 17:00 UTC  •  Désactive avec /ping actif:False",
        color=COLOR_WARNING,
        thumbnail="🛡️",
    )


# ─────────────────────────────────────────────────────────────────────────────
# DM 2 — Attaque faible détectée (ATTACK_LOW_GAIN) — nouvelle fonctionnalité
# ─────────────────────────────────────────────────────────────────────────────
def dm_attack_low_gain() -> Panel:
    n_attacks = 2
    avg_gain = 18

    return discord_embed(
        title="⚔️ Attaque faible détectée",
        description=(
            f"Tu viens de faire **{n_attacks} attaques** pour un gain moyen "
            f"de **{avg_gain} trophées** (seuil : 40).\n\n"
            "**Analyse :** Gain faible — plusieurs attaques ont peut-être abouti "
            "à 2 étoiles ou à une destruction insuffisante.\n\n"
            "💡 **Conseils :**\n"
            "• Vise **3 étoiles** : même une base légèrement plus faible rapporte plus.\n"
            "• Assure ton **queen walk** ou super-troops avant l'attaque principale.\n"
            "• Évite les bases avec **double inferno monocible** sans assez de guérisseurs.\n"
            "• Pratique le **funnel** — une armée mal orientée perd toujours."
        ),
        fields=[
            (
                "📈 Tes stats du jour",
                (
                    "Attaques : **3 / 8**  •  Gain moyen : **18 tr.**\n"
                    "Trophées actuels : **6 174**  •  Record aujourd'hui : **6 231**"
                ),
                False,
            ),
            (
                "🎯 Objectif recommandé",
                (
                    "Pour finir la journée positif, vise **+35 tr.** sur tes\n"
                    "5 prochaines attaques. Soit des bases **6 200–6 350**."
                ),
                False,
            ),
        ],
        footer=(
            "⚔️ Prochain reset : 17:00 UTC  •  /daily pour le bilan complet  "
            "•  Désactive avec /ping actif:False"
        ),
        color=COLOR_WARNING,
        thumbnail="⚔️",
    )


# ─────────────────────────────────────────────────────────────────────────────
# DM 3 — Recap hebdomadaire Legend II/III (WEEKLY_RECAP)
# ─────────────────────────────────────────────────────────────────────────────
def dm_weekly_recap() -> Panel:
    sparkline_trophies = "▂▃▄▄▃▅▆▇"   # 8 jours de trophées
    sparkline_attacks  = "▄▃▄▅▄▆▅▆"   # 8 jours d'attaques

    return discord_embed(
        title="📊 Recap hebdo — Légende II",
        description=(
            "Semaine du **28 avr. → 4 mai 2026** · _Tournoi hebdomadaire Legend II_"
        ),
        fields=[
            (
                "🏆 Trophées",
                (
                    f"Début : **5 812**  →  Fin : **5 944**  •  Net : **+132** tr.\n"
                    f"Record semaine : **5 971**  •  Plus bas : **5 789**\n"
                    f"Tendance : {sparkline_trophies}"
                ),
                False,
            ),
            (
                "⚔️ Attaques",
                (
                    f"Effectuées : **27 / 30**  •  Quota : **90 %** ✅\n"
                    f"Victoires : **19**  •  Défaites : **8**  •  Win rate : **70 %**\n"
                    f"Activité : {sparkline_attacks}"
                ),
                False,
            ),
            (
                "📉 Défenses subies",
                (
                    "Défenses reçues : **24**  •  Trophées perdus : **742**\n"
                    "Pire défense : **−44 tr.**  •  Score malchance moy. : **0.21**"
                ),
                False,
            ),
            (
                "🔮 Projection fin de tournoi",
                (
                    "À ce rythme → **+180 tr.** d'ici dimanche.\n"
                    "Rang estimé (groupe) : **top 25 %** de Legend II."
                ),
                False,
            ),
            (
                "💡 Conseil de la semaine",
                (
                    "Tu n'as pas complété ton quota mercredi et jeudi.\n"
                    "3 attaques manquées = ~90 trophées perdus potentiellement.\n"
                    "Active `/ping` pour recevoir une alerte en fin de journée."
                ),
                False,
            ),
        ],
        footer=(
            "📅 Prochain recap : dimanche 4 mai 22:00 UTC  •  "
            "/carnet pour le détail des défenses"
        ),
        color=COLOR_INFO,
        thumbnail="📊",
    )


# ─────────────────────────────────────────────────────────────────────────────
# DM 4 — Recap attaques du lundi (ATTACK_WEEKLY_RECAP) — Legend I
# ─────────────────────────────────────────────────────────────────────────────
def dm_monday_attack_recap() -> Panel:
    return discord_embed(
        title="📊 Recap attaques — semaine passée",
        description=(
            "**ClashPlayer01** (`#2PP0YJU8`)  ·  "
            "Semaine du **28/04 au 04/05/2026**"
        ),
        fields=[
            (
                "📅 Jours sous le seuil (40 tr.)",
                (
                    "• **Mer 30/04** — gain moy. **18 tr./attaque**\n"
                    "• **Jeu 01/05** — gain moy. **24 tr./attaque**\n"
                    "• **Sam 03/05** — gain moy. **31 tr./attaque**"
                ),
                False,
            ),
            (
                "🗳️ Tes feedbacks (8 attaques notées)",
                (
                    "`████░░░░░░` 🔀 Funnel raté — **4** (50 %)\n"
                    "`██░░░░░░░░` ⏱️ Fail timing — **2** (25 %)\n"
                    "`█░░░░░░░░░` 💥 Erreur d'exéc. — **1** (13 %)\n"
                    "`█░░░░░░░░░` ❓ Autre — **1** (13 %)"
                ),
                False,
            ),
            (
                "🎯 Conseil prioritaire de la semaine",
                (
                    "**Focus semaine : Funnel**\n"
                    "Le funnel est la base de toute attaque 3 étoiles :\n"
                    "• 2 troupes de funnel (giants/super-barbs) sur chaque flanc d'entrée.\n"
                    "• Ton armée principale doit rentrer **au centre**, pas sur les bords.\n"
                    "• Regarde où tes troupes partent en début d'attaque — si elles longent\n"
                    "  les bords, le funnel était raté.\n"
                    "👉 Entraîne-toi sur des bases villages amis cette semaine."
                ),
                False,
            ),
            (
                "📈 Tendance gains (jours faibles)",
                "`▂▃▄`  (bas=faible, haut=proche du seuil)",
                False,
            ),
        ],
        footer=(
            "Recap généré chaque lundi matin · "
            "/carnet pour le détail · "
            "Désactive avec /ping actif:False"
        ),
        color=COLOR_WARNING,
        thumbnail="📊",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    console.print()
    console.rule(
        "[bold cyan]📱 LegendMind V3 — Aperçu des DMs Discord[/bold cyan]",
        style="cyan",
    )
    console.print(
        "\n[dim]Ces DMs sont envoyés directement en message privé au joueur.[/dim]\n"
    )

    # ── DM 1 : Défense subie ─────────────────────────────────────────────
    console.rule("[bold yellow]DM 1 — Défense subie (DEFENSE_TAKEN)[/bold yellow]")
    console.print(
        "[dim]Envoyé dès qu'une défense est détectée (trophies_lost augmente "
        "entre deux polls).\nActivé via /ping actif:True — opt-in, 50/mois en Free.[/dim]\n"
    )
    console.print(dm_defense_taken())

    console.print()

    # ── DM 2 : Attaque faible ────────────────────────────────────────────
    console.rule(
        "[bold yellow]DM 2 — Attaque faible (ATTACK_LOW_GAIN) — avec boutons[/bold yellow]"
    )
    console.print(
        "[dim]Envoyé quand le gain moyen par attaque est < 40 trophées. Cooldown 3 min.\n"
        "Le DM inclut des boutons de feedback : ⏱️ Timing · 🔀 Funnel · 💥 Exéc. · ❓ Autre · ✅ Faux positif\n"
        "Le joueur clique → réponse stockée pour le recap du lundi.[/dim]\n"
    )
    console.print(dm_attack_low_gain())

    console.print()

    # ── DM 3 : Recap hebdo ───────────────────────────────────────────────
    console.rule("[bold yellow]DM 3 — Recap hebdomadaire Legend II/III[/bold yellow]")
    console.print(
        "[dim]Envoyé chaque dimanche à 22h UTC aux joueurs Legend II/III.\n"
        "Pas de DM par défense pour eux — uniquement ce digest hebdo.\n"
        "Idempotent (1 seul DM par semaine même si le bot redémarre).[/dim]\n"
    )
    console.print(dm_weekly_recap())

    console.print()

    # ── DM 4 : Recap lundi ───────────────────────────────────────────────
    console.rule(
        "[bold yellow]DM 4 — Recap attaques du lundi (Legend I)[/bold yellow]"
    )
    console.print(
        "[dim]Envoyé chaque lundi à 9h UTC aux joueurs Legend I.\n"
        "Agrège les feedbacks cliqués dans les DMs d'attaque faible.\n"
        "Conseil personnalisé basé sur la catégorie d'erreur la plus fréquente.[/dim]\n"
    )
    console.print(dm_monday_attack_recap())

    console.print()

    # ── Tableau récap des fonctionnalités ────────────────────────────────
    console.rule("[bold cyan]Résumé des fonctionnalités DM[/bold cyan]")
    t = Table(box=box.ROUNDED, expand=True, show_header=True)
    t.add_column("Fonctionnalité", style="bold")
    t.add_column("Tier", justify="center")
    t.add_column("Déclencheur", style="dim")
    t.add_column("Opt-in", justify="center")
    t.add_column("Cooldown", justify="right")
    t.add_column("Active ?", justify="center")

    t.add_row(
        "🛡️ Défense subie",
        "Legend I",
        "trophies_lost augmente",
        "/ping actif:True",
        "60 s",
        "[green]✅ Oui[/green]",
    )
    t.add_row(
        "⚔️ Attaque faible",
        "Legend I",
        "gain moyen < 40 tr./attaque",
        "/ping actif:True",
        "3 min",
        "[green]✅ Oui[/green]",
    )
    t.add_row(
        "📋 Recap lundi",
        "Legend I",
        "Lundi 9h UTC",
        "/ping actif:True",
        "7 jours",
        "[green]✅ Oui (nouveau)[/green]",
    )
    t.add_row(
        "📊 Recap hebdo",
        "Legend II/III",
        "Dimanche 22h UTC",
        "alert_on_defense=True",
        "6 jours",
        "[green]✅ Oui[/green]",
    )
    t.add_row(
        "⚠️ Relégation imminente",
        "Legend I",
        "trophies < floor + 60",
        "enable_alerts=True",
        "3 h",
        "[green]✅ Oui[/green]",
    )
    t.add_row(
        "🔥 Rythme critique",
        "Legend I",
        "< 2 attaques, reset < 2h",
        "enable_alerts=True",
        "2 h",
        "[green]✅ Oui[/green]",
    )

    console.print(t)
    console.print()
    console.rule("[bold cyan]Fin de l'aperçu[/bold cyan]")


if __name__ == "__main__":
    main()
