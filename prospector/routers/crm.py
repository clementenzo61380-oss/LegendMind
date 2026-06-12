import datetime
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from database.db import get_db, rows_to_list, row_to_dict

router = APIRouter()

DELAI_PAIEMENT = int(os.getenv("DELAI_PAIEMENT_JOURS", "30"))


class TransmissionCreate(BaseModel):
    lead_id: int
    artisan_id: int
    notes: Optional[str] = None


class CommissionCreate(BaseModel):
    lead_id: int
    artisan_id: int
    transmission_id: Optional[int] = None
    montant_chantier: float
    taux: Optional[float] = None
    date_echeance: Optional[str] = None
    notes: Optional[str] = None


class CommissionStatusUpdate(BaseModel):
    statut: str  # en_attente / payee / en_retard / contentieux
    notes: Optional[str] = None


# ─── TRANSMISSIONS ───────────────────────────────────────────────────────────

@router.get("/transmissions")
def list_transmissions(lead_id: Optional[int] = None, artisan_id: Optional[int] = None):
    with get_db() as db:
        where = ["1=1"]
        params = []
        if lead_id:
            where.append("t.lead_id = ?")
            params.append(lead_id)
        if artisan_id:
            where.append("t.artisan_id = ?")
            params.append(artisan_id)

        transmissions = rows_to_list(
            db.execute(
                f"""SELECT t.*,
                           l.type_travaux, l.contact_nom, l.localisation,
                           a.nom as artisan_nom, a.email as artisan_email
                    FROM transmissions t
                    JOIN leads l ON t.lead_id = l.id
                    JOIN artisans a ON t.artisan_id = a.id
                    WHERE {" AND ".join(where)}
                    ORDER BY t.date_transmission DESC""",
                params,
            ).fetchall()
        )
    return {"transmissions": transmissions, "total": len(transmissions)}


@router.post("/transmissions")
async def create_transmission(data: TransmissionCreate):
    """
    Crée une transmission et génère automatiquement le draft d'email horodaté.
    Met à jour le statut du lead à 'transmis'.
    ⚠️ L'email est un DRAFT — jamais envoyé automatiquement.
    """
    from services.ai_service import generate_transmission_email

    with get_db() as db:
        lead = row_to_dict(db.execute("SELECT * FROM leads WHERE id=?", [data.lead_id]).fetchone())
        if not lead:
            raise HTTPException(404, "Lead non trouvé")
        artisan = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [data.artisan_id]).fetchone())
        if not artisan:
            raise HTTPException(404, "Artisan non trouvé")

        # Récupérer la date du contrat signé si disponible
        contract = row_to_dict(
            db.execute(
                "SELECT date_signature FROM contracts WHERE artisan_id=? AND statut='signe' ORDER BY date_signature DESC LIMIT 1",
                [data.artisan_id],
            ).fetchone()
        )
        contrat_date = contract["date_signature"] if contract else ""

        apporteur_info = {
            "nom": os.getenv("APPORTEUR_NOM", "L'Apporteur"),
            "contrat_date": contrat_date,
        }

        # Générer le draft email
        email_result = await generate_transmission_email(lead, artisan, apporteur_info)
        email_draft = email_result.get("contenu", "") if email_result.get("success") else ""

        # Insérer la transmission
        cur = db.execute(
            "INSERT INTO transmissions (lead_id, artisan_id, email_draft, notes) VALUES (?,?,?,?)",
            [data.lead_id, data.artisan_id, email_draft, data.notes],
        )
        transmission_id = cur.lastrowid

        # Mettre à jour le lead : statut + artisan assigné
        db.execute(
            "UPDATE leads SET statut='transmis', artisan_id=?, updated_at=? WHERE id=?",
            [data.artisan_id, datetime.datetime.now().isoformat(), data.lead_id],
        )

        # Sauvegarder le draft en ai_drafts aussi
        db.execute(
            "INSERT INTO ai_drafts (type, reference_id, reference_type, contenu) VALUES (?,?,?,?)",
            ["email_transmission", transmission_id, "transmission", email_draft],
        )

        transmission = row_to_dict(
            db.execute("SELECT * FROM transmissions WHERE id=?", [transmission_id]).fetchone()
        )

    return {
        "transmission": transmission,
        "email_draft": email_draft,
        "email_subject": email_result.get("subject", ""),
        "email_to": artisan.get("email", ""),
        "warning": "⚠️ DRAFT uniquement — envoyez depuis votre client mail (ce mail constitue votre preuve de transmission).",
    }


@router.delete("/transmissions/{transmission_id}")
def delete_transmission(transmission_id: int):
    with get_db() as db:
        if not db.execute("SELECT id FROM transmissions WHERE id=?", [transmission_id]).fetchone():
            raise HTTPException(404, "Transmission non trouvée")
        db.execute("DELETE FROM transmissions WHERE id=?", [transmission_id])
    return {"message": "Transmission supprimée"}


# ─── COMMISSIONS ─────────────────────────────────────────────────────────────

@router.get("/commissions")
def list_commissions(statut: Optional[str] = None):
    with get_db() as db:
        where = ["1=1"]
        params = []
        if statut:
            where.append("cm.statut = ?")
            params.append(statut)

        commissions = rows_to_list(
            db.execute(
                f"""SELECT cm.*,
                           l.type_travaux, l.contact_nom, l.localisation,
                           a.nom as artisan_nom, a.email as artisan_email
                    FROM commissions cm
                    LEFT JOIN leads l ON cm.lead_id = l.id
                    LEFT JOIN artisans a ON cm.artisan_id = a.id
                    WHERE {" AND ".join(where)}
                    ORDER BY cm.date_echeance ASC""",
                params,
            ).fetchall()
        )

    # Marquer automatiquement en_retard si l'échéance est dépassée
    today = datetime.date.today().isoformat()
    for c in commissions:
        if c["statut"] == "en_attente" and c.get("date_echeance") and c["date_echeance"] < today:
            c["statut"] = "en_retard"

    return {"commissions": commissions, "total": len(commissions)}


@router.post("/commissions")
def create_commission(data: CommissionCreate):
    import os

    taux = data.taux or float(os.getenv("COMMISSION_DEFAUT", "5.0"))
    montant = data.montant_chantier * taux / 100

    if data.date_echeance:
        date_echeance = data.date_echeance
    else:
        date_echeance = (
            datetime.date.today() + datetime.timedelta(days=DELAI_PAIEMENT)
        ).isoformat()

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO commissions (lead_id, artisan_id, transmission_id, montant, taux, montant_chantier, date_echeance, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            [data.lead_id, data.artisan_id, data.transmission_id, montant, taux,
             data.montant_chantier, date_echeance, data.notes],
        )
        commission = row_to_dict(db.execute("SELECT * FROM commissions WHERE id=?", [cur.lastrowid]).fetchone())

        # Mettre à jour le lead
        db.execute(
            "UPDATE leads SET statut='devis_envoye', montant_chantier_estime=?, commission_attendue=?, updated_at=? WHERE id=?",
            [data.montant_chantier, montant, datetime.datetime.now().isoformat(), data.lead_id],
        )

    return commission


@router.put("/commissions/{commission_id}/status")
def update_commission_status(commission_id: int, update: CommissionStatusUpdate):
    valid = ["en_attente", "payee", "en_retard", "contentieux"]
    if update.statut not in valid:
        raise HTTPException(400, f"Statut invalide. Valeurs : {valid}")

    with get_db() as db:
        commission = row_to_dict(db.execute("SELECT * FROM commissions WHERE id=?", [commission_id]).fetchone())
        if not commission:
            raise HTTPException(404, "Commission non trouvée")

        fields = {
            "statut": update.statut,
            "updated_at": datetime.datetime.now().isoformat(),
        }
        if update.notes:
            fields["notes"] = update.notes

        set_clause = ", ".join([f"{k}=?" for k in fields])
        db.execute(f"UPDATE commissions SET {set_clause} WHERE id=?", list(fields.values()) + [commission_id])

        # Si payée, mettre à jour le lead et l'historique artisan
        if update.statut == "payee":
            db.execute(
                "UPDATE leads SET statut='commission_payee', updated_at=? WHERE id=?",
                [fields["updated_at"], commission["lead_id"]],
            )
            # Mettre à jour historique paiement de l'artisan
            db.execute(
                "UPDATE artisans SET historique_paiement='fiable', updated_at=? WHERE id=?",
                [fields["updated_at"], commission["artisan_id"]],
            )

        updated = row_to_dict(db.execute("SELECT * FROM commissions WHERE id=?", [commission_id]).fetchone())
    return updated


@router.post("/commissions/{commission_id}/relance")
async def generate_relance(commission_id: int, niveau: int = 1):
    """
    Génère un message de relance pour une commission impayée.
    niveau 1 = J+30 amiable, 2 = J+45 ferme, 3 = J+60 mise en demeure
    ⚠️ DRAFT uniquement.
    """
    from services.ai_service import generate_relance as ai_relance

    with get_db() as db:
        commission = row_to_dict(db.execute("SELECT * FROM commissions WHERE id=?", [commission_id]).fetchone())
        if not commission:
            raise HTTPException(404, "Commission non trouvée")
        lead = row_to_dict(db.execute("SELECT * FROM leads WHERE id=?", [commission["lead_id"]]).fetchone()) or {}
        artisan = row_to_dict(db.execute("SELECT * FROM artisans WHERE id=?", [commission["artisan_id"]]).fetchone()) or {}

    result = await ai_relance(commission, lead, artisan, niveau)

    if result.get("success"):
        with get_db() as db:
            db.execute(
                "UPDATE commissions SET relances_count=relances_count+1, derniere_relance=?, updated_at=? WHERE id=?",
                [datetime.date.today().isoformat(), datetime.datetime.now().isoformat(), commission_id],
            )
            # Marquer en_retard si > niveau 1
            if niveau >= 2:
                db.execute("UPDATE commissions SET statut='en_retard' WHERE id=? AND statut='en_attente'", [commission_id])
            if niveau >= 3:
                db.execute("UPDATE commissions SET statut='contentieux' WHERE id=?", [commission_id])

            db.execute(
                "INSERT INTO ai_drafts (type, reference_id, reference_type, contenu) VALUES (?,?,?,?)",
                [f"relance_niveau_{niveau}", commission_id, "commission", result["contenu"]],
            )

    return result


# ─── ALERTES ─────────────────────────────────────────────────────────────────

@router.get("/alerts")
def get_alerts():
    """Retourne toutes les alertes actives."""
    today = datetime.date.today()
    alerts = []

    with get_db() as db:
        # Leads sans nouvelle depuis 7 jours (transmis mais pas de mise à jour)
        leads_en_attente = rows_to_list(
            db.execute(
                """SELECT l.id, l.type_travaux, l.contact_nom, l.localisation,
                          l.updated_at, a.nom as artisan_nom, a.id as artisan_id
                   FROM leads l
                   LEFT JOIN artisans a ON l.artisan_id = a.id
                   WHERE l.statut = 'transmis'
                   AND date(l.updated_at) <= date('now', '-7 days')""",
            ).fetchall()
        )
        for lead in leads_en_attente:
            alerts.append({
                "type": "lead_sans_nouvelle",
                "severity": "warning",
                "message": f"Lead sans nouvelle depuis +7j : {lead['type_travaux'] or 'Travaux'} — {lead['contact_nom'] or 'Contact inconnu'}",
                "lead_id": lead["id"],
                "artisan_nom": lead.get("artisan_nom"),
                "artisan_id": lead.get("artisan_id"),
            })

        # Commissions en retard (échéance dépassée)
        commissions_retard = rows_to_list(
            db.execute(
                """SELECT cm.id, cm.montant, cm.date_echeance,
                          a.nom as artisan_nom, l.type_travaux
                   FROM commissions cm
                   LEFT JOIN artisans a ON cm.artisan_id = a.id
                   LEFT JOIN leads l ON cm.lead_id = l.id
                   WHERE cm.statut IN ('en_attente', 'en_retard')
                   AND cm.date_echeance < date('now')""",
            ).fetchall()
        )
        for cm in commissions_retard:
            days_late = (today - datetime.date.fromisoformat(cm["date_echeance"])).days
            severity = "danger" if days_late > 30 else "warning"
            alerts.append({
                "type": "commission_en_retard",
                "severity": severity,
                "message": f"Commission en retard de {days_late}j : {cm['montant']:.0f}€ — {cm['artisan_nom']}",
                "commission_id": cm["id"],
                "artisan_nom": cm["artisan_nom"],
                "days_late": days_late,
            })

        # Leads nouveaux non traités depuis 3 jours
        leads_nouveaux_vieux = rows_to_list(
            db.execute(
                """SELECT id, type_travaux, contact_nom, score
                   FROM leads
                   WHERE statut = 'nouveau'
                   AND date(created_at) <= date('now', '-3 days')
                   ORDER BY score DESC""",
            ).fetchall()
        )
        for lead in leads_nouveaux_vieux[:5]:
            alerts.append({
                "type": "lead_non_traite",
                "severity": "info",
                "message": f"Lead non qualifié depuis +3j (score {lead['score']}) : {lead['type_travaux'] or 'Travaux'}",
                "lead_id": lead["id"],
            })

    return {"alerts": alerts, "total": len(alerts)}
