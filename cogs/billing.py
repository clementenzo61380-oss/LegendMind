"""Billing cog — `/premium` and `/accounts`.

Surfaces the entitlement model to end users without exposing Stripe directly:
- ``/premium`` opens a Stripe Checkout session URL (or a graceful "not
  available" message when Stripe isn't configured locally).
- ``/accounts`` lists / removes the user's linked CoC tags with a paginated
  `discord.ui.View` of buttons.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from constants import (
    COLOR_INFO,
    COLOR_NEUTRAL,
    COLOR_SUCCESS,
    MAX_LINKED_ACCOUNTS_FREE,
    MAX_LINKED_ACCOUNTS_PREMIUM,
    PING_QUOTA_FREE_MONTHLY,
    PREMIUM_MONTHLY_PRICE_EUR_DISPLAY,
    LeagueType,
)
from models import Subscription, SubscriptionPlan
from services.billing import (
    BillingNotConfigured,
    BillingService,
    subscription_trial_window_days,
)
from services.db import Repository
from services.quota import QuotaService

log = logging.getLogger(__name__)


class BillingCog(commands.Cog):
    """User-facing premium / account management commands."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: Repository,
        billing: BillingService,
        quota: QuotaService,
    ) -> None:
        self.bot = bot
        self._repo = repository
        self._billing = billing
        self._quota = quota

    # ── /premium ─────────────────────────────────────────────────────────
    @app_commands.command(
        name="premium",
        description=(
            "Active ton essai gratuit Premium (durée selon le serveur), "
            "ou ouvre Stripe pour souscrire."
        ),
    )
    async def premium(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if self._billing.is_lifetime_entitled(interaction.user.id):
            await interaction.followup.send(
                embed=_lifetime_partner_embed(),
                ephemeral=True,
            )
            return

        sub = await self._billing.get_subscription(interaction.user.id)
        now = datetime.now(timezone.utc)

        # Étape 1 : essai pas encore consommé → on l'accorde.
        if not sub.trial_used:
            sub = await self._billing.start_trial(
                interaction.user.id,
                guild_id=interaction.guild_id,
            )
            embed = _trial_embed(sub)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Étape 2 : essai consommé mais Premium déjà actif (entitled).
        if sub.is_entitled(now):
            embed = _active_premium_embed(sub)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Étape 3 : essai épuisé / Premium expiré → Checkout Stripe.
        try:
            url = await self._billing.start_checkout(interaction.user.id)
        except BillingNotConfigured as exc:
            await interaction.followup.send(
                f"⚠️ Le paiement n'est pas encore configuré sur cette instance du bot.\n_{exc}_",
                ephemeral=True,
            )
            return
        view = _CheckoutView(url)
        embed = _checkout_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ── /accounts ────────────────────────────────────────────────────────
    @app_commands.command(
        name="accounts",
        description="Affiche tes comptes CoC liés (tier inclus, Free: 1 / Premium: 3).",
    )
    async def accounts(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        accounts = await self._repo.list_active_accounts(interaction.user.id)
        sub = await self._billing.get_subscription(interaction.user.id)
        entitled = await self._billing.is_entitled(interaction.user.id)
        max_accounts = MAX_LINKED_ACCOUNTS_PREMIUM if entitled else MAX_LINKED_ACCOUNTS_FREE
        embed = await _accounts_embed(
            accounts=accounts,
            sub=sub,
            max_accounts=max_accounts,
            quota=self._quota,
            user_id=interaction.user.id,
        )
        if not accounts:
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        view = _AccountsView(
            repo=self._repo,
            owner_id=interaction.user.id,
            tags=[t for (t, _n, _tier) in accounts],
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# ─────────────────────────────────────────────────────────────────────────────
# Embeds
# ─────────────────────────────────────────────────────────────────────────────
def _lifetime_partner_embed() -> discord.Embed:
    return discord.Embed(
        title="⭐ Accès Premium permanent",
        description=(
            "Ton compte Discord est sur la **liste autorisée** de cette "
            "instance : tu as les mêmes avantages que Premium **sans payer** "
            "(`/ping` illimité, jusqu'à **3 comptes** CoC, etc.)."
        ),
        color=COLOR_SUCCESS,
    )


def _trial_embed(sub: Subscription) -> discord.Embed:
    end = sub.current_period_end
    n_days = subscription_trial_window_days(sub)
    embed = discord.Embed(
        title="🎁 Essai Premium activé",
        description=(
            f"Ton essai **{n_days} jours** est en cours. "
            "Profite de :\n"
            "• `/ping` illimité\n"
            "• Jusqu'à **3 comptes** CoC liés (`/accounts`)\n"
            "• Toutes les commandes coaching (`/predict`, `/score`, `/daily`)"
        ),
        color=COLOR_SUCCESS,
    )
    if end is not None:
        embed.add_field(
            name="Expire le",
            value=f"<t:{int(end.timestamp())}:F> (<t:{int(end.timestamp())}:R>)",
            inline=False,
        )
    embed.set_footer(
        text="À la fin de l'essai : retour automatique au plan Free, puis /premium pour souscrire.",
    )
    return embed


def _active_premium_embed(sub: Subscription) -> discord.Embed:
    end = sub.current_period_end
    label = "Essai" if sub.plan is SubscriptionPlan.TRIAL else "Premium"
    embed = discord.Embed(
        title=f"✅ {label} actif",
        color=COLOR_SUCCESS,
    )
    if end is not None:
        embed.add_field(
            name="Renouvellement / fin",
            value=f"<t:{int(end.timestamp())}:F> (<t:{int(end.timestamp())}:R>)",
            inline=False,
        )
    embed.add_field(
        name="Pour gérer ton abonnement",
        value="Stripe t'envoie un portail client par e-mail, ou contacte le support.",
        inline=False,
    )
    return embed


def _checkout_embed() -> discord.Embed:
    embed = discord.Embed(
        title="💳 Souscrire au Premium",
        description=(
            f"**{PREMIUM_MONTHLY_PRICE_EUR_DISPLAY} / mois** (TTC, via Stripe).\n"
            "Clique sur le bouton ci-dessous pour ouvrir le paiement sécurisé.\n\n"
            "Tu obtiens : `/ping` illimité, jusqu'à 3 comptes liés, accès "
            "complet aux commandes coaching."
        ),
        color=COLOR_INFO,
    )
    embed.set_footer(
        text="Paiement géré par Stripe ; ton compte est crédité dès "
        "réception du webhook (quelques secondes).",
    )
    return embed


async def _accounts_embed(
    *,
    accounts: list[tuple[str, str | None, LeagueType]],
    sub: Subscription,
    max_accounts: int,
    quota: QuotaService,
    user_id: int,
) -> discord.Embed:
    plan_label = {
        SubscriptionPlan.FREE: "Free",
        SubscriptionPlan.TRIAL: "Premium (essai)",
        SubscriptionPlan.PREMIUM: "Premium",
    }[sub.plan]
    color = COLOR_NEUTRAL if sub.plan is SubscriptionPlan.FREE else COLOR_SUCCESS
    embed = discord.Embed(
        title="🔗 Comptes CoC liés",
        description=(f"Plan **{plan_label}** — limite : {len(accounts)}/{max_accounts}"),
        color=color,
    )
    if not accounts:
        embed.add_field(
            name="Aucun compte lié",
            value="Utilise `/setup tag:#TONTAG` pour démarrer.",
            inline=False,
        )
        return embed
    lines = []
    for tag, name, tier in accounts:
        label_name = f" — {name}" if name else ""
        lines.append(f"{_tier_emoji(tier)} `{tag}`{label_name} · **{_tier_label(tier)}**")
    embed.add_field(name="Comptes", value="\n".join(lines), inline=False)
    remaining = await quota.remaining(user_id)
    if remaining is None:
        quota_line = "Illimité (Premium / Essai)"
    else:
        quota_line = f"{remaining}/{PING_QUOTA_FREE_MONTHLY} DM restants ce mois"
    embed.add_field(name="Quota /ping", value=quota_line, inline=False)
    if any(t is LeagueType.UNKNOWN for (_t, _n, t) in accounts):
        embed.add_field(
            name="⚠️ Tier non déclaré",
            value=(
                "Un ou plusieurs comptes n'ont pas de tier déclaré. "
                "Lance `/tier tag:#TAG` pour le préciser — sans cela "
                "`/daily`, `/predict` et `/score` resteront en attente."
            ),
            inline=False,
        )
    if sub.plan is SubscriptionPlan.FREE:
        embed.set_footer(
            text="Passe Premium avec /premium pour 3 comptes + DM illimités.",
        )
    return embed


def _tier_label(tier: LeagueType) -> str:
    return {
        LeagueType.LEGEND_I: "Légende I",
        LeagueType.LEGEND_II: "Légende II",
        LeagueType.LEGEND_III: "Légende III",
        LeagueType.UNKNOWN: "Tier non déclaré",
    }[tier]


def _tier_emoji(tier: LeagueType) -> str:
    return {
        LeagueType.LEGEND_I: "🥇",
        LeagueType.LEGEND_II: "🥈",
        LeagueType.LEGEND_III: "🥉",
        LeagueType.UNKNOWN: "❓",
    }[tier]


# ─────────────────────────────────────────────────────────────────────────────
# Views
# ─────────────────────────────────────────────────────────────────────────────
class _CheckoutView(discord.ui.View):
    """Single-button view that opens the Stripe Checkout URL."""

    def __init__(self, url: str) -> None:
        super().__init__(timeout=600.0)
        self.add_item(
            discord.ui.Button(
                style=discord.ButtonStyle.link,
                label="💳 Ouvrir Stripe Checkout",
                url=url,
            )
        )


class _AccountsView(discord.ui.View):
    """One ✖ button per linked tag — soft-deletes via repo.deactivate_player."""

    def __init__(
        self,
        repo: Repository,
        owner_id: int,
        tags: list[str],
    ) -> None:
        super().__init__(timeout=120.0)
        self._repo = repo
        self._owner = owner_id
        for tag in tags[:5]:  # Discord caps at 5 buttons per row
            self.add_item(_RemoveAccountButton(repo, owner_id, tag))


class _RemoveAccountButton(discord.ui.Button[discord.ui.View]):
    """Per-tag removal button — only callable by the original requester."""

    def __init__(self, repo: Repository, owner_id: int, tag: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.danger,
            label=f"✖ {tag}",
        )
        self._repo = repo
        self._owner = owner_id
        self._tag = tag

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self._owner:
            await interaction.response.send_message(
                "❌ Cette action n'est disponible que pour le propriétaire des comptes.",
                ephemeral=True,
            )
            return
        ok = await self._repo.deactivate_player(self._tag, self._owner)
        if ok:
            await interaction.response.send_message(
                f"✅ Compte `{self._tag}` retiré. Utilise `/setup` pour le relier.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"⚠️ `{self._tag}` n'était plus actif.",
                ephemeral=True,
            )
