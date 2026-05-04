"""Attack Feedback cog — Vue interactive des DMs d'attaque faible.

Quand `ATTACK_LOW_GAIN` est déclenché, `AlertManager` envoie un DM avec
une `AttackFeedbackView`.  Le joueur clique sur un bouton pour catégoriser
son erreur. La réponse est persistée dans `attack_feedback` pour le recap
du lundi.

Catégories :
- ⏱️ Timing      — attaque lancée trop tôt / CC mal géré / héros pas prêts
- 🔀 Funnel      — armée mal orientée en début d'attaque
- 💥 Exécution   — mauvais drop de sorts, mauvaise zone d'entrée
- ❓ Autre        — cause inconnue ou combinaison
- ✅ Faux positif — l'attaque était en réalité correcte (base très défensive)
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from services.db import Repository

log = logging.getLogger(__name__)

# Feedback types → (label, emoji, value)
FEEDBACK_CHOICES: list[tuple[str, str, str]] = [
    ("Fail timing",   "⏱️", "timing"),
    ("Funnel raté",   "🔀", "funnel"),
    ("Exec. rate",    "💥", "execution"),
    ("Autre",         "❓", "other"),
    ("Faux positif",  "✅", "false_pos"),
]


class _FeedbackSelect(discord.ui.Select["AttackFeedbackView"]):
    """Dropdown unique — plus simple et type-safe que des boutons dynamiques."""

    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=label, emoji=emoji, value=value,
                description=_SHORT_DESC.get(value, ""),
            )
            for label, emoji, value in FEEDBACK_CHOICES
        ]
        super().__init__(
            placeholder="Qu'est-ce qui a posé problème ?",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AttackFeedbackView):
            return
        await view.handle_selection(interaction, self.values[0])


_SHORT_DESC: dict[str, str] = {
    "timing":    "CC non géré, héros absents, timing raté",
    "funnel":    "Armée mal orientée, flancs pas ouverts",
    "execution": "Sorts mal placés, mauvais drop de troupes",
    "other":     "Autre cause ou combinaison",
    "false_pos": "L'attaque était en réalité correcte",
}


class AttackFeedbackView(discord.ui.View):
    """Menu déroulant envoyé avec chaque DM ATTACK_LOW_GAIN.

    Expire après 24h. La sélection est persistée dans `attack_feedback`
    et agrégée dans le recap du lundi matin.
    """

    def __init__(
        self,
        repo: Repository,
        player_tag: str,
        discord_user_id: int,
        trophies_gained: int,
        n_attacks: int,
    ) -> None:
        super().__init__(timeout=86_400.0)  # 24h
        self._repo = repo
        self._player_tag = player_tag
        self._discord_user_id = discord_user_id
        self._trophies_gained = trophies_gained
        self._n_attacks = n_attacks
        self._answered = False
        self.add_item(_FeedbackSelect())

    async def handle_selection(
        self, interaction: discord.Interaction, value: str,
    ) -> None:
        if self._answered:
            await interaction.response.send_message(
                "Tu as déjà répondu à cette attaque.", ephemeral=True
            )
            return
        self._answered = True

        msg_id = interaction.message.id if interaction.message else None
        await self._repo.insert_attack_feedback(
            player_tag=self._player_tag,
            discord_user_id=self._discord_user_id,
            trophies_gained=self._trophies_gained,
            n_attacks=self._n_attacks,
            feedback=value,
            discord_message_id=msg_id,
        )

        # Find label + emoji for the selected value
        label, emoji = next(
            ((lbl, emo) for lbl, emo, val in FEEDBACK_CHOICES if val == value),
            ("Feedback", "📝"),
        )
        embed = discord.Embed(
            title=f"{emoji} Noté — {label}",
            description="Feedback enregistré. Résumé chaque lundi matin 📊",
            color=0x2ECC71 if value == "false_pos" else 0x95A5A6,
        )
        self.stop()
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=embed, ephemeral=False)

    async def on_timeout(self) -> None:
        """Désactive le select quand le timeout expire."""
        if not self._answered:
            for item in self.children:
                if isinstance(item, discord.ui.Select):
                    item.disabled = True


class AttackFeedbackCog(commands.Cog):
    """Cog requis pour enregistrer les vues persistantes au démarrage du bot.

    `bot.add_view()` est appelé ici pour chaque vue active (vues dont le
    timeout n'a pas expiré). En pratique, les AttackFeedbackView sont
    éphémères (24h) et recréées à chaque DM — pas de persistance entre
    redémarrages nécessaire pour ce cas d'usage.
    """

    def __init__(self, bot: commands.Bot, repo: Repository) -> None:
        self.bot = bot
        self._repo = repo
