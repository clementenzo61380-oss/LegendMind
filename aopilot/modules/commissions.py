"""Suivi des commissions sur dossiers gagnés.

Modèle économique : une commission (% du montant du marché) est due
pour chaque dossier réussi. Cycle : en attente → facturée → payée.
"""

from __future__ import annotations

from typing import Any

from .database import ecrire_reglage, get_connection, lire_reglage

STATUTS_COMMISSION: list[str] = ["en attente", "facturée", "payée"]

TAUX_DEFAUT: float = 5.0  # % du montant du marché, modifiable dans l'UI


def taux_par_defaut() -> float:
    """Taux de commission par défaut (mémorisé dans les réglages)."""
    try:
        return float(lire_reglage("taux_commission", str(TAUX_DEFAUT)))
    except ValueError:
        return TAUX_DEFAUT


def definir_taux_par_defaut(taux: float) -> None:
    """Mémorise le taux par défaut pour les prochains dossiers."""
    ecrire_reglage("taux_commission", str(taux))


def montant_commission(montant_marche: float, taux: float) -> float:
    """Commission due : montant du marché × taux %."""
    return round(montant_marche * taux / 100.0, 2)


def enregistrer_commission(
    client: str,
    montant_marche: float,
    taux: float,
    marche_idweb: str | None = None,
) -> int:
    """Enregistre la commission d'un dossier gagné. Retourne son id."""
    if montant_marche <= 0 or taux <= 0:
        raise ValueError("Le montant du marché et le taux doivent être positifs.")
    conn = get_connection()
    try:
        curseur = conn.execute(
            """
            INSERT INTO commissions (marche_idweb, client, montant_marche, taux)
            VALUES (?, ?, ?, ?)
            """,
            (marche_idweb, client, montant_marche, taux),
        )
        conn.commit()
        return int(curseur.lastrowid)
    finally:
        conn.close()


def lister_commissions() -> list[dict[str, Any]]:
    """Liste les commissions avec le montant calculé, plus récentes d'abord."""
    conn = get_connection()
    try:
        lignes = conn.execute(
            "SELECT * FROM commissions ORDER BY date_creation DESC"
        )
        resultat = []
        for ligne in lignes:
            commission = dict(ligne)
            commission["montant_commission"] = montant_commission(
                commission["montant_marche"], commission["taux"]
            )
            resultat.append(commission)
        return resultat
    finally:
        conn.close()


def changer_statut_commission(commission_id: int, statut: str) -> None:
    """Fait avancer une commission dans son cycle (en attente / facturée / payée)."""
    if statut not in STATUTS_COMMISSION:
        raise ValueError(f"Statut invalide : {statut}")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE commissions SET statut = ? WHERE id = ?", (statut, commission_id)
        )
        conn.commit()
    finally:
        conn.close()


def supprimer_commission(commission_id: int) -> None:
    """Supprime une commission."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM commissions WHERE id = ?", (commission_id,))
        conn.commit()
    finally:
        conn.close()


def marche_a_commission(marche_idweb: str) -> bool:
    """Vrai si une commission est déjà enregistrée pour ce marché."""
    conn = get_connection()
    try:
        ligne = conn.execute(
            "SELECT 1 FROM commissions WHERE marche_idweb = ? LIMIT 1",
            (marche_idweb,),
        ).fetchone()
        return ligne is not None
    finally:
        conn.close()


def totaux() -> dict[str, float]:
    """Totaux pour le dashboard : commissions encaissées et en attente d'encaissement."""
    encaissees = 0.0
    en_attente = 0.0
    for commission in lister_commissions():
        if commission["statut"] == "payée":
            encaissees += commission["montant_commission"]
        else:  # en attente ou facturée : pas encore encaissée
            en_attente += commission["montant_commission"]
    return {"encaissees": round(encaissees, 2), "en_attente": round(en_attente, 2)}
