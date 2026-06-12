"""
Moteur d'auto-prospection — tâche de fond.

Toutes les N heures (configurable dans .env) :
1. Interroge l'open data Sitadel (permis de construire, Rennes Métropole)
2. Déduplique contre les leads déjà en base
3. Importe les nouveaux leads avec scoring automatique
4. Auto-qualifie les leads dont le score dépasse le seuil configuré

⚠️ Périmètre légal : uniquement des sources open data publiques.
   Aucun scraping de sites privés, aucun envoi automatique de message.
"""
import os
import asyncio
import logging
from datetime import datetime

from database.db import get_db
from services.scoring import score_lead
from services.open_data import fetch_permis_construire

logger = logging.getLogger("auto_prospect")

# Statut en mémoire, exposé via l'API (app locale mono-utilisateur)
STATUS = {
    "enabled": False,
    "running": False,
    "last_run": None,
    "last_result": None,
    "next_run": None,
    "total_imported": 0,
    "runs": [],  # historique des 20 derniers passages
}


def _config():
    return {
        "enabled": os.getenv("AUTO_PROSPECT_ENABLED", "true").lower() in ("1", "true", "oui"),
        "interval_hours": float(os.getenv("AUTO_PROSPECT_INTERVAL_HOURS", "6")),
        "commune": os.getenv("AUTO_PROSPECT_COMMUNE", "Rennes"),
        "dept": os.getenv("AUTO_PROSPECT_DEPT", "35"),
        "limit": int(os.getenv("AUTO_PROSPECT_LIMIT", "30")),
        "auto_qualify_score": int(os.getenv("AUTO_QUALIFY_SCORE", "70")),
    }


async def run_auto_prospect() -> dict:
    """Un passage complet de prospection : fetch → dédup → import → qualif."""
    cfg = _config()
    STATUS["running"] = True
    result = {
        "started_at": datetime.now().isoformat(),
        "fetched": 0,
        "imported": 0,
        "duplicates": 0,
        "auto_qualified": 0,
        "errors": [],
    }

    try:
        data = await fetch_permis_construire(cfg["commune"], cfg["dept"], cfg["limit"])
        leads = data.get("leads", [])
        result["fetched"] = len(leads)
        result["errors"].extend(data.get("errors", []))

        with get_db() as db:
            for lead in leads:
                raw = lead.get("raw_text") or f"{lead.get('type_travaux')}|{lead.get('localisation')}|{lead.get('notes')}"

                # Déduplication : même raw_text déjà importé depuis l'open data
                exists = db.execute(
                    "SELECT id FROM leads WHERE raw_text = ? AND source LIKE 'open_data%'",
                    [raw],
                ).fetchone()
                if exists:
                    result["duplicates"] += 1
                    continue

                score = score_lead(lead)
                statut = "qualifie" if score >= cfg["auto_qualify_score"] else "nouveau"
                if statut == "qualifie":
                    result["auto_qualified"] += 1

                db.execute(
                    """INSERT INTO leads
                       (source, raw_text, type_travaux, budget_estime, localisation,
                        urgence, notes, score, statut)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    [
                        lead.get("source", "open_data"),
                        raw,
                        lead.get("type_travaux"),
                        lead.get("budget_estime", 0),
                        lead.get("localisation", "Rennes"),
                        lead.get("urgence", 3),
                        lead.get("notes"),
                        score,
                        statut,
                    ],
                )
                result["imported"] += 1

        STATUS["total_imported"] += result["imported"]

    except Exception as e:
        result["errors"].append(str(e))
        logger.exception("Erreur auto-prospection")
    finally:
        result["finished_at"] = datetime.now().isoformat()
        STATUS["running"] = False
        STATUS["last_run"] = result["finished_at"]
        STATUS["last_result"] = result
        STATUS["runs"] = ([result] + STATUS["runs"])[:20]

    logger.info(
        "Auto-prospection : %s récupérés, %s importés, %s doublons, %s auto-qualifiés",
        result["fetched"], result["imported"], result["duplicates"], result["auto_qualified"],
    )
    return result


async def auto_prospect_loop():
    """Boucle de fond lancée au démarrage de l'app (annulée à l'arrêt)."""
    cfg = _config()
    STATUS["enabled"] = cfg["enabled"]
    if not cfg["enabled"]:
        logger.info("Auto-prospection désactivée (AUTO_PROSPECT_ENABLED=false)")
        return

    # Premier passage 10 s après le démarrage, puis toutes les N heures
    await asyncio.sleep(10)
    while True:
        await run_auto_prospect()
        interval = _config()["interval_hours"] * 3600
        STATUS["next_run"] = datetime.fromtimestamp(
            datetime.now().timestamp() + interval
        ).isoformat()
        await asyncio.sleep(interval)
