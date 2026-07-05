"""Module 2 — Gestion des prospects.

Table de prospects liés aux marchés, saisie manuelle, import CSV,
et calcul des relances dues (J+3 après contact).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

from .database import STATUTS_PROSPECT, get_connection

DELAI_RELANCE_JOURS: int = 3  # relance due J+3 après le contact


def ajouter_prospect(
    entreprise: str,
    ville: str = "",
    email: str = "",
    telephone: str = "",
    prenom_contact: str = "",
    secteur: str = "",
    source: str = "",
    statut: str = "à contacter",
    marche_idweb: str | None = None,
    notes: str = "",
) -> int:
    """Ajoute un prospect et retourne son id."""
    if statut not in STATUTS_PROSPECT:
        raise ValueError(f"Statut invalide : {statut}")
    conn = get_connection()
    try:
        curseur = conn.execute(
            """
            INSERT INTO prospects
                (entreprise, ville, email, telephone, prenom_contact,
                 secteur, source, statut, marche_idweb, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entreprise,
                ville,
                email,
                telephone,
                prenom_contact,
                secteur,
                source,
                statut,
                marche_idweb,
                notes,
            ),
        )
        conn.commit()
        return int(curseur.lastrowid)
    finally:
        conn.close()


def lister_prospects(
    statut: str | None = None, marche_idweb: str | None = None
) -> list[dict[str, Any]]:
    """Liste les prospects, filtrables par statut et/ou marché."""
    conn = get_connection()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if statut:
            clauses.append("statut = ?")
            params.append(statut)
        if marche_idweb:
            clauses.append("marche_idweb = ?")
            params.append(marche_idweb)
        requete = "SELECT * FROM prospects"
        if clauses:
            requete += " WHERE " + " AND ".join(clauses)
        requete += " ORDER BY date_ajout DESC"
        return [dict(ligne) for ligne in conn.execute(requete, params)]
    finally:
        conn.close()


def changer_statut_prospect(prospect_id: int, statut: str) -> None:
    """Change le statut ; enregistre la date de contact quand on passe à 'contacté' ou 'relancé'."""
    if statut not in STATUTS_PROSPECT:
        raise ValueError(f"Statut invalide : {statut}")
    conn = get_connection()
    try:
        if statut in ("contacté", "relancé"):
            conn.execute(
                "UPDATE prospects SET statut = ?, date_contact = date('now') WHERE id = ?",
                (statut, prospect_id),
            )
        else:
            conn.execute(
                "UPDATE prospects SET statut = ? WHERE id = ?", (statut, prospect_id)
            )
        conn.commit()
    finally:
        conn.close()


def supprimer_prospect(prospect_id: int) -> None:
    """Supprime un prospect."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM prospects WHERE id = ?", (prospect_id,))
        conn.commit()
    finally:
        conn.close()


def relances_dues() -> list[dict[str, Any]]:
    """Prospects contactés/relancés depuis au moins J+3 sans réponse."""
    conn = get_connection()
    try:
        lignes = conn.execute(
            """
            SELECT * FROM prospects
            WHERE statut IN ('contacté', 'relancé')
              AND date_contact IS NOT NULL
            ORDER BY date_contact ASC
            """
        )
        dues: list[dict[str, Any]] = []
        for ligne in lignes:
            prospect = dict(ligne)
            try:
                contact = datetime.fromisoformat(prospect["date_contact"]).date()
            except (ValueError, TypeError):
                continue
            if (date.today() - contact).days >= DELAI_RELANCE_JOURS:
                dues.append(prospect)
        return dues
    finally:
        conn.close()


def exporter_csv() -> str:
    """Exporte tous les prospects en CSV (pour téléchargement depuis l'UI)."""
    colonnes = [
        "entreprise",
        "ville",
        "email",
        "telephone",
        "prenom_contact",
        "secteur",
        "source",
        "statut",
        "date_contact",
        "marche_idweb",
        "notes",
    ]
    tampon = io.StringIO()
    ecrivain = csv.DictWriter(tampon, fieldnames=colonnes, extrasaction="ignore")
    ecrivain.writeheader()
    for prospect in lister_prospects():
        ecrivain.writerow({c: prospect.get(c) or "" for c in colonnes})
    return tampon.getvalue()


def importer_csv(contenu: str | bytes, marche_idweb: str | None = None) -> int:
    """Importe des prospects depuis un CSV (colonnes : entreprise, ville, email,
    telephone, prenom_contact, secteur, source). Seule 'entreprise' est obligatoire.
    Retourne le nombre de lignes importées."""
    if isinstance(contenu, bytes):
        contenu = contenu.decode("utf-8-sig")
    # Excel français exporte en ';' : détection du délimiteur sur l'en-tête
    premiere_ligne = contenu.splitlines()[0] if contenu.strip() else ""
    delimiteur = ";" if premiere_ligne.count(";") > premiere_ligne.count(",") else ","
    lecteur = csv.DictReader(io.StringIO(contenu), delimiter=delimiteur)
    nb = 0
    for ligne in lecteur:
        # Normalise les clés (minuscules, sans espaces superflus)
        ligne = {(k or "").strip().lower(): (v or "").strip() for k, v in ligne.items()}
        entreprise = ligne.get("entreprise", "")
        if not entreprise:
            continue
        ajouter_prospect(
            entreprise=entreprise,
            ville=ligne.get("ville", ""),
            email=ligne.get("email", ""),
            telephone=ligne.get("telephone", ""),
            prenom_contact=ligne.get("prenom_contact", ""),
            secteur=ligne.get("secteur", ""),
            source=ligne.get("source", "import CSV"),
            marche_idweb=marche_idweb,
        )
        nb += 1
    return nb
