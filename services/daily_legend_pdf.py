"""Export PDF cumulatif des stats Légende (une section par joueur, table journalière)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services.legend_day_export import LegendDayStats

_HEADERS: tuple[str, ...] = (
    "Jour fin (UTC)",
    "Attaques",
    "Défenses",
    "ATK TR",
    "DEF TR",
    "+/- TR",
    "INIT TR",
    "FINAL TR",
)


def _row_to_json(r: LegendDayStats) -> dict[str, object]:
    return {
        "player_tag": r.player_tag,
        "player_name": r.player_name,
        "legend_day_end_utc": r.legend_day_end_utc.isoformat(),
        "attacks": r.attacks,
        "defenses": r.defenses,
        "net_battles": r.net_battles,
        "trophies_attack": r.trophies_attack,
        "trophies_defense": r.trophies_defense,
        "net_trophies": r.net_trophies,
        "trophies_start": r.trophies_start,
        "trophies_end": r.trophies_end,
    }


def _row_from_json(d: dict[str, object]) -> LegendDayStats:
    end_raw = d["legend_day_end_utc"]
    if isinstance(end_raw, str):
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
    else:
        raise ValueError("legend_day_end_utc must be str")
    return LegendDayStats(
        player_tag=str(d["player_tag"]),
        player_name=(str(d["player_name"]) if d.get("player_name") is not None else None),
        legend_day_end_utc=end,
        attacks=int(d["attacks"]),
        defenses=int(d["defenses"]),
        net_battles=int(d["net_battles"]),
        trophies_attack=int(d["trophies_attack"]),
        trophies_defense=int(d["trophies_defense"]),
        net_trophies=int(d["net_trophies"]),
        trophies_start=int(d["trophies_start"]),
        trophies_end=int(d["trophies_end"]),
    )


def _append_history(path: Path, rows: list[LegendDayStats]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(_row_to_json(r), ensure_ascii=False) + "\n")


def _load_history(path: Path) -> list[LegendDayStats]:
    if not path.is_file():
        return []
    out: list[LegendDayStats] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(_row_from_json(json.loads(line)))
    return out


def _dedupe(rows: list[LegendDayStats]) -> list[LegendDayStats]:
    by_key: dict[tuple[str, str], LegendDayStats] = {}
    for r in rows:
        k = (r.player_tag, r.legend_day_end_utc.isoformat())
        by_key[k] = r
    return list(by_key.values())


def _group_by_player(rows: list[LegendDayStats]) -> dict[str, list[LegendDayStats]]:
    d: dict[str, list[LegendDayStats]] = defaultdict(list)
    for r in rows:
        d[r.player_tag].append(r)
    for tag in d:
        d[tag].sort(key=lambda x: x.legend_day_end_utc)
    return dict(sorted(d.items()))


def _build_pdf(pdf_path: Path, grouped: dict[str, list[LegendDayStats]]) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    styles = getSampleStyleSheet()
    story: list = [
        Paragraph("LegendMind — Export Légende (cumul)", styles["Title"]),
        Spacer(1, 4 * mm),
        Paragraph(
            "Une ligne par journée de reset Légende (UTC).",
            styles["Normal"],
        ),
        Spacer(1, 8 * mm),
    ]

    for _tag, prow in grouped.items():
        name = escape(prow[0].player_name or "—")
        tag_esc = escape(prow[0].player_tag)
        story.append(Paragraph(f"{name} — <b>{tag_esc}</b>", styles["Heading2"]))
        story.append(Spacer(1, 2 * mm))

        data: list[list[str | int]] = [list(_HEADERS)]
        for r in prow:
            data.append(
                [
                    r.legend_day_end_utc.strftime("%Y-%m-%d %H:%M"),
                    r.attacks,
                    r.defenses,
                    r.trophies_attack,
                    r.trophies_defense,
                    r.net_trophies,
                    r.trophies_start,
                    r.trophies_end,
                ],
            )
        col_widths = [32 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm, 14 * mm]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                ],
            ),
        )
        story.append(t)
        story.append(Spacer(1, 10 * mm))

    doc.build(story)


def append_legend_day_rows_pdf(
    pdf_path: Path,
    history_path: Path,
    rows: list[LegendDayStats],
) -> None:
    """Ajoute les lignes à l'historique JSONL et régénère le PDF complet."""
    if not rows:
        return
    _append_history(history_path, rows)
    all_rows = _dedupe(_load_history(history_path))
    grouped = _group_by_player(all_rows)
    _build_pdf(pdf_path, grouped)
