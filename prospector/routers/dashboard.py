import datetime
from fastapi import APIRouter
from database.db import get_db, rows_to_list, row_to_dict

router = APIRouter()


@router.get("/stats")
def get_stats():
    """Stats globales pour le dashboard."""
    today = datetime.date.today()
    first_day_month = today.replace(day=1).isoformat()
    today_str = today.isoformat()

    with get_db() as db:
        # Leads
        leads_total = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        leads_nouveaux = db.execute("SELECT COUNT(*) FROM leads WHERE statut='nouveau'").fetchone()[0]
        leads_actifs = db.execute(
            "SELECT COUNT(*) FROM leads WHERE statut NOT IN ('perdu', 'commission_payee')"
        ).fetchone()[0]
        leads_signes = db.execute("SELECT COUNT(*) FROM leads WHERE statut='signe'").fetchone()[0]

        # Artisans
        artisans_total = db.execute("SELECT COUNT(*) FROM artisans").fetchone()[0]
        artisans_avec_contrat = db.execute("SELECT COUNT(*) FROM artisans WHERE contrat_signe=1").fetchone()[0]

        # Commissions
        commissions = rows_to_list(db.execute("SELECT * FROM commissions").fetchall())
        ca_total = sum(c["montant"] for c in commissions if c["statut"] == "payee")
        ca_mois = sum(
            c["montant"] for c in commissions
            if c["statut"] == "payee" and (c.get("updated_at") or "") >= first_day_month
        )
        en_attente_montant = sum(c["montant"] for c in commissions if c["statut"] in ["en_attente", "en_retard"])
        en_retard_count = sum(1 for c in commissions if c["statut"] == "en_retard")
        en_retard_montant = sum(c["montant"] for c in commissions if c["statut"] == "en_retard")

        # Alertes
        leads_sans_nouvelle = db.execute(
            "SELECT COUNT(*) FROM leads WHERE statut='transmis' AND date(updated_at) <= date('now', '-7 days')"
        ).fetchone()[0]

        commissions_retard_count = db.execute(
            "SELECT COUNT(*) FROM commissions WHERE statut IN ('en_attente','en_retard') AND date_echeance < ?",
            [today_str],
        ).fetchone()[0]

    return {
        "leads": {
            "total": leads_total,
            "nouveaux": leads_nouveaux,
            "actifs": leads_actifs,
            "signes": leads_signes,
        },
        "artisans": {
            "total": artisans_total,
            "avec_contrat": artisans_avec_contrat,
        },
        "commissions": {
            "ca_total": ca_total,
            "ca_mois": ca_mois,
            "en_attente_montant": en_attente_montant,
            "en_retard_count": en_retard_count,
            "en_retard_montant": en_retard_montant,
        },
        "alertes": {
            "leads_sans_nouvelle": leads_sans_nouvelle,
            "commissions_retard": commissions_retard_count,
        },
    }


@router.get("/pipeline")
def get_pipeline():
    """Leads groupés par statut pour le pipeline Kanban."""
    statuts = [
        ("nouveau", "Nouveau", "#64748b"),
        ("qualifie", "Qualifié", "#3b82f6"),
        ("transmis", "Transmis", "#f97316"),
        ("devis_envoye", "Devis envoyé", "#8b5cf6"),
        ("signe", "Signé", "#10b981"),
        ("commission_payee", "Payé", "#059669"),
        ("perdu", "Perdu", "#ef4444"),
    ]

    with get_db() as db:
        result = []
        for statut, label, color in statuts:
            leads = rows_to_list(
                db.execute(
                    """SELECT l.id, l.type_travaux, l.contact_nom, l.localisation,
                              l.score, l.budget_estime, l.commission_attendue, l.created_at,
                              a.nom as artisan_nom
                       FROM leads l
                       LEFT JOIN artisans a ON l.artisan_id = a.id
                       WHERE l.statut = ?
                       ORDER BY l.score DESC
                       LIMIT 50""",
                    [statut],
                ).fetchall()
            )
            total_montant = sum(float(l.get("budget_estime") or 0) for l in leads)
            result.append({
                "statut": statut,
                "label": label,
                "color": color,
                "count": len(leads),
                "total_montant": total_montant,
                "leads": leads,
            })
    return {"pipeline": result}


@router.get("/commissions-summary")
def get_commissions_summary():
    """Résumé financier des commissions."""
    with get_db() as db:
        by_month = rows_to_list(
            db.execute(
                """SELECT strftime('%Y-%m', updated_at) as mois,
                          SUM(montant) as montant, COUNT(*) as count
                   FROM commissions
                   WHERE statut = 'payee'
                   GROUP BY mois
                   ORDER BY mois DESC
                   LIMIT 12"""
            ).fetchall()
        )

        upcoming = rows_to_list(
            db.execute(
                """SELECT cm.*, a.nom as artisan_nom, l.type_travaux
                   FROM commissions cm
                   LEFT JOIN artisans a ON cm.artisan_id = a.id
                   LEFT JOIN leads l ON cm.lead_id = l.id
                   WHERE cm.statut IN ('en_attente', 'en_retard')
                   ORDER BY cm.date_echeance ASC
                   LIMIT 20"""
            ).fetchall()
        )

        total_encaisse = db.execute("SELECT COALESCE(SUM(montant),0) FROM commissions WHERE statut='payee'").fetchone()[0]
        total_pipeline = db.execute("SELECT COALESCE(SUM(montant),0) FROM commissions WHERE statut IN ('en_attente','en_retard')").fetchone()[0]

    return {
        "by_month": by_month,
        "upcoming": upcoming,
        "total_encaisse": total_encaisse,
        "total_pipeline": total_pipeline,
    }


@router.get("/top-artisans")
def get_top_artisans():
    """Classement artisans par volume + fiabilité."""
    with get_db() as db:
        top = rows_to_list(
            db.execute(
                """SELECT a.*,
                          COUNT(DISTINCT l.id) as nb_leads_transmis,
                          COUNT(DISTINCT CASE WHEN l.statut = 'signe' THEN l.id END) as nb_signes,
                          COALESCE(SUM(CASE WHEN cm.statut='payee' THEN cm.montant ELSE 0 END), 0) as ca_total,
                          COALESCE(SUM(CASE WHEN cm.statut IN ('en_attente','en_retard') THEN cm.montant ELSE 0 END), 0) as ca_en_attente
                   FROM artisans a
                   LEFT JOIN leads l ON l.artisan_id = a.id
                   LEFT JOIN commissions cm ON cm.artisan_id = a.id
                   GROUP BY a.id
                   ORDER BY ca_total DESC, nb_signes DESC
                   LIMIT 10"""
            ).fetchall()
        )
    return {"artisans": top}
