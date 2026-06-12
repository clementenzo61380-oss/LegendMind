import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

from database.db import get_db, rows_to_list, row_to_dict

router = APIRouter()


class ContractStatusUpdate(BaseModel):
    statut: str  # brouillon / envoye / signe
    date_signature: Optional[str] = None
    notes: Optional[str] = None


@router.get("/")
def list_contracts():
    with get_db() as db:
        contracts = rows_to_list(
            db.execute(
                """SELECT c.*, a.nom as artisan_nom, a.metier as artisan_metier, a.taux_commission
                   FROM contracts c
                   JOIN artisans a ON c.artisan_id = a.id
                   ORDER BY c.date_creation DESC"""
            ).fetchall()
        )
    return {"contracts": contracts, "total": len(contracts)}


@router.post("/{artisan_id}/generate")
def generate_contract(artisan_id: int, taux_commission: Optional[float] = None):
    """Génère un contrat .docx ET .pdf pour un artisan."""
    from services.document_generator import generate_docx, generate_pdf

    with get_db() as db:
        artisan = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [artisan_id]).fetchone())
    if not artisan:
        raise HTTPException(404, "Artisan non trouvé")

    taux = taux_commission or artisan.get("taux_commission", 5.0)

    errors = []
    docx_path = None
    pdf_path = None

    try:
        docx_path = generate_docx(artisan, taux)
    except Exception as e:
        errors.append(f"DOCX : {str(e)}")

    try:
        pdf_path = generate_pdf(artisan, taux)
    except Exception as e:
        errors.append(f"PDF : {str(e)}")

    if not docx_path and not pdf_path:
        raise HTTPException(500, f"Erreur génération : {'; '.join(errors)}")

    # Enregistrer en base
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO contracts (artisan_id, statut, fichier_docx, fichier_pdf)
               VALUES (?,?,?,?)""",
            [
                artisan_id,
                "brouillon",
                str(docx_path) if docx_path else None,
                str(pdf_path) if pdf_path else None,
            ],
        )
        contract_id = cur.lastrowid
        contract = row_to_dict(db.execute("SELECT * FROM contracts WHERE id=?", [contract_id]).fetchone())

    return {
        "contract": contract,
        "docx_url": f"/generated_docs/{docx_path.name}" if docx_path else None,
        "pdf_url": f"/generated_docs/{pdf_path.name}" if pdf_path else None,
        "warnings": errors,
        "disclaimer": "⚠️ MODÈLE À FAIRE VALIDER PAR UN PROFESSIONNEL DU DROIT",
    }


@router.get("/{contract_id}")
def get_contract(contract_id: int):
    with get_db() as db:
        contract = row_to_dict(
            db.execute(
                "SELECT c.*, a.nom as artisan_nom FROM contracts c JOIN artisans a ON c.artisan_id=a.id WHERE c.id=?",
                [contract_id],
            ).fetchone()
        )
    if not contract:
        raise HTTPException(404, "Contrat non trouvé")
    return contract


@router.put("/{contract_id}/status")
def update_contract_status(contract_id: int, update: ContractStatusUpdate):
    valid_statuts = ["brouillon", "envoye", "signe"]
    if update.statut not in valid_statuts:
        raise HTTPException(400, f"Statut invalide. Valeurs : {valid_statuts}")

    with get_db() as db:
        contract = db.execute("SELECT id FROM contracts WHERE id=?", [contract_id]).fetchone()
        if not contract:
            raise HTTPException(404, "Contrat non trouvé")

        fields = {"statut": update.statut}
        if update.date_signature:
            fields["date_signature"] = update.date_signature
        elif update.statut == "signe" and not update.date_signature:
            fields["date_signature"] = datetime.date.today().isoformat()
        if update.notes:
            fields["notes"] = update.notes

        set_clause = ", ".join([f"{k}=?" for k in fields])
        db.execute(f"UPDATE contracts SET {set_clause} WHERE id=?", list(fields.values()) + [contract_id])

        # Si signé, marquer l'artisan contrat_signe = 1
        if update.statut == "signe":
            row = db.execute("SELECT artisan_id FROM contracts WHERE id=?", [contract_id]).fetchone()
            if row:
                db.execute(
                    "UPDATE artisans SET contrat_signe=1, updated_at=? WHERE id=?",
                    [datetime.datetime.now().isoformat(), row["artisan_id"]],
                )

        updated = row_to_dict(db.execute("SELECT * FROM contracts WHERE id=?", [contract_id]).fetchone())
    return updated


@router.delete("/{contract_id}")
def delete_contract(contract_id: int):
    with get_db() as db:
        contract = row_to_dict(db.execute("SELECT * FROM contracts WHERE id=?", [contract_id]).fetchone())
        if not contract:
            raise HTTPException(404, "Contrat non trouvé")

        # Supprimer les fichiers
        for field in ["fichier_docx", "fichier_pdf"]:
            f = contract.get(field)
            if f:
                p = Path(f)
                if p.exists():
                    p.unlink()

        db.execute("DELETE FROM contracts WHERE id=?", [contract_id])
    return {"message": "Contrat supprimé"}
