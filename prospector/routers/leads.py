import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from database.db import get_db, rows_to_list, row_to_dict
from services.scoring import score_lead

router = APIRouter()


class LeadCreate(BaseModel):
    source: str = "manual"
    raw_text: Optional[str] = None
    type_travaux: Optional[str] = None
    budget_estime: Optional[float] = 0
    localisation: Optional[str] = "Rennes"
    urgence: Optional[int] = 3
    contact_nom: Optional[str] = None
    contact_tel: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    montant_chantier_estime: Optional[float] = 0


class LeadUpdate(BaseModel):
    type_travaux: Optional[str] = None
    budget_estime: Optional[float] = None
    localisation: Optional[str] = None
    urgence: Optional[int] = None
    contact_nom: Optional[str] = None
    contact_tel: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    statut: Optional[str] = None
    artisan_id: Optional[int] = None
    montant_chantier_estime: Optional[float] = None
    commission_attendue: Optional[float] = None


class ExtractRequest(BaseModel):
    text: str


class OpenDataRequest(BaseModel):
    commune: str = "Rennes"
    code_dept: str = "35"
    limit: int = 20


@router.get("/")
def list_leads(
    statut: Optional[str] = None,
    source: Optional[str] = None,
    score_min: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
):
    with get_db() as db:
        where = ["1=1"]
        params = []
        if statut:
            where.append("l.statut = ?")
            params.append(statut)
        if source:
            where.append("l.source = ?")
            params.append(source)
        if score_min is not None:
            where.append("l.score >= ?")
            params.append(score_min)

        where_sql = " AND ".join(where)
        query = f"""
            SELECT l.*, a.nom as artisan_nom
            FROM leads l
            LEFT JOIN artisans a ON l.artisan_id = a.id
            WHERE {where_sql}
            ORDER BY l.score DESC, l.created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        leads = rows_to_list(db.execute(query, params).fetchall())

        count_params = [p for p in params[:-2]]
        total = db.execute(
            f"SELECT COUNT(*) FROM leads l WHERE {where_sql}", count_params
        ).fetchone()[0]

    return {"leads": leads, "total": total}


@router.post("/")
def create_lead(lead: LeadCreate):
    data = lead.model_dump()
    data["score"] = score_lead(data)

    # Calcul commission attendue si montant connu
    montant = data.get("montant_chantier_estime") or 0
    if montant > 0 and not data.get("commission_attendue"):
        import os
        taux = float(os.getenv("COMMISSION_DEFAUT", "5.0"))
        data["commission_attendue"] = montant * taux / 100

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO leads
               (source, raw_text, type_travaux, budget_estime, localisation,
                urgence, contact_nom, contact_tel, contact_email, notes, score,
                montant_chantier_estime, commission_attendue)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                data["source"], data.get("raw_text"), data.get("type_travaux"),
                data.get("budget_estime", 0), data.get("localisation", "Rennes"),
                data.get("urgence", 3), data.get("contact_nom"), data.get("contact_tel"),
                data.get("contact_email"), data.get("notes"), data["score"],
                data.get("montant_chantier_estime", 0), data.get("commission_attendue", 0),
            ],
        )
        new_lead = row_to_dict(db.execute("SELECT * FROM leads WHERE id=?", [cur.lastrowid]).fetchone())
    return new_lead


@router.get("/stats-by-status")
def leads_by_status():
    with get_db() as db:
        rows = db.execute(
            "SELECT statut, COUNT(*) as count FROM leads GROUP BY statut"
        ).fetchall()
    return {row["statut"]: row["count"] for row in rows}


@router.get("/{lead_id}")
def get_lead(lead_id: int):
    with get_db() as db:
        lead = row_to_dict(
            db.execute(
                "SELECT l.*, a.nom as artisan_nom FROM leads l LEFT JOIN artisans a ON l.artisan_id=a.id WHERE l.id=?",
                [lead_id],
            ).fetchone()
        )
    if not lead:
        raise HTTPException(404, "Lead non trouvé")
    return lead


@router.put("/{lead_id}")
def update_lead(lead_id: int, update: LeadUpdate):
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "Aucune donnée à mettre à jour")

    data["updated_at"] = datetime.datetime.now().isoformat()

    with get_db() as db:
        existing = row_to_dict(db.execute("SELECT * FROM leads WHERE id=?", [lead_id]).fetchone())
        if not existing:
            raise HTTPException(404, "Lead non trouvé")

        merged = {**existing, **data}
        data["score"] = score_lead(merged)

        # Recalculer commission si le montant a changé
        if "montant_chantier_estime" in data and "commission_attendue" not in data:
            montant = data["montant_chantier_estime"]
            if montant > 0:
                import os
                taux = float(os.getenv("COMMISSION_DEFAUT", "5.0"))
                data["commission_attendue"] = montant * taux / 100

        # Gérer l'affectation artisan + mise à jour commission_attendue selon son taux
        if "artisan_id" in data and data["artisan_id"]:
            artisan = row_to_dict(db.execute("SELECT taux_commission FROM artisans WHERE id=?", [data["artisan_id"]]).fetchone())
            if artisan:
                montant = data.get("montant_chantier_estime") or existing.get("montant_chantier_estime") or 0
                if montant > 0:
                    data["commission_attendue"] = montant * artisan["taux_commission"] / 100

        set_clause = ", ".join([f"{k}=?" for k in data])
        db.execute(f"UPDATE leads SET {set_clause} WHERE id=?", list(data.values()) + [lead_id])
        updated = row_to_dict(db.execute("SELECT * FROM leads WHERE id=?", [lead_id]).fetchone())
    return updated


@router.delete("/{lead_id}")
def delete_lead(lead_id: int):
    with get_db() as db:
        if not db.execute("SELECT id FROM leads WHERE id=?", [lead_id]).fetchone():
            raise HTTPException(404, "Lead non trouvé")
        db.execute("DELETE FROM leads WHERE id=?", [lead_id])
    return {"message": "Lead supprimé"}


@router.post("/extract")
async def extract_lead(req: ExtractRequest):
    """Extraction IA depuis un texte collé (post FB, annonce, conversation)."""
    from services.ai_service import extract_lead_from_text
    return await extract_lead_from_text(req.text)


@router.post("/open-data/fetch")
async def fetch_open_data(req: OpenDataRequest):
    """Récupère les permis de construire depuis data.gouv.fr / Sitadel."""
    from services.open_data import fetch_permis_construire
    return await fetch_permis_construire(req.commune, req.code_dept, req.limit)


@router.post("/open-data/import")
async def import_open_data(req: OpenDataRequest):
    """Récupère les permis ET les importe directement comme leads."""
    from services.open_data import fetch_permis_construire
    result = await fetch_permis_construire(req.commune, req.code_dept, req.limit)

    imported = []
    with get_db() as db:
        for lead_data in result.get("leads", []):
            lead_data["score"] = score_lead(lead_data)
            cur = db.execute(
                """INSERT INTO leads
                   (source, raw_text, type_travaux, budget_estime, localisation,
                    urgence, notes, score)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    lead_data.get("source", "open_data"),
                    lead_data.get("raw_text"),
                    lead_data.get("type_travaux"),
                    lead_data.get("budget_estime", 0),
                    lead_data.get("localisation", "Rennes"),
                    lead_data.get("urgence", 3),
                    lead_data.get("notes"),
                    lead_data["score"],
                ],
            )
            imported.append(cur.lastrowid)

    return {
        "imported": len(imported),
        "lead_ids": imported,
        "source_info": result.get("errors", []),
    }


@router.get("/auto-prospect/status")
def auto_prospect_status():
    """Statut du moteur d'auto-prospection (dernier passage, prochains, total importé)."""
    from services.auto_prospect import STATUS
    return STATUS


@router.post("/auto-prospect/run")
async def auto_prospect_run():
    """Déclenche immédiatement un passage d'auto-prospection."""
    from services.auto_prospect import run_auto_prospect, STATUS
    if STATUS["running"]:
        return {"message": "Un passage est déjà en cours", "status": STATUS}
    result = await run_auto_prospect()
    return {"message": "Passage terminé", "result": result}


@router.get("/{lead_id}/suggest-artisan")
async def suggest_artisan_for_lead(lead_id: int):
    """Suggère les meilleurs artisans pour un lead donné via IA."""
    from services.ai_service import suggest_artisan
    with get_db() as db:
        lead = row_to_dict(db.execute("SELECT * FROM leads WHERE id=?", [lead_id]).fetchone())
        if not lead:
            raise HTTPException(404, "Lead non trouvé")
        artisans = rows_to_list(db.execute("SELECT * FROM artisans").fetchall())
    return await suggest_artisan(lead, artisans)
