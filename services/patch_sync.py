"""Synchronisation périodique du tuning jeu depuis une URL JSON (dérivée des patch notes)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import discord

from services.game_tuning import apply_tuning_patch, get_tuning

if TYPE_CHECKING:
    from cogs.tracker import LegendPoller

log = logging.getLogger(__name__)


class PatchNotesSyncService:
    """Fetch ``GAME_TUNING_URL`` et applique ``apply_tuning_patch``.

    Si les intervalles de polling changent, met à jour ``LegendPoller``.
    """

    def __init__(
        self,
        *,
        url: str | None,
        poll_interval_seconds: int,
        bot: discord.Client,
        poller: LegendPoller | None = None,
    ) -> None:
        self._bot = bot
        self._url = url.strip() if url else None
        self._poll_interval = max(300, poll_interval_seconds)
        self._poller = poller
        self._etag: str | None = None

    def attach_poller(self, poller: LegendPoller) -> None:
        self._poller = poller

    async def run_forever(self) -> None:
        if not self._url:
            log.info(
                "patch_sync: GAME_TUNING_URL absent — tuning 100%% embarqué "
                "(constants + game_tuning par défaut).",
            )
            return
        await self._bot.wait_until_ready()
        log.info(
            "patch_sync: boucle démarrée (intervalle %ds, url=%s)",
            self._poll_interval,
            self._url[:80] + ("…" if len(self._url) > 80 else ""),
        )
        while True:
            try:
                await self._fetch_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("patch_sync: fetch ou apply a échoué")
            await asyncio.sleep(self._poll_interval)

    async def _fetch_once(self) -> None:
        assert self._url is not None
        timeout = aiohttp.ClientTimeout(total=45)
        req_headers: dict[str, str] = {}
        if self._etag:
            req_headers["If-None-Match"] = self._etag
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self._url, headers=req_headers) as resp:
                if resp.status == 304:
                    log.debug("patch_sync: 304 Not Modified")
                    return
                resp.raise_for_status()
                new_etag = resp.headers.get("ETag")
                if new_etag:
                    self._etag = new_etag
                data: Any = await resp.json(content_type=None)
        if not isinstance(data, dict):
            log.warning("patch_sync: JSON racine doit être un objet, reçu %s", type(data))
            return
        old = get_tuning()
        ok, msg = apply_tuning_patch(data)
        if not ok:
            log.debug("patch_sync: %s", msg)
            return
        log.debug("patch_sync: %s", msg)
        new = get_tuning()
        if self._poller is not None and (
            new.poll_interval_legend_i_seconds != old.poll_interval_legend_i_seconds
            or new.poll_interval_legend_ii_iii_seconds != old.poll_interval_legend_ii_iii_seconds
        ):
            self._poller.apply_tuning_poll_intervals()
