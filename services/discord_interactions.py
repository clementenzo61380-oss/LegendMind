"""Helpers for Discord slash interactions (safe defer, etc.)."""

from __future__ import annotations

import logging

import discord

_log = logging.getLogger(__name__)


async def defer_ephemeral_safe(
    interaction: discord.Interaction,
    *,
    log_label: str,
) -> bool:
    """Defer ephemeral; return False if interaction already expired (10062)."""
    try:
        await interaction.response.defer(ephemeral=True)
        return True
    except (discord.NotFound, discord.HTTPException) as exc:
        _log.warning("%s defer failed: %r", log_label, exc)
        return False
