"""SeasonService — façade haut niveau au-dessus de ``Repository`` (prompt §7).

Garde la responsabilité unique « cycle saisonnier » :

* `get_current_season()` — saison ouverte (ou en crée une).
* `close_season()` — fige le classement de chaque guild puis ouvre la suivante.
* `get_player_history()` — vue historique pour `/historique`.

Aucune écriture SQL ici : tout passe par `Repository`. Cela évite la
duplication et garantit que les migrations restent une seule source de vérité.
"""

from __future__ import annotations

import logging

from models import SeasonHistoryEntry, SeasonRecord
from services.db import Repository

log = logging.getLogger(__name__)


class SeasonService:
    """Gère le cycle saisonnier (ouvert / clôturé)."""

    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    async def get_current_season(self) -> SeasonRecord:
        """Retourne la saison ouverte ; en crée une si aucune n'est ouverte."""
        active = await self._repo.get_active_season()
        if active is not None:
            return active
        return await self._repo.ensure_active_season()

    async def close_season(self) -> tuple[int, int]:
        """Clôture la saison ouverte et en ouvre une nouvelle.

        Returns:
            Tuple ``(closed_season_id, new_season_id)``.
        """
        return await self._repo.close_season()

    async def get_player_history(
        self,
        player_tag: str,
        limit: int = 12,
    ) -> list[SeasonHistoryEntry]:
        """Historique récent (par défaut 12 saisons) du joueur."""
        return await self._repo.list_player_season_history(player_tag, limit=limit)
