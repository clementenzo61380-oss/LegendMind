"""Écriture / append d'un classeur Excel pour l'export quotidien Légende."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook

from services.legend_day_export import LegendDayStats

_HEADERS: tuple[str, ...] = (
    "Jour fin (UTC)",
    "Tag",
    "Nom",
    "Attaques",
    "Défenses",
    "Attaques - Défenses",
    "Trophées net",
    "Trophées fin journée",
)


def append_legend_day_rows(path: Path, rows: list[LegendDayStats]) -> None:
    """Ajoute une ligne par stats ; crée le fichier et les en-têtes si besoin."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        wb = load_workbook(path)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.append(list(_HEADERS))

    for r in rows:
        ws.append(
            [
                r.legend_day_end_utc.isoformat(),
                r.player_tag,
                r.player_name or "",
                r.attacks,
                r.defenses,
                r.net_battles,
                r.net_trophies,
                r.trophies_end,
            ],
        )
    wb.save(path)
