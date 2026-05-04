"""Dashboard cog — `/setup`, `/dashboard`, `/compare`, `/ping`, `/digest`.

Three navigable pages (Overview / History / Goals) on a single message,
plus a modal for editing goals. Every interaction is ephemeral so private
data never leaks into a public channel.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import coc
import discord
from discord import app_commands
from discord.ext import commands

from constants import (
    COLOR_INFO,
    COLOR_NEUTRAL,
    COLOR_SUCCESS,
    DIGEST_DEFAULT_HOUR_UTC,
    EMBED_TITLE_DASHBOARD,
    LEAGUE_LOWER_BOUND,
    MAX_LINKED_ACCOUNTS_FREE,
    MAX_LINKED_ACCOUNTS_PREMIUM,
    PING_QUOTA_FREE_MONTHLY,
    LeagueType,
)
from models import LegendSnapshot, PlayerGoal, UserPreferences
from services.billing import BillingService
from services.db import Repository
from services.debug_ndjson import debug_ndjson
from services.game_tuning import get_tuning
from services.logic import predict_end_of_season_trophies
from services.notebook import ErrorNotebookService

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────
class DashboardCog(commands.Cog):
    """User-facing slash commands for the personal dashboard."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: Repository,
        notebook: ErrorNotebookService,
        coc_client: coc.Client,
        billing: BillingService,
    ) -> None:
        self.bot = bot
        self._repo = repository
        self._notebook = notebook
        self._coc = coc_client
        self._billing = billing

    # ── /setup ────────────────────────────────────────────────────────────
    @app_commands.command(
        name="setup",
        description=(
            "Lie ton tag CoC en Legend League — essai Premium auto "
            "(durée selon le serveur)."
        ),
    )
    @app_commands.describe(tag="Ton tag CoC, ex. #2PP0YJU8")
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        tag: str,
    ) -> None:
        debug_ndjson(
            hypothesis_id="SETUP",
            location="dashboard.py:/setup:entry",
            message="setup entry",
            data={"guild_id": interaction.guild_id},
        )
        await interaction.response.defer(ephemeral=True)
        normalised = _normalise_tag(tag)

        # 1. Vérification API CoC (existe + Legend League).
        # asyncio.timeout garantit une réponse en ≤ 8s — sans ça, le client
        # coc.py peut bloquer jusqu'à 10s (timeout client) avant de lever.
        try:
            player = await asyncio.wait_for(
                self._coc.get_player(normalised), timeout=8.0
            )
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏱️ L'API CoC met trop de temps à répondre. Réessaie dans 30 secondes.",
                ephemeral=True,
            )
            return
        except coc.errors.NotFound:
            await interaction.followup.send(
                f"❌ Tag `{normalised}` introuvable côté Clash of Clans.",
                ephemeral=True,
            )
            return
        except coc.errors.Maintenance:
            await interaction.followup.send(
                "🔧 Les serveurs CoC sont en maintenance. Réessaie dans quelques minutes.",
                ephemeral=True,
            )
            return
        except coc.errors.PrivateWarLog:
            # This shouldn't happen for player lookups but guard it anyway.
            await interaction.followup.send(
                f"❌ Tag `{normalised}` introuvable ou profil privé.",
                ephemeral=True,
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("CoC API failure during /setup for %s", normalised)
            # Surface a short hint so the player can self-diagnose.
            hint = str(exc)[:80] if str(exc) else type(exc).__name__
            await interaction.followup.send(
                f"⚠️ Erreur API CoC : `{hint}`\nRéessaie dans une minute.",
                ephemeral=True,
            )
            return
        league = getattr(player, "league", None)
        league_id = getattr(league, "id", None)
        league_name = getattr(league, "name", "Aucune")
        expected_legend_id = get_tuning().coc_legend_league_id
        is_legend_by_name = str(league_name).strip().lower() == "legend league"
        debug_ndjson(
            hypothesis_id="SETUP",
            location="dashboard.py:/setup:league",
            message="league check",
            data={
                "tag": normalised,
                "league_id": league_id,
                "league_name": league_name,
                "expected_legend_id": expected_legend_id,
                "is_legend_by_name": is_legend_by_name,
            },
        )
        if league_id != expected_legend_id and not is_legend_by_name:
            trophies = getattr(player, "trophies", None)
            log.info(
                "/setup rejected: not in Legend League tag=%s league_id=%r league_name=%r trophies=%r expected_id=%d",
                normalised,
                league_id,
                league_name,
                trophies,
                expected_legend_id,
            )
            await interaction.followup.send(
                f"❌ `{normalised}` n'est pas en **Legend League** "
                f"(actuellement : **{league_name}**, trophées: **{trophies}**).\n"
                "LegendMind n'accepte que les comptes **Legend League**.\n\n"
                "Si tu es sûr d'être en Legend : vérifie le tag (0/O), attends 1–2 minutes "
                "puis réessaie (l'API peut être en retard après un changement de ligue).",
                ephemeral=True,
            )
            return
        if league_id != expected_legend_id and is_legend_by_name:
            # Observed in the wild: league id mismatch but name is Legend League.
            # Accept to avoid blocking legit users and log for tuning visibility.
            trophies = getattr(player, "trophies", None)
            log.warning(
                "/setup: accepting Legend by name despite league_id mismatch tag=%s league_id=%r expected_id=%d trophies=%r",
                normalised,
                league_id,
                expected_legend_id,
                trophies,
            )

        # 2. Limite de comptes : Free=1, Premium=3.
        existing = await self._repo.list_active_tags(interaction.user.id)
        entitled = await self._billing.is_entitled(interaction.user.id)
        max_accounts = MAX_LINKED_ACCOUNTS_PREMIUM if entitled else MAX_LINKED_ACCOUNTS_FREE
        if normalised not in existing and len(existing) >= max_accounts:
            tier_label = "Premium" if entitled else "Free"
            await interaction.followup.send(
                f"❌ Limite de comptes atteinte ({len(existing)}/{max_accounts} "
                f"sur le plan {tier_label}).\n"
                "Passe **Premium** avec `/premium` pour lier jusqu'à 3 comptes, "
                "ou retire un compte avec `/accounts`.",
                ephemeral=True,
            )
            return

        # 3. Liaison + essai Premium auto (idempotent, durée selon le serveur).
        await self._repo.link_player(
            tag=normalised,
            discord_user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            name=getattr(player, "name", None),
        )
        sub_before = await self._billing.get_subscription(interaction.user.id)
        trial_was_fresh = not sub_before.trial_used
        await self._billing.start_trial(
            interaction.user.id,
            guild_id=interaction.guild_id,
        )
        trial_days = self._billing.trial_duration_days(interaction.guild_id)

        # 4. Pré-remplissage du tier si on a un rank API (top 200 mondial).
        # Sinon, l'utilisateur déclare son tier via le Select ci-dessous.
        api_tier = _api_tier_hint(player)
        if api_tier is not None:
            await self._repo.set_legend_tier(normalised, api_tier)

        # 5. Demande la confirmation/déclaration du tier (Avril 2026 refonte).
        embed = _setup_success_embed(
            display_name=getattr(player, "name", normalised),
            tag=normalised,
            trial_was_fresh=trial_was_fresh,
            trial_days=trial_days,
            api_tier=api_tier,
        )
        view = _TierSelectView(
            repo=self._repo,
            owner_id=interaction.user.id,
            tag=normalised,
            preselected=api_tier,
            enable_digest_default=True,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ── /verify ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="verify",
        description="Prouve que tu possèdes ton compte CoC via le token en jeu.",
    )
    @app_commands.describe(
        tag="Tag du compte à vérifier (défaut : ton premier compte lié).",
        token="Token affiché dans CoC : Paramètres → Avancé → API token.",
    )
    async def verify_cmd(
        self,
        interaction: discord.Interaction,
        token: str,
        tag: str | None = None,
    ) -> None:
        """Verify account ownership using the Supercell in-game API token.

        The token is a one-time code shown in-game under Settings → Advanced
        → API token.  It rotates on every check, so it proves live access.
        We never store the token — only the resulting `verified=TRUE` flag.
        """
        await interaction.response.defer(ephemeral=True)
        target = (
            _normalise_tag(tag)
            if tag
            else await self._repo.get_first_active_tag(interaction.user.id)
        )
        if target is None:
            await interaction.followup.send(
                "Aucun compte CoC lié. Utilise `/setup tag:#TONTAG` d'abord.",
                ephemeral=True,
            )
            return
        # Security: only the owner can verify their own account.
        owner = await self._repo.get_owner_id_for_tag(target)
        if owner != interaction.user.id:
            await interaction.followup.send(
                f"❌ `{target}` n'est pas lié à ton compte Discord.",
                ephemeral=True,
            )
            return
        try:
            ok = await self._coc.verify_player_token(target, token.strip())
        except Exception:  # noqa: BLE001
            log.exception("verify_player_token failed for %s", target)
            await interaction.followup.send(
                "⚠️ L'API CoC n'a pas répondu. Réessaie dans une minute.",
                ephemeral=True,
            )
            return
        if not ok:
            await interaction.followup.send(
                "❌ Token invalide ou expiré.\n"
                "Le token change après chaque consultation — "
                "récupère-en un nouveau dans CoC → Paramètres → Avancé → API token.",
                ephemeral=True,
            )
            return
        await self._repo.set_verified(target)
        await interaction.followup.send(
            f"✅ Compte `{target}` **vérifié** — badge ✔ affiché dans ton dashboard.",
            ephemeral=True,
        )

    # ── /tier ─────────────────────────────────────────────────────────────
    @app_commands.command(
        name="tier",
        description=("Déclare/met à jour ton tier Legend (I, II ou III) — Avril 2026."),
    )
    @app_commands.describe(tag="Tag du compte (par défaut : ton premier compte lié).")
    async def tier_cmd(
        self,
        interaction: discord.Interaction,
        tag: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        target = (
            _normalise_tag(tag)
            if tag
            else await self._repo.get_first_active_tag(interaction.user.id)
        )
        if target is None:
            await interaction.followup.send(
                "Aucun compte CoC lié. Utilise `/setup tag:#TONTAG` d'abord.",
                ephemeral=True,
            )
            return
        # Sécurité : on ne change le tier que d'un compte appartenant à l'invocateur.
        owner = await self._repo.get_owner_id_for_tag(target)
        if owner != interaction.user.id:
            await interaction.followup.send(
                f"❌ Le tag `{target}` n'est pas lié à ton compte Discord.",
                ephemeral=True,
            )
            return
        current = await self._repo.get_legend_tier(target)
        embed = discord.Embed(
            title=f"🎯 Déclare ton tier — `{target}`",
            description=(
                "Sélectionne ton tier Legend actuel. Source de vérité : "
                "l'application Clash of Clans (Profil → Legend League).\n"
                f"Tier actuel enregistré : **{_tier_label(current)}**."
            ),
            color=COLOR_INFO,
        )
        view = _TierSelectView(
            repo=self._repo,
            owner_id=interaction.user.id,
            tag=target,
            preselected=current if current is not LeagueType.UNKNOWN else None,
            enable_digest_default=False,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ── /dashboard ────────────────────────────────────────────────────────
    @app_commands.command(
        name="dashboard",
        description="Ton tableau de bord Legend League.",
    )
    async def dashboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        tag = await _first_active_tag(self._repo, interaction.user.id)
        if tag is None:
            await interaction.followup.send(
                "Aucun compte CoC lié. Utilise `/setup tag:#TAG` d'abord.",
                ephemeral=True,
            )
            return

        prefs = await self._repo.get_preferences(interaction.user.id)
        view = _DashboardView(
            repo=self._repo,
            notebook=self._notebook,
            player_tag=tag,
            prefs=prefs,
        )
        await view.refresh()
        await interaction.followup.send(
            embed=view.current_embed,
            view=view,
            ephemeral=True,
        )

    # ── /compare ──────────────────────────────────────────────────────────
    @app_commands.command(
        name="compare",
        description="Compare tes stats à celles d'un autre membre.",
    )
    @app_commands.describe(membre="Le membre Discord à comparer")
    async def compare(
        self,
        interaction: discord.Interaction,
        membre: discord.Member,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        my_tag = await _first_active_tag(self._repo, interaction.user.id)
        their_tag = await _first_active_tag(self._repo, membre.id)
        if my_tag is None or their_tag is None:
            await interaction.followup.send(
                "L'un de vous deux n'a pas encore lié de compte CoC.",
                ephemeral=True,
            )
            return

        my_snap = await self._repo.get_latest_snapshot(my_tag)
        their_snap = await self._repo.get_latest_snapshot(their_tag)
        if my_snap is None or their_snap is None:
            await interaction.followup.send(
                "Pas encore assez de données pour comparer.",
                ephemeral=True,
            )
            return

        embed = _render_compare(
            interaction.user.display_name,
            my_snap,
            membre.display_name,
            their_snap,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /ping ─────────────────────────────────────────────────────────────
    @app_commands.command(
        name="ping",
        description=(
            "Active/désactive le DM automatique à chaque défense subie "
            "(50/mois en Free, illimité Premium)."
        ),
    )
    @app_commands.describe(
        actif="True pour activer, False pour désactiver. Vide pour voir l'état.",
    )
    async def ping_toggle(
        self,
        interaction: discord.Interaction,
        actif: bool | None = None,
    ) -> None:
        """Toggle ``alert_on_defense`` and report quota / entitlement state."""
        prefs = await self._repo.get_preferences(interaction.user.id)
        # State lines reference the entitlement directly (no QuotaService coupling
        # in this command — enforcement lives in AlertManager._dispatch_one).
        entitled = await self._billing.is_entitled(interaction.user.id)
        if actif is None:
            state = "✅ activé" if prefs.alert_on_defense else "🔕 désactivé"
            quota_line = (
                "Plan **Premium / Essai** : DM illimités."
                if entitled
                else f"Plan **Free** : quota {PING_QUOTA_FREE_MONTHLY} DM/mois."
            )
            await interaction.response.send_message(
                f"État actuel : **{state}**.\n{quota_line}\n"
                "Pour changer : `/ping actif:True` ou `/ping actif:False`.",
                ephemeral=True,
            )
            return
        prefs.alert_on_defense = actif
        await self._repo.upsert_preferences(prefs)
        if actif:
            cap = (
                "illimité (Premium / Essai actif)"
                if entitled
                else f"jusqu'à {PING_QUOTA_FREE_MONTHLY} DM/mois (Free)"
            )
            msg = (
                f"✅ DM activés à chaque défense — {cap}.\n"
                "Désactive à tout moment avec `/ping actif:False`."
            )
        else:
            msg = "🔕 DM de défense désactivés. Réactive avec `/ping actif:True`."
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /digest ───────────────────────────────────────────────────────────
    @app_commands.command(
        name="digest",
        description="Digest DM 1×/jour: daily, predict, score — heure UTC réglable.",
    )
    @app_commands.describe(
        actif="True = activer, False = désactiver. Vide = afficher l'état.",
        heure_utc="Heure d'envoi en UTC (0–23). Vide = ne pas modifier.",
    )
    async def digest_cmd(
        self,
        interaction: discord.Interaction,
        actif: bool | None = None,
        heure_utc: app_commands.Range[int, 0, 23] | None = None,
    ) -> None:
        """Toggle automated daily coaching digest + optional UTC hour."""
        prefs = await self._repo.get_preferences(interaction.user.id)
        if actif is None and heure_utc is None:
            state = "✅ activé" if prefs.digest_daily_enabled else "🔕 désactivé"
            await interaction.response.send_message(
                f"**Digest auto** : {state}.\n"
                f"Heure UTC : **{prefs.digest_hour_utc}h** "
                f"(défaut bot : {DIGEST_DEFAULT_HOUR_UTC}h).\n"
                "• `/digest actif:True` — activer\n"
                "• `/digest actif:False` — couper\n"
                f"• `/digest heure_utc:14` — envoi chaque jour à 14:00 UTC",
                ephemeral=True,
            )
            return
        if heure_utc is not None:
            prefs.digest_hour_utc = int(heure_utc)
        if actif is not None:
            prefs.digest_daily_enabled = actif
        await self._repo.upsert_preferences(prefs)
        parts = [
            f"Heure UTC : **{prefs.digest_hour_utc}h**.",
        ]
        if actif is True:
            parts.insert(0, "✅ Digest quotidien **activé**.")
        elif actif is False:
            parts.insert(0, "🔕 Digest quotidien **désactivé**.")
        else:
            st = "activé" if prefs.digest_daily_enabled else "désactivé"
            parts.insert(0, f"Réglages digest mis à jour ({st}).")
        await interaction.response.send_message("\n".join(parts), ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# View — paginated dashboard.
# ─────────────────────────────────────────────────────────────────────────────
class _DashboardView(discord.ui.View):
    """Three-page dashboard. Stores all per-page state on the view itself."""

    PAGE_OVERVIEW = 0
    PAGE_HISTORY = 1
    PAGE_GOALS = 2

    def __init__(
        self,
        repo: Repository,
        notebook: ErrorNotebookService,
        player_tag: str,
        prefs: UserPreferences,
    ) -> None:
        super().__init__(timeout=300.0)
        self._repo = repo
        self._notebook = notebook
        self._tag = player_tag
        self._prefs = prefs
        self._page = self.PAGE_OVERVIEW
        self._snapshots: list[LegendSnapshot] = []
        self._goal: PlayerGoal | None = None
        self._player_row: dict[str, object] | None = None
        self.current_embed: discord.Embed = discord.Embed(
            title=EMBED_TITLE_DASHBOARD,
        )

    # ── data load ────────────────────────────────────────────────────────
    async def refresh(self) -> None:
        """Reload snapshots + goal + player meta and rebuild the current page."""
        since = datetime.now(timezone.utc) - timedelta(days=7)
        self._snapshots = await self._repo.get_snapshots_since(self._tag, since)
        self._goal = await self._repo.get_goal(self._tag)
        self._player_row = await self._repo.get_player_row(self._tag)
        self._render()

    def _render(self) -> None:
        if self._page == self.PAGE_OVERVIEW:
            self.current_embed = self._render_overview()
        elif self._page == self.PAGE_HISTORY:
            self.current_embed = self._render_history()
        else:
            self.current_embed = self._render_goals()

    # ── pages ────────────────────────────────────────────────────────────
    def _render_overview(self) -> discord.Embed:
        latest = self._latest()
        row = self._player_row or {}

        # Build title with verified badge and clan.
        verified = row.get("verified", False)
        badge = " ✔" if verified else ""
        clan_name = row.get("clan_name")
        clan_tag = row.get("clan_tag")
        clan_part = f" · 🏰 {clan_name}" if clan_name else ""
        title = f"{EMBED_TITLE_DASHBOARD}{badge}{clan_part}"

        embed = discord.Embed(title=title, color=COLOR_INFO)

        if clan_tag and clan_name:
            embed.add_field(
                name="🏰 Clan",
                value=f"[{clan_name}](https://link.clashofclans.com/en?action=OpenClanProfile&tag={str(clan_tag).lstrip('#')})",
                inline=True,
            )
        if not verified:
            embed.add_field(
                name="🔓 Compte non vérifié",
                value="Utilise `/verify` pour prouver que ce compte t'appartient.",
                inline=False,
            )

        if latest is None:
            embed.description = "Aucune donnée pour l'instant. Reviens plus tard."
            return embed

        embed.add_field(
            name="🏆 Trophées",
            value=_trophy_progress(latest),
            inline=False,
        )
        embed.add_field(
            name="⚔️ Attaques aujourd'hui",
            value=f"{latest.attacks_done}/8 (Légende I)"
            if latest.league_type == LeagueType.LEGEND_I
            else "Quota hebdomadaire (II/III)",
            inline=True,
        )
        prediction = predict_end_of_season_trophies(
            self._snapshots,
            latest.league_type,
        )
        embed.add_field(
            name="🔮 Projection fin de saison",
            value=f"{prediction} trophées",
            inline=True,
        )
        if self._prefs.enable_error_notebook:
            today = datetime.now(timezone.utc).date()
            today_defenses = [s for s in self._snapshots if s.captured_at.date() == today]
            # Lightweight today-snapshot count; full malchance comes from /carnet.
            embed.add_field(
                name="📓 Carnet",
                value=f"{len(today_defenses)} mises à jour aujourd'hui",
                inline=False,
            )
        return embed

    def _render_history(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"{EMBED_TITLE_DASHBOARD} — Historique",
            color=COLOR_NEUTRAL,
        )
        if len(self._snapshots) < 2:
            embed.description = "Pas assez de données pour tracer l'historique."
            return embed

        spark = _trophy_sparkline(self._snapshots)
        embed.add_field(name="📈 7 derniers jours", value=f"```{spark}```", inline=False)

        daily = _daily_extrema(self._snapshots)
        if daily:
            best, worst = daily
            embed.add_field(
                name="🌟 Meilleur jour",
                value=f"{best[1]:+d} trophées le {best[0]:%d/%m}",
                inline=True,
            )
            embed.add_field(
                name="💧 Pire jour",
                value=f"{worst[1]:+d} trophées le {worst[0]:%d/%m}",
                inline=True,
            )

        won, lost = _win_loss_estimate(self._snapshots)
        ratio = (won / (won + lost)) if (won + lost) else 0.0
        embed.add_field(
            name="⚖️ Ratio gains/pertes (estimé)",
            value=f"{won} ↑ / {lost} ↓ ({ratio:.0%})",
            inline=False,
        )
        return embed

    def _render_goals(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"{EMBED_TITLE_DASHBOARD} — Objectifs",
            color=COLOR_SUCCESS,
        )
        latest = self._latest()
        if self._goal is None:
            embed.description = "Aucun objectif défini. Clique sur ✏️ pour en créer un."
            return embed

        progress = 0.0
        if latest is not None and self._goal.target_trophies > 0:
            base = LEAGUE_LOWER_BOUND.get(LeagueType.LEGEND_III, 5000)
            denom = max(1, self._goal.target_trophies - base)
            progress = max(0.0, min(1.0, (latest.trophies - base) / denom))

        bar = _progress_bar(progress)
        embed.add_field(
            name="🎯 Objectif trophées",
            value=(
                f"{latest.trophies if latest else '—'} / "
                f"{self._goal.target_trophies}\n{bar} {progress:.0%}"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚔️ Quota d'attaques par jour",
            value=f"{self._goal.target_attacks_per_day}",
            inline=True,
        )
        days_left = _days_until_season_end()
        embed.add_field(
            name="📅 Jours restants",
            value=str(days_left),
            inline=True,
        )
        if self._goal.notes:
            embed.add_field(
                name="📝 Notes",
                value=self._goal.notes,
                inline=False,
            )
        return embed

    # ── helpers ──────────────────────────────────────────────────────────
    def _latest(self) -> LegendSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    # ── buttons ──────────────────────────────────────────────────────────
    @discord.ui.button(label="Vue d'ensemble", style=discord.ButtonStyle.primary)
    async def go_overview(
        self,
        interaction: discord.Interaction,
        _b: discord.ui.Button[discord.ui.View],
    ) -> None:
        self._page = self.PAGE_OVERVIEW
        self._render()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    @discord.ui.button(label="Historique", style=discord.ButtonStyle.secondary)
    async def go_history(
        self,
        interaction: discord.Interaction,
        _b: discord.ui.Button[discord.ui.View],
    ) -> None:
        self._page = self.PAGE_HISTORY
        self._render()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    @discord.ui.button(label="Objectifs", style=discord.ButtonStyle.secondary)
    async def go_goals(
        self,
        interaction: discord.Interaction,
        _b: discord.ui.Button[discord.ui.View],
    ) -> None:
        self._page = self.PAGE_GOALS
        self._render()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    @discord.ui.button(label="✏️ Modifier l'objectif", style=discord.ButtonStyle.success, row=1)
    async def edit_goal(
        self,
        interaction: discord.Interaction,
        _b: discord.ui.Button[discord.ui.View],
    ) -> None:
        modal = _EditGoalModal(self, self._goal)
        await interaction.response.send_modal(modal)


# ─────────────────────────────────────────────────────────────────────────────
# Modal
# ─────────────────────────────────────────────────────────────────────────────
class _EditGoalModal(discord.ui.Modal, title="✏️ Modifier mon objectif"):
    target_trophies: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Objectif trophées",
        placeholder="Ex: 6200",
        required=True,
    )
    target_attacks: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Quota attaques/jour",
        placeholder="Entre 1 et 8",
        required=True,
        max_length=2,
    )
    notes: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Notes",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(
        self,
        view: _DashboardView,
        current: PlayerGoal | None,
    ) -> None:
        super().__init__()
        self._view = view
        if current is not None:
            self.target_trophies.default = str(current.target_trophies)
            self.target_attacks.default = str(current.target_attacks_per_day)
            self.notes.default = current.notes

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            trophies = int(str(self.target_trophies))
            attacks = int(str(self.target_attacks))
        except ValueError:
            await interaction.response.send_message(
                "Les valeurs numériques sont invalides.",
                ephemeral=True,
            )
            return
        attacks = max(1, min(8, attacks))
        goal = PlayerGoal(
            player_tag=self._view._tag,  # noqa: SLF001 (intentional binding)
            target_trophies=trophies,
            target_attacks_per_day=attacks,
            notes=str(self.notes),
        )
        await self._view._repo.upsert_goal(goal)  # noqa: SLF001
        await self._view.refresh()
        await interaction.response.edit_message(
            embed=self._view.current_embed,
            view=self._view,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Comparison embed
# ─────────────────────────────────────────────────────────────────────────────
def _render_compare(
    name_a: str,
    snap_a: LegendSnapshot,
    name_b: str,
    snap_b: LegendSnapshot,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚔️ {name_a} vs {name_b}",
        color=COLOR_INFO,
    )

    def _pair(label: str, a: int, b: int, fmt: str = "{}") -> None:
        leader_a = "🏅" if a > b else "  "
        leader_b = "🏅" if b > a else "  "
        embed.add_field(
            name=label,
            value=(
                f"{leader_a} **{name_a}** : {fmt.format(a)}\n"
                f"{leader_b} **{name_b}** : {fmt.format(b)}"
            ),
            inline=False,
        )

    _pair("🏆 Trophées", snap_a.trophies, snap_b.trophies)
    _pair("⚔️ Attaques aujourd'hui", snap_a.attacks_done, snap_b.attacks_done)
    _pair("📉 Trophées perdus", snap_a.trophies_lost, snap_b.trophies_lost)
    _pair("📈 Trophées gagnés", snap_a.trophies_gained, snap_b.trophies_gained)
    return embed


# ─────────────────────────────────────────────────────────────────────────────
# Rendering helpers
# ─────────────────────────────────────────────────────────────────────────────
def _normalise_tag(tag: str) -> str:
    cleaned = tag.strip().upper()
    if not cleaned.startswith("#"):
        cleaned = "#" + cleaned
    return cleaned


async def _first_active_tag(repo: Repository, discord_user_id: int) -> str | None:
    return await repo.get_first_active_tag(discord_user_id)


# ─────────────────────────────────────────────────────────────────────────────
# Tier declaration UI (used by /setup and /tier).
# ─────────────────────────────────────────────────────────────────────────────
def _api_tier_hint(player: object) -> LeagueType | None:
    """Auto-detect Legend I if the API exposes a top-200 rank.

    The CoC public API only populates ``LegendStatistics.current_season.rank``
    for the global top 200. When present, the player is unambiguously
    Legend I; otherwise we cannot infer the tier and must ask.
    """
    legend = getattr(player, "legend_statistics", None)
    if legend is None:
        return None
    current = getattr(legend, "current_season", None)
    if current is None:
        return None
    rank = getattr(current, "rank", None)
    if rank is None or int(rank) <= 0:
        return None
    return LeagueType.LEGEND_I


def _tier_label(tier: LeagueType) -> str:
    return {
        LeagueType.LEGEND_I: "Légende I",
        LeagueType.LEGEND_II: "Légende II",
        LeagueType.LEGEND_III: "Légende III",
        LeagueType.UNKNOWN: "Non déclaré",
    }[tier]


def _setup_success_embed(
    *,
    display_name: str,
    tag: str,
    trial_was_fresh: bool,
    trial_days: int,
    api_tier: LeagueType | None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"✅ Compte lié — {display_name}",
        description=f"Tag : `{tag}`",
        color=COLOR_SUCCESS,
    )
    if trial_was_fresh:
        embed.add_field(
            name=f"🎁 Essai Premium ({trial_days} j)",
            value=(
                "Activé automatiquement : `/ping` illimité, jusqu'à 3 comptes, "
                "accès complet aux commandes coaching."
            ),
            inline=False,
        )
    if api_tier is LeagueType.LEGEND_I:
        embed.add_field(
            name="🥇 Tier détecté automatiquement",
            value=(
                "Tu es dans le **top 200 mondial** d'après l'API Clash of Clans "
                "→ tier **Légende I** présélectionné. Confirme ci-dessous "
                "(ou change si tu es en train de redescendre)."
            ),
            inline=False,
        )
    else:
        embed.add_field(
            name="🎯 Déclare ton tier (refonte Avril 2026)",
            value=(
                "L'API CoC n'expose le rang qu'au-dessus du top 200. "
                "Sélectionne ton tier dans le menu ci-dessous — tu peux le "
                "changer plus tard avec `/tier`."
            ),
            inline=False,
        )
    return embed


class _TierSelectView(discord.ui.View):
    """Single-row dropdown with the three Legend tiers."""

    def __init__(
        self,
        repo: Repository,
        owner_id: int,
        tag: str,
        preselected: LeagueType | None,
        *,
        enable_digest_default: bool = True,
    ) -> None:
        super().__init__(timeout=120.0)
        self.add_item(
            _TierSelect(
                repo,
                owner_id,
                tag,
                preselected,
                enable_digest_default=enable_digest_default,
            ),
        )


class _TierSelect(discord.ui.Select[discord.ui.View]):
    """Persists the chosen Legend tier for ``tag`` (owner-only)."""

    def __init__(
        self,
        repo: Repository,
        owner_id: int,
        tag: str,
        preselected: LeagueType | None,
        *,
        enable_digest_default: bool = True,
    ) -> None:
        options = [
            discord.SelectOption(
                label="Légende I (8 batailles/jour, top 12 500 mondial)",
                value=str(int(LeagueType.LEGEND_I)),
                emoji="🥇",
                default=preselected is LeagueType.LEGEND_I,
            ),
            discord.SelectOption(
                label="Légende II (30 batailles/semaine, top 12 500–62 500)",
                value=str(int(LeagueType.LEGEND_II)),
                emoji="🥈",
                default=preselected is LeagueType.LEGEND_II,
            ),
            discord.SelectOption(
                label="Légende III (24 batailles/semaine, le reste)",
                value=str(int(LeagueType.LEGEND_III)),
                emoji="🥉",
                default=preselected is LeagueType.LEGEND_III,
            ),
        ]
        super().__init__(
            placeholder="Sélectionne ton tier Legend",
            min_values=1,
            max_values=1,
            options=options,
        )
        self._repo = repo
        self._owner = owner_id
        self._tag = tag
        self._enable_digest_default = enable_digest_default

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._owner:
            await interaction.response.send_message(
                "❌ Cette sélection ne peut être faite que par le propriétaire du compte.",
                ephemeral=True,
            )
            return
        try:
            tier = LeagueType(int(self.values[0]))
        except (ValueError, KeyError):
            await interaction.response.send_message(
                "❌ Tier invalide.",
                ephemeral=True,
            )
            return
        await self._repo.set_legend_tier(self._tag, tier)
        digest_line = ""
        if self._enable_digest_default:
            prefs = await self._repo.get_preferences(self._owner)
            prefs.digest_daily_enabled = True
            prefs.digest_hour_utc = DIGEST_DEFAULT_HOUR_UTC
            await self._repo.upsert_preferences(prefs)
            digest_line = (
                f"\n**Digest auto** activé ({DIGEST_DEFAULT_HOUR_UTC}h UTC) : chaque jour "
                "tu recevras par DM l'équivalent de `/daily`, `/predict` et `/score` "
                "pour tes comptes liés. Règle avec `/digest`."
            )
        # Legend I only: ask the season-end trophy goal right away (helps onboarding).
        if tier is LeagueType.LEGEND_I:
            await interaction.response.send_modal(
                _SetupLegendIGoalModal(
                    repo=self._repo,
                    tag=self._tag,
                    owner_id=self._owner,
                    digest_line=digest_line,
                )
            )
            return
        await interaction.response.send_message(
            f"✅ Tier `{self._tag}` enregistré : **{_tier_label(tier)}**."
            f"{digest_line}\n"
            f"Tu peux toujours changer le tier avec `/tier tag:{self._tag}`.",
            ephemeral=True,
        )


class _SetupLegendIGoalModal(discord.ui.Modal, title="🎯 Objectif fin de saison (Légende I)"):
    target_trophies: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Objectif trophées (fin de saison)",
        placeholder="Ex: 6200",
        required=True,
        max_length=5,
    )

    def __init__(
        self,
        *,
        repo: Repository,
        tag: str,
        owner_id: int,
        digest_line: str,
    ) -> None:
        super().__init__()
        self._repo = repo
        self._tag = tag
        self._owner_id = owner_id
        self._digest_line = digest_line

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._owner_id:
            await interaction.response.send_message(
                "❌ Seul le propriétaire du compte peut définir cet objectif.",
                ephemeral=True,
            )
            return
        try:
            trophies = int(str(self.target_trophies).strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Objectif trophées invalide (nombre attendu).",
                ephemeral=True,
            )
            return
        trophies = max(0, trophies)
        # Legend I: attacks/day quota is always 8, so we store a sensible default.
        await self._repo.upsert_goal(
            PlayerGoal(
                player_tag=self._tag,
                target_trophies=trophies,
                target_attacks_per_day=8,
                notes="",
            )
        )
        await interaction.response.send_message(
            f"✅ Tier `{self._tag}` enregistré : **Légende I**.\n"
            f"🎯 Objectif fin de saison : **{trophies}** trophées.\n"
            f"{self._digest_line}\n"
            f"Tu peux modifier cet objectif plus tard via `/dashboard` → **Objectifs**.",
            ephemeral=True,
        )


def _progress_bar(value: float, width: int = 12) -> str:
    filled = max(0, min(width, round(value * width)))
    return "█" * filled + "░" * (width - filled)


def _trophy_progress(snap: LegendSnapshot) -> str:
    """Trophies + bar to next league boundary (or current league floor distance)."""
    league = snap.league_type
    if league == LeagueType.UNKNOWN:
        return f"**{snap.trophies}** (hors Légende)"
    if league == LeagueType.LEGEND_I:
        return f"**{snap.trophies}** ({_league_label(league)})"

    nxt = _next_league(league)
    if nxt is None:
        return f"**{snap.trophies}** ({_league_label(league)})"
    next_floor = LEAGUE_LOWER_BOUND[nxt]
    current_floor = LEAGUE_LOWER_BOUND[league]
    progress = (snap.trophies - current_floor) / max(1, (next_floor - current_floor))
    progress = max(0.0, min(1.0, progress))
    return (
        f"**{snap.trophies}** ({_league_label(league)})\n"
        f"{_progress_bar(progress)}  "
        f"{snap.trophies}/{next_floor} → {_league_label(nxt)}"
    )


def _next_league(league: LeagueType) -> LeagueType | None:
    if league == LeagueType.LEGEND_III:
        return LeagueType.LEGEND_II
    if league == LeagueType.LEGEND_II:
        return LeagueType.LEGEND_I
    return None


def _league_label(league: LeagueType) -> str:
    return {
        LeagueType.LEGEND_I: "Légende I",
        LeagueType.LEGEND_II: "Légende II",
        LeagueType.LEGEND_III: "Légende III",
        LeagueType.UNKNOWN: "—",
    }[league]


def _trophy_sparkline(snapshots: list[LegendSnapshot]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    values = [s.trophies for s in snapshots]
    lo, hi = min(values), max(values)
    if hi == lo:
        return blocks[0] * len(values)
    span = hi - lo
    return "".join(
        blocks[min(len(blocks) - 1, round((v - lo) / span * (len(blocks) - 1)))] for v in values
    )


def _daily_extrema(
    snapshots: list[LegendSnapshot],
) -> tuple[tuple[datetime, int], tuple[datetime, int]] | None:
    """Best and worst day in terms of net trophy delta over the snapshot range."""
    by_day: dict[datetime, list[LegendSnapshot]] = {}
    for s in snapshots:
        key = datetime.combine(s.captured_at.date(), datetime.min.time())
        by_day.setdefault(key, []).append(s)

    if not by_day:
        return None
    deltas: list[tuple[datetime, int]] = []
    for day, snaps in by_day.items():
        snaps.sort(key=lambda s: s.captured_at)
        deltas.append((day, snaps[-1].trophies - snaps[0].trophies))
    if not deltas:
        return None
    best = max(deltas, key=lambda x: x[1])
    worst = min(deltas, key=lambda x: x[1])
    return best, worst


def _win_loss_estimate(snapshots: list[LegendSnapshot]) -> tuple[int, int]:
    """Counts of upward vs downward consecutive deltas (rough win/loss proxy)."""
    won = lost = 0
    for prev, cur in zip(snapshots, snapshots[1:]):
        diff = cur.trophies - prev.trophies
        if diff > 0:
            won += 1
        elif diff < 0:
            lost += 1
    return won, lost


def _days_until_season_end() -> int:
    now = datetime.now(timezone.utc)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return max(0, (end - now).days)
