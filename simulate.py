#!/usr/bin/env python3
"""LegendMind V3 — Season Simulator.

Simulates N Legend I players across a full season.
Exercises business logic (malchance, pace, alerts, rank prediction)
without any real DB, Discord, or CoC API connection.

Usage
-----
    python scripts/simulate.py                         # 10 000 players, 30 days
    python scripts/simulate.py --players 1000 --days 30
    python scripts/simulate.py --players 10000 --seed 42
    python scripts/simulate.py --speed fast            # skip sleep between days
"""
# ruff: noqa: E402  — sys.path.insert must run before project imports
from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Add project root to sys.path so we can import services ───────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Rich terminal UI ──────────────────────────────────────────────────────────
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from constants import (
    ALERT_COMEBACK_DELTA,
    LEGEND_I_DAILY_ATTACK_QUOTA,
    MALCHANCE_HIGH_THRESHOLD,
    RELEGATION_PROXIMITY_TROPHIES,
    LeagueType,
)
from models import DefenseData, LegendSnapshot
from services.logic import (
    check_attack_pace,
    check_threshold,
    get_malchance_score,
)
from services.rank_predictor import RankDataPoint, _fit_curve, format_rank, rank_emoji

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Simulation config
# ─────────────────────────────────────────────────────────────────────────────
SEASON_DAYS = 28          # Legend I tournament = 4 weeks
DAILY_RESET_HOUR = 5      # CoC daily reset (UTC)
LEAGUE_FLOOR = 5000       # Legend III lower bound for reference
LEGEND_I_FLOOR = 6000

# Attack outcome probabilities by player strategy
_STRATEGIES = {
    "aggressive":  {"win_rate": 0.72, "avg_gain": 38, "avg_loss": 22},
    "balanced":    {"win_rate": 0.62, "avg_gain": 35, "avg_loss": 26},
    "defensive":   {"win_rate": 0.52, "avg_gain": 32, "avg_loss": 30},
    "inconsistent":{"win_rate": 0.50, "avg_gain": 36, "avg_loss": 32},
}

# Defense outcome (each player receives 0–3 defenses per day)
_DEF_PROFILES = {
    "easy_base":   {"incoming_avg": 0.8, "loss_avg": 24, "loss_std": 6},
    "medium_base": {"incoming_avg": 1.5, "loss_avg": 30, "loss_std": 8},
    "hard_base":   {"incoming_avg": 2.2, "loss_avg": 38, "loss_std": 10},
}

# Commands players "use" — weighted by realism
_COMMAND_WEIGHTS = {
    "/dashboard":   30,
    "/predict":     20,
    "/carnet":      12,
    "/classement":  10,
    "/score":        8,
    "/daily":        8,
    "/ping":         5,
    "/verify":       3,
    "/compare":      4,
}

# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SimPlayer:
    tag: str
    name: str
    strategy: str
    def_profile: str
    trophies: int
    snapshots: list[LegendSnapshot] = field(default_factory=list)
    daily_attacks: list[int] = field(default_factory=list)   # attacks per day
    daily_net: list[int] = field(default_factory=list)        # net trophies per day
    defenses: list[DefenseData] = field(default_factory=list)
    alerts_received: dict[str, int] = field(default_factory=dict)
    commands_used: dict[str, int] = field(default_factory=dict)
    malchance_scores: list[float] = field(default_factory=list)
    was_relegated: bool = False
    season_high: int = 0
    season_low: int = 0


@dataclass
class DailyStats:
    day: int
    total_attacks: int = 0
    total_wins: int = 0
    total_trophies_gained: int = 0
    total_trophies_lost: int = 0
    alerts_fired: dict[str, int] = field(default_factory=dict)
    relegations: int = 0
    quota_completions: int = 0    # players who hit 8/8
    high_malchance_events: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Simulation engine
# ─────────────────────────────────────────────────────────────────────────────
def _make_snapshot(player: SimPlayer, day: int) -> LegendSnapshot:
    base = datetime(2026, 5, 1, DAILY_RESET_HOUR, 0, tzinfo=timezone.utc)
    captured = base + timedelta(days=day, hours=random.uniform(0, 16))
    return LegendSnapshot(
        player_tag=player.tag,
        trophies=player.trophies,
        league_type=LeagueType.LEGEND_I,
        attacks_done=player.daily_attacks[-1] if player.daily_attacks else 0,
        trophies_gained=sum(max(0, n) for n in player.daily_net[-3:]),
        trophies_lost=sum(max(0, -n) for n in player.daily_net[-3:]),
        captured_at=captured,
    )


def simulate_day(player: SimPlayer, day: int, rng: random.Random) -> DailyStats:
    """Simulate one CoC day for one player. Returns per-player day stats."""
    stats = DailyStats(day=day)
    strat = _STRATEGIES[player.strategy]
    def_prof = _DEF_PROFILES[player.def_profile]

    # Decide how many attacks (0–8); inconsistent players skip randomly
    if player.strategy == "inconsistent" and rng.random() < 0.30:
        n_attacks = rng.randint(0, 4)
    else:
        n_attacks = rng.randint(6, LEGEND_I_DAILY_ATTACK_QUOTA)

    # Simulate each attack
    day_gain = 0
    day_attacks = n_attacks
    wins = 0
    for _ in range(n_attacks):
        if rng.random() < strat["win_rate"]:
            gain = int(rng.gauss(strat["avg_gain"], 5))
            player.trophies += max(10, gain)
            day_gain += max(10, gain)
            wins += 1
        else:
            loss = int(rng.gauss(12, 3))   # offensive loss is small
            player.trophies -= max(5, loss)
            day_gain -= max(5, loss)

    stats.total_attacks += day_attacks
    stats.total_wins += wins
    stats.total_trophies_gained += max(0, day_gain)

    # Simulate incoming defenses
    n_defenses = int(rng.expovariate(1.0 / def_prof["incoming_avg"]))
    n_defenses = min(n_defenses, 5)
    day_def_loss = 0
    for _ in range(n_defenses):
        loss = max(5, int(rng.gauss(def_prof["loss_avg"], def_prof["loss_std"])))
        opp_trophies = player.trophies + rng.randint(-300, 100)
        n_att = rng.choices([1, 1, 1, 2, 3], weights=[50, 50, 30, 15, 5])[0]
        defense = DefenseData(
            trophies_lost=loss,
            opponent_tag=f"#OPP{rng.randint(1000,9999)}",
            opponent_trophies=opp_trophies,
            attack_count=n_att,
        )
        player.defenses.append(defense)
        malchance = get_malchance_score(defense, LeagueType.LEGEND_I)
        player.malchance_scores.append(malchance)
        player.trophies -= loss
        day_def_loss += loss
        if malchance >= MALCHANCE_HIGH_THRESHOLD:
            stats.high_malchance_events += 1

    stats.total_trophies_lost += day_def_loss
    player.daily_attacks.append(day_attacks)
    player.daily_net.append(day_gain - day_def_loss)

    # Clamp trophies to Legend range
    player.trophies = max(4900, player.trophies)

    # Track season high/low
    if player.trophies > player.season_high:
        player.season_high = player.trophies
    if player.season_low == 0 or player.trophies < player.season_low:
        player.season_low = player.trophies

    # Save snapshot
    snap = _make_snapshot(player, day)
    player.snapshots.append(snap)

    # ── Alert evaluation ────────────────────────────────────────────────
    # Build a snapshot for threshold/pace checking
    threshold = check_threshold(snap)
    if threshold:
        player.alerts_received[threshold] = player.alerts_received.get(threshold, 0) + 1
        stats.alerts_fired[threshold] = stats.alerts_fired.get(threshold, 0) + 1

    pace = check_attack_pace(day_attacks, LeagueType.LEGEND_I)
    if pace:
        player.alerts_received[pace] = player.alerts_received.get(pace, 0) + 1
        stats.alerts_fired[pace] = stats.alerts_fired.get(pace, 0) + 1

    # Comeback detection (simplified)
    if len(player.daily_net) >= 3:
        recent_gain = sum(player.daily_net[-3:])
        if recent_gain >= ALERT_COMEBACK_DELTA:
            player.alerts_received["comeback_detected"] = (
                player.alerts_received.get("comeback_detected", 0) + 1
            )

    # Relegation check
    if player.trophies < LEGEND_I_FLOOR - RELEGATION_PROXIMITY_TROPHIES:
        player.was_relegated = True
        stats.relegations += 1

    # Quota completion
    if day_attacks == LEGEND_I_DAILY_ATTACK_QUOTA:
        stats.quota_completions += 1

    # Simulate command usage (random subset per day)
    if rng.random() < 0.65:  # 65% chance of using any command today
        cmd = rng.choices(
            list(_COMMAND_WEIGHTS.keys()),
            weights=list(_COMMAND_WEIGHTS.values()),
        )[0]
        player.commands_used[cmd] = player.commands_used.get(cmd, 0) + 1

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────
def _c(v: int) -> str:
    """Rich color tag: green for positive, red for negative."""
    return "green" if v >= 0 else "red"


def _sparkline(values: "list[float] | list[int]", width: int = 20) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not values:
        return "—"
    lo, hi = min(values), max(values)
    span = hi - lo if hi != lo else 1
    result = ""
    step = max(1, len(values) // width)
    for i in range(0, len(values), step):
        v = values[i]
        idx = min(len(blocks) - 1, int((v - lo) / span * (len(blocks) - 1)))
        result += blocks[idx]
    return result[:width]


def render_final_dashboard(
    players: list[SimPlayer],
    daily: list[DailyStats],
    season_days: int,
    elapsed_s: float,
) -> None:
    console.print()
    console.rule("[bold cyan]⚔️  LegendMind — Rapport final de simulation[/bold cyan]")
    console.print()

    # ── Key numbers ──────────────────────────────────────────────────────
    n = len(players)
    total_attacks = sum(d.total_attacks for d in daily)
    total_wins = sum(d.total_wins for d in daily)
    total_trophies_gained = sum(d.total_trophies_gained for d in daily)
    total_trophies_lost = sum(d.total_trophies_lost for d in daily)
    total_alerts = sum(
        sum(d.alerts_fired.values()) for d in daily
    )
    total_commands = sum(sum(p.commands_used.values()) for p in players)
    relegated = sum(1 for p in players if p.was_relegated)
    high_malchance = sum(d.high_malchance_events for d in daily)

    # Trophy distribution
    final_trophies = sorted(p.trophies for p in players)
    avg_trophies = sum(final_trophies) / n
    median_trophies = final_trophies[n // 2]
    top1_trophies = final_trophies[-1]
    top1_pct_trophies = final_trophies[int(n * 0.99)]
    bot10_trophies = final_trophies[int(n * 0.10)]

    # Rank curve from final leaderboard
    top200 = sorted(players, key=lambda p: p.trophies, reverse=True)[:200]
    rank_points = [
        RankDataPoint(rank=i + 1, trophies=p.trophies, player_tag=p.tag, player_name=p.name)
        for i, p in enumerate(top200)
    ]
    curve = _fit_curve(rank_points)

    # ── Overview table ───────────────────────────────────────────────────
    ov = Table(title="📊 Vue d'ensemble", box=box.ROUNDED, expand=True)
    ov.add_column("Métrique", style="bold")
    ov.add_column("Valeur", justify="right", style="cyan")

    ov.add_row("Joueurs simulés", f"{n:,}")
    ov.add_row("Jours de saison", str(season_days))
    ov.add_row("Temps d'exécution", f"{elapsed_s:.1f}s")
    ov.add_row("Vitesse", f"{n * season_days / elapsed_s:,.0f} joueurs·jours/s")
    ov.add_row("─" * 20, "─" * 12)
    ov.add_row("Attaques totales", f"{total_attacks:,}")
    ov.add_row("Win rate global", f"{total_wins/total_attacks:.1%}" if total_attacks else "—")
    ov.add_row("Trophées gagnés", f"{total_trophies_gained:,}")
    ov.add_row("Trophées perdus", f"{total_trophies_lost:,}")
    ov.add_row("Net saison", f"{total_trophies_gained - total_trophies_lost:+,}")
    ov.add_row("─" * 20, "─" * 12)
    ov.add_row("Alertes déclenchées", f"{total_alerts:,}")
    ov.add_row("Commandes utilisées", f"{total_commands:,}")
    ov.add_row("Joueurs relégués", f"{relegated:,}  ({relegated/n:.1%})")
    ov.add_row("Défenses haute malchance", f"{high_malchance:,}")
    console.print(ov)
    console.print()

    # ── Trophy distribution ──────────────────────────────────────────────
    td = Table(title="🏆 Distribution de trophées (fin de saison)", box=box.ROUNDED, expand=True)
    td.add_column("Percentile")
    td.add_column("Trophées", justify="right", style="yellow")
    td.add_column("Rang estimé", justify="right", style="green")

    for pct_label, trophies in [
        ("🥇 Top 1 (record)", top1_trophies),
        ("Top 1%", top1_pct_trophies),
        ("Médiane (50%)", median_trophies),
        ("Moyenne", int(avg_trophies)),
        ("Bottom 10%", bot10_trophies),
    ]:
        est_rank = curve.estimate_rank(trophies) if curve else None
        td.add_row(pct_label, f"{trophies:,}", format_rank(est_rank))

    td.add_row("", "", "")
    if curve:
        td.add_row(
            "Courbe rank r²",
            f"{curve.r_squared:.4f}",
            "🟢 fiable" if curve.r_squared > 0.90 else "🔴 faible",
        )
    console.print(td)
    console.print()

    # ── Daily trophy sparkline ───────────────────────────────────────────
    daily_net = [d.total_trophies_gained - d.total_trophies_lost for d in daily]
    daily_alerts = [sum(d.alerts_fired.values()) for d in daily]
    daily_quota = [d.quota_completions for d in daily]

    spark_tbl = Table(title="📈 Activité quotidienne (sparklines)", box=box.ROUNDED, expand=True)
    spark_tbl.add_column("Métrique", style="bold")
    spark_tbl.add_column("Courbe", style="cyan")
    spark_tbl.add_column("Min", justify="right")
    spark_tbl.add_column("Max", justify="right")
    spark_tbl.add_column("Moy", justify="right")

    rows_spark: list[tuple[str, list[int]]] = [
        ("Net trophées/jour", daily_net),
        ("Alertes/jour", daily_alerts),
        ("8/8 attaques/jour", daily_quota),
    ]
    for label, series in rows_spark:
        spark_tbl.add_row(
            label,
            _sparkline(series, width=28),
            f"{min(series):,}",
            f"{max(series):,}",
            f"{sum(series) / len(series):,.0f}",
        )
    console.print(spark_tbl)
    console.print()

    # ── Alert breakdown ──────────────────────────────────────────────────
    all_alerts: dict[str, int] = {}
    for d in daily:
        for k, v in d.alerts_fired.items():
            all_alerts[k] = all_alerts.get(k, 0) + v

    at = Table(title="🔔 Détail des alertes", box=box.ROUNDED, expand=True)
    at.add_column("Type d'alerte", style="bold")
    at.add_column("Nombre", justify="right", style="cyan")
    at.add_column("% du total", justify="right")
    at.add_column("Barre", min_width=20)

    total_a = max(1, sum(all_alerts.values()))
    for alert_type, count in sorted(all_alerts.items(), key=lambda x: -x[1]):
        pct = count / total_a
        bar_len = max(1, int(pct * 20))
        bar = "█" * bar_len + "░" * (20 - bar_len)
        at.add_row(alert_type, f"{count:,}", f"{pct:.1%}", bar)
    console.print(at)
    console.print()

    # ── Command usage ────────────────────────────────────────────────────
    all_cmds: dict[str, int] = {}
    for p in players:
        for cmd, cnt in p.commands_used.items():
            all_cmds[cmd] = all_cmds.get(cmd, 0) + cnt

    ct = Table(title="💬 Commandes Discord utilisées", box=box.ROUNDED, expand=True)
    ct.add_column("Commande", style="bold")
    ct.add_column("Total", justify="right", style="cyan")
    ct.add_column("Par joueur/saison", justify="right")
    ct.add_column("Barre", min_width=20)

    total_c = max(1, sum(all_cmds.values()))
    for cmd, cnt in sorted(all_cmds.items(), key=lambda x: -x[1]):
        bar_len = max(1, int(cnt / total_c * 20))
        bar = "█" * bar_len + "░" * (20 - bar_len)
        ct.add_row(cmd, f"{cnt:,}", f"{cnt/n:.1f}", bar)
    console.print(ct)
    console.print()

    # ── Strategy breakdown ───────────────────────────────────────────────
    strat_groups: dict[str, list[SimPlayer]] = {}
    for p in players:
        strat_groups.setdefault(p.strategy, []).append(p)

    st = Table(title="⚔️  Résultats par stratégie d'attaque", box=box.ROUNDED, expand=True)
    st.add_column("Stratégie", style="bold")
    st.add_column("Joueurs", justify="right")
    st.add_column("Trophées moy.", justify="right", style="yellow")
    st.add_column("Record moy.", justify="right", style="green")
    st.add_column("Relégués", justify="right", style="red")
    st.add_column("Malchance moy.", justify="right")

    for strat_name in sorted(strat_groups.keys()):
        group = strat_groups[strat_name]
        avg_tr = sum(p.trophies for p in group) / len(group)
        avg_hi = sum(p.season_high for p in group) / len(group)
        rel = sum(1 for p in group if p.was_relegated)
        avg_mal = (
            sum(
                sum(p.malchance_scores) / max(1, len(p.malchance_scores))
                for p in group
            )
            / len(group)
        )
        st.add_row(
            strat_name,
            str(len(group)),
            f"{avg_tr:,.0f}",
            f"{avg_hi:,.0f}",
            f"{rel} ({rel/len(group):.0%})",
            f"{avg_mal:.3f}",
        )
    console.print(st)
    console.print()

    # ── Rank prediction accuracy ─────────────────────────────────────────
    if curve and curve.r_squared > 0.70:
        console.print(
            Panel(
                f"[bold green]✅ Rank Predictor opérationnel[/bold green]\n"
                f"Courbe log-linéaire sur {len(rank_points)} joueurs\n"
                f"r² = {curve.r_squared:.4f} · a = {curve.a:.1f} · b = {curve.b:.1f}\n\n"
                f"Exemple : {rank_emoji(curve.estimate_rank(6500))} "
                f"6 500 trophées → rang estimé {format_rank(curve.estimate_rank(6500))}\n"
                f"          {rank_emoji(curve.estimate_rank(6200))} "
                f"6 200 trophées → rang estimé {format_rank(curve.estimate_rank(6200))}\n"
                f"          {rank_emoji(curve.estimate_rank(5800))} "
                f"5 800 trophées → rang estimé {format_rank(curve.estimate_rank(5800))}",
                title="🔮 Rank Predictor",
                expand=True,
            )
        )
    console.print()
    console.rule("[bold cyan]Simulation terminée ✓[/bold cyan]")


# ─────────────────────────────────────────────────────────────────────────────
# Progress display helpers
# ─────────────────────────────────────────────────────────────────────────────
def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
    )


def _live_day_panel(
    day: int,
    season_days: int,
    today: DailyStats,
    cumulative_alerts: dict[str, int],
    top5: list[SimPlayer],
    bottom5: list[SimPlayer],
    avg_trophies: float,
) -> Panel:
    top5_lines = "\n".join(
        f"  [yellow]{rank_emoji(i+1)}[/yellow] {p.name[:16]:<16} "
        f"[cyan]{p.trophies:>6,}[/cyan] tr."
        for i, p in enumerate(top5)
    )
    bot5_lines = "\n".join(
        f"  [red]↓[/red] {p.name[:16]:<16} "
        f"[cyan]{p.trophies:>6,}[/cyan] tr."
        for p in bottom5
    )
    alert_summary = "  " + "  ".join(
        f"[yellow]{k}[/yellow]:{v:,}"
        for k, v in sorted(cumulative_alerts.items(), key=lambda x: -x[1])[:4]
    )
    win_rate = (
        f"{today.total_wins / today.total_attacks:.1%}"
        if today.total_attacks
        else "—"
    )
    body = (
        f"[bold]Jour {day}/{season_days}[/bold] · "
        f"Attaques : [cyan]{today.total_attacks:,}[/cyan] · "
        f"Win rate : [green]{win_rate}[/green] · "
        f"Trophées moy. : [yellow]{avg_trophies:,.0f}[/yellow] · "
        f"Relégations : [red]{today.relegations}[/red]\n\n"
        f"[bold]Top 5[/bold]\n{top5_lines}\n\n"
        f"[bold]Bottom 5[/bold]\n{bot5_lines}\n\n"
        f"[bold]Alertes cumulées[/bold]\n{alert_summary or '  (aucune)'}"
    )
    return Panel(body, title=f"📅 Saison en cours — Jour {day}", expand=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="LegendMind Season Simulator")
    parser.add_argument(
        "--players", type=int, default=10_000, help="Joueurs (défaut 10 000)"
    )
    parser.add_argument(
        "--days", type=int, default=SEASON_DAYS, help="Jours de saison (défaut 28)"
    )
    parser.add_argument("--seed", type=int, default=2026, help="Graine aléatoire")
    parser.add_argument(
        "--speed", choices=["normal", "fast"], default="fast", help="Vitesse"
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    n = args.players

    console.rule("[bold cyan]⚔️  LegendMind V3 — Season Simulator[/bold cyan]")
    console.print(
        f"\n[bold]Config :[/bold] {n:,} joueurs · {args.days} jours · "
        f"seed={args.seed} · speed={args.speed}\n"
    )

    # ── Phase 1 : Générer les joueurs ────────────────────────────────────
    console.print("[bold yellow]Phase 1/3[/bold yellow] — Génération des joueurs…")
    players: list[SimPlayer] = []
    strategies = list(_STRATEGIES.keys())
    def_profiles = list(_DEF_PROFILES.keys())
    strategy_weights = [35, 40, 15, 10]   # aggressive, balanced, defensive, inconsistent
    def_weights = [30, 50, 20]

    with _make_progress() as prog:
        task = prog.add_task("Création des joueurs", total=n)
        for i in range(n):
            strat = rng.choices(strategies, weights=strategy_weights)[0]
            def_prof = rng.choices(def_profiles, weights=def_weights)[0]
            start_trophies = int(rng.gauss(6300, 400))
            start_trophies = max(6000, min(9000, start_trophies))
            p = SimPlayer(
                tag=f"#SIM{i:06d}",
                name=f"Player{i:05d}",
                strategy=strat,
                def_profile=def_prof,
                trophies=start_trophies,
                season_high=start_trophies,
                season_low=start_trophies,
            )
            players.append(p)
            prog.advance(task)

    console.print(f"  ✅ {n:,} joueurs créés\n")

    # ── Phase 2 : Simulation de la saison ───────────────────────────────
    daily_stats: list[DailyStats] = []
    cumulative_alerts: dict[str, int] = {}
    n * args.days
    t0 = time.perf_counter()
    done_player_days = 0
    # Refresh the Live display only once per day (not 10k times/day).

    def _build_live(
        day: int,
        day_agg: DailyStats,
        avg_tr: float,
        top3: list[SimPlayer],
        elapsed: float,
        speed: float,
    ) -> Panel:
        """Single panel that fits in a terminal without scrolling."""
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_column(justify="right")

        # ── progress bar row ──
        done = (day - 1) * n
        total = args.days * n
        pct = done / total if total else 0
        bar_w = 50
        filled = int(pct * bar_w)
        bar = (
            "[bold green]"
            + "█" * filled
            + "[/bold green][dim]"
            + "░" * (bar_w - filled)
            + "[/dim]"
        )
        eta = (elapsed / pct * (1 - pct)) if pct > 0.001 else 0

        grid.add_row(
            f"[bold cyan]⚔️  LegendMind Simulator[/bold cyan]  "
            f"Jour [bold]{day}[/bold] / {args.days}  "
            f"{bar}  [bold]{pct:.0%}[/bold]",
            f"[dim]{elapsed:.1f}s  ETA {eta:.0f}s  {speed:,.0f} p·j/s[/dim]",
        )

        grid.add_row("")

        # ── live stats row ──
        win_r = (
            f"{day_agg.total_wins / day_agg.total_attacks:.1%}"
            if day_agg.total_attacks
            else "—"
        )
        net = day_agg.total_trophies_gained - day_agg.total_trophies_lost
        grid.add_row(
            f"  Attaques : [cyan]{day_agg.total_attacks:,}[/cyan]  "
            f"Win rate : [green]{win_r}[/green]  "
            f"Net : [{_c(net)}]{net:+,}[/{_c(net)}] tr.  "
            f"Quota 8/8 : [yellow]{day_agg.quota_completions:,}[/yellow]  "
            f"Relégués : [red]{day_agg.relegations}[/red]  "
            f"Trophées moy. : [yellow]{avg_tr:,.0f}[/yellow]",
            "",
        )

        # ── alerts row ──
        top_alerts = sorted(cumulative_alerts.items(), key=lambda x: -x[1])[:5]
        if top_alerts:
            alert_txt = "  Alertes : " + "  ".join(
                f"[yellow]{k.replace('_', ' ')}[/yellow] {v:,}" for k, v in top_alerts
            )
            grid.add_row(alert_txt, "")

        # ── top 3 row ──
        if top3:
            top3_txt = "  Top 3 : " + "  ".join(
                f"[bold]{rank_emoji(i+1)}[/bold] {p.name} [cyan]{p.trophies:,}[/cyan]"
                for i, p in enumerate(top3)
            )
            grid.add_row(top3_txt, "")

        return Panel(grid, title="[bold]Saison en cours[/bold]", expand=True)

    with Live(console=console, refresh_per_second=4) as live:
        for day in range(1, args.days + 1):
            day_agg = DailyStats(day=day)

            for player in players:
                day_result = simulate_day(player, day, rng)
                day_agg.total_attacks += day_result.total_attacks
                day_agg.total_wins += day_result.total_wins
                day_agg.total_trophies_gained += day_result.total_trophies_gained
                day_agg.total_trophies_lost += day_result.total_trophies_lost
                day_agg.relegations += day_result.relegations
                day_agg.quota_completions += day_result.quota_completions
                day_agg.high_malchance_events += day_result.high_malchance_events
                for k, v in day_result.alerts_fired.items():
                    day_agg.alerts_fired[k] = day_agg.alerts_fired.get(k, 0) + v
                    cumulative_alerts[k] = cumulative_alerts.get(k, 0) + v

            daily_stats.append(day_agg)
            done_player_days += n
            elapsed_now = time.perf_counter() - t0
            speed_now = done_player_days / max(0.001, elapsed_now)
            avg_tr_now = sum(p.trophies for p in players) / n
            top3_now = sorted(players, key=lambda p: p.trophies, reverse=True)[:3]
            live.update(
                _build_live(day + 1, day_agg, avg_tr_now, top3_now, elapsed_now, speed_now)
            )

    elapsed = time.perf_counter() - t0
    console.print(
        f"\n✅ [bold]{args.days}[/bold] jours simulés en "
        f"[cyan]{elapsed:.2f}s[/cyan]  "
        f"({n * args.days / elapsed:,.0f} joueurs·jours/s)\n"
    )

    # ── Phase 3 : Rank curve + predictions ──────────────────────────────
    console.print("[bold yellow]Phase 3/3[/bold yellow] — Calcul du rank predictor…")
    top200 = sorted(players, key=lambda p: p.trophies, reverse=True)[:200]
    rank_points = [
        RankDataPoint(rank=i + 1, trophies=p.trophies, player_tag=p.tag, player_name=p.name)
        for i, p in enumerate(top200)
    ]
    curve = _fit_curve(rank_points)
    # Pre-sort once for rank accuracy check (O(n log n) instead of O(n²))
    sorted_by_trophies = sorted(players, key=lambda x: x.trophies, reverse=True)
    true_rank_map = {p.tag: i + 1 for i, p in enumerate(sorted_by_trophies)}
    correct_predictions = 0
    for p in players:
        if curve:
            est = curve.estimate_rank(p.trophies)
            true_rank = true_rank_map[p.tag]
            if est and abs(est - true_rank) / max(1, true_rank) < 0.20:
                correct_predictions += 1

    pred_acc = correct_predictions / n if curve else 0
    r2 = curve.r_squared if curve else 0.0
    console.print(
        f"  ✅ Courbe rank : r²={r2:.4f} · "
        f"précision (±20%) = {pred_acc:.1%}\n"
    )

    # ── Final Dashboard ──────────────────────────────────────────────────
    sorted(players, key=lambda p: p.trophies, reverse=True)[:5]
    sorted(players, key=lambda p: p.trophies)[:5]
    sum(p.trophies for p in players) / n

    render_final_dashboard(players, daily_stats, args.days, elapsed)


if __name__ == "__main__":
    main()
