import datetime
import csv
import io
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from database.db import get_db, rows_to_list, row_to_dict
from services.scoring import score_artisan

router = APIRouter()


class ArtisanCreate(BaseModel):
    nom: str
    metier: Optional[str] = None
    ville: Optional[str] = "Rennes"
    siren: Optional[str] = None
    telephone: Optional[str] = None
    email: Optional[str] = None
    forme_juridique: Optional[str] = None
    date_creation: Optional[str] = None
    effectif: Optional[int] = 0
    taux_commission: Optional[float] = None
    notes: Optional[str] = None


class ArtisanUpdate(BaseModel):
    nom: Optional[str] = None
    metier: Optional[str] = None
    ville: Optional[str] = None
    siren: Optional[str] = None
    telephone: Optional[str] = None
    email: Optional[str] = None
    forme_juridique: Optional[str] = None
    date_creation: Optional[str] = None
    effectif: Optional[int] = None
    taux_commission: Optional[float] = None
    contrat_signe: Optional[bool] = None
    historique_paiement: Optional[str] = None
    notes: Optional[str] = None


class MessageRequest(BaseModel):
    type_message: str = "email"  # 'email' ou 'sms'


@router.get("/")
def list_artisans(
    contrat_signe: Optional[bool] = None,
    metier: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    with get_db() as db:
        where = ["1=1"]
        params = []
        if contrat_signe is not None:
            where.append("contrat_signe = ?")
            params.append(1 if contrat_signe else 0)
        if metier:
            where.append("LOWER(metier) LIKE ?")
            params.append(f"%{metier.lower()}%")

        where_sql = " AND ".join(where)
        query = f"""
            SELECT a.*,
                   COUNT(DISTINCT l.id) as nb_leads,
                   COUNT(DISTINCT c.id) as nb_contrats,
                   COALESCE(SUM(cm.montant), 0) as ca_total
            FROM artisans a
            LEFT JOIN leads l ON l.artisan_id = a.id
            LEFT JOIN contracts c ON c.artisan_id = a.id
            LEFT JOIN commissions cm ON cm.artisan_id = a.id AND cm.statut = 'payee'
            WHERE {where_sql}
            GROUP BY a.id
            ORDER BY a.score_fiabilite DESC, a.nom ASC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        artisans = rows_to_list(db.execute(query, params).fetchall())
        total = db.execute(f"SELECT COUNT(*) FROM artisans WHERE {where_sql}", params[:-2]).fetchone()[0]

    return {"artisans": artisans, "total": total}


@router.post("/")
def create_artisan(artisan: ArtisanCreate):
    import os
    data = artisan.model_dump()
    if data.get("taux_commission") is None:
        data["taux_commission"] = float(os.getenv("COMMISSION_DEFAUT", "5.0"))
    data["score_fiabilite"] = score_artisan(data)

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO artisans
               (nom, metier, ville, siren, telephone, email, forme_juridique,
                date_creation, effectif, taux_commission, score_fiabilite, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                data["nom"], data.get("metier"), data.get("ville", "Rennes"),
                data.get("siren"), data.get("telephone"), data.get("email"),
                data.get("forme_juridique"), data.get("date_creation"),
                data.get("effectif", 0), data["taux_commission"],
                data["score_fiabilite"], data.get("notes"),
            ],
        )
        new = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [cur.lastrowid]).fetchone())
    return new


@router.get("/{artisan_id}")
def get_artisan(artisan_id: int):
    with get_db() as db:
        artisan = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [artisan_id]).fetchone())
    if not artisan:
        raise HTTPException(404, "Artisan non trouvé")
    return artisan


@router.put("/{artisan_id}")
def update_artisan(artisan_id: int, update: ArtisanUpdate):
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(400, "Aucune donnée à mettre à jour")

    data["updated_at"] = datetime.datetime.now().isoformat()

    # Convertir bool → int pour SQLite
    if "contrat_signe" in data:
        data["contrat_signe"] = 1 if data["contrat_signe"] else 0

    with get_db() as db:
        existing = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [artisan_id]).fetchone())
        if not existing:
            raise HTTPException(404, "Artisan non trouvé")

        merged = {**existing, **data}
        data["score_fiabilite"] = score_artisan(merged)

        set_clause = ", ".join([f"{k}=?" for k in data])
        db.execute(f"UPDATE artisans SET {set_clause} WHERE id=?", list(data.values()) + [artisan_id])
        updated = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [artisan_id]).fetchone())
    return updated


@router.delete("/{artisan_id}")
def delete_artisan(artisan_id: int):
    with get_db() as db:
        if not db.execute("SELECT id FROM artisans WHERE id=?", [artisan_id]).fetchone():
            raise HTTPException(404, "Artisan non trouvé")
        db.execute("DELETE FROM artisans WHERE id=?", [artisan_id])
    return {"message": "Artisan supprimé"}


@router.post("/{artisan_id}/enrich")
async def enrich_artisan(artisan_id: int):
    """Enrichit la fiche via l'API Sirene (INSEE)."""
    from services.sirene import enrich_from_siren
    with get_db() as db:
        artisan = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [artisan_id]).fetchone())
    if not artisan:
        raise HTTPException(404, "Artisan non trouvé")
    if not artisan.get("siren"):
        raise HTTPException(400, "SIREN non renseigné pour cet artisan")

    enriched = await enrich_from_siren(artisan["siren"])
    if "error" in enriched:
        return {"success": False, "error": enriched["error"]}

    # Mettre à jour en base
    update_data = {}
    if enriched.get("forme_juridique") and not artisan.get("forme_juridique"):
        update_data["forme_juridique"] = enriched["forme_juridique"]
    if enriched.get("date_creation") and not artisan.get("date_creation"):
        update_data["date_creation"] = enriched["date_creation"]
    if enriched.get("effectif") and not artisan.get("effectif"):
        update_data["effectif"] = enriched["effectif"]
    if enriched.get("ville") and not artisan.get("ville"):
        update_data["ville"] = enriched["ville"]

    if update_data:
        update_data["updated_at"] = datetime.datetime.now().isoformat()
        merged = {**artisan, **update_data}
        update_data["score_fiabilite"] = score_artisan(merged)
        set_clause = ", ".join([f"{k}=?" for k in update_data])
        with get_db() as db:
            db.execute(f"UPDATE artisans SET {set_clause} WHERE id=?", list(update_data.values()) + [artisan_id])

    return {"success": True, "enriched_data": enriched, "fields_updated": list(update_data.keys())}


@router.post("/{artisan_id}/generate-message")
async def generate_message(artisan_id: int, req: MessageRequest):
    """Génère un message d'approche personnalisé (DRAFT — jamais envoyé auto)."""
    from services.ai_service import generate_artisan_message
    with get_db() as db:
        artisan = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [artisan_id]).fetchone())
    if not artisan:
        raise HTTPException(404, "Artisan non trouvé")

    result = await generate_artisan_message(artisan, req.type_message)

    # Sauvegarder le draft
    if result.get("success"):
        with get_db() as db:
            db.execute(
                "INSERT INTO ai_drafts (type, reference_id, reference_type, contenu) VALUES (?,?,?,?)",
                [f"message_{req.type_message}", artisan_id, "artisan", result["contenu"]],
            )

    return result


@router.get("/{artisan_id}/drafts")
def get_artisan_drafts(artisan_id: int):
    """Récupère les drafts IA générés pour un artisan."""
    with get_db() as db:
        drafts = rows_to_list(
            db.execute(
                "SELECT * FROM ai_drafts WHERE reference_id=? AND reference_type='artisan' ORDER BY created_at DESC LIMIT 20",
                [artisan_id],
            ).fetchall()
        )
    return {"drafts": drafts}


@router.post("/import-csv")
async def import_csv(file: UploadFile = File(...)):
    """
    Import CSV artisans.
    Colonnes attendues : nom, metier, ville, siren, telephone, email
    (ordre flexible, en-tête requis)
    """
    import os
    content = await file.read()
    text = content.decode("utf-8-sig")  # BOM-safe
    reader = csv.DictReader(io.StringIO(text))

    imported = []
    errors = []
    taux_defaut = float(os.getenv("COMMISSION_DEFAUT", "5.0"))

    with get_db() as db:
        for i, row in enumerate(reader, start=2):
            nom = row.get("nom", "").strip() or row.get("Nom", "").strip()
            if not nom:
                errors.append(f"Ligne {i}: nom manquant — ignoré")
                continue

            data = {
                "nom": nom,
                "metier": row.get("metier", row.get("Metier", row.get("métier", ""))).strip() or None,
                "ville": row.get("ville", row.get("Ville", "Rennes")).strip() or "Rennes",
                "siren": row.get("siren", row.get("SIREN", "")).strip() or None,
                "telephone": row.get("telephone", row.get("tel", row.get("Telephone", ""))).strip() or None,
                "email": row.get("email", row.get("Email", "")).strip() or None,
            }
            data["score_fiabilite"] = score_artisan(data)
            data["taux_commission"] = taux_defaut

            try:
                cur = db.execute(
                    """INSERT INTO artisans (nom, metier, ville, siren, telephone, email, taux_commission, score_fiabilite)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [data["nom"], data["metier"], data["ville"], data["siren"],
                     data["telephone"], data["email"], data["taux_commission"], data["score_fiabilite"]],
                )
                imported.append({"id": cur.lastrowid, "nom": nom})
            except Exception as e:
                errors.append(f"Ligne {i} ({nom}): {str(e)}")

    return {
        "imported": len(imported),
        "errors": errors,
        "artisans": imported,
    }
