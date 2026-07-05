"""Module 1 — Radar BOAMP.

Interroge l'API open data du BOAMP (Opendatasoft, Explore v2.1),
extrait les avis pertinents et les stocke en base avec déduplication
par idweb.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

import requests

from .database import get_connection

URL_API_BOAMP = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1"
    "/catalog/datasets/boamp/records"
)

# Valeurs par défaut de l'UI
MOTS_CLES_DEFAUT: list[str] = [
    "nettoyage",
    "propreté",
    "espaces verts",
    "peinture",
    "second oeuvre",
    "gardiennage",
]
DEPARTEMENTS_DEFAUT: list[str] = ["35", "22", "56", "44", "53"]
FENETRE_JOURS_DEFAUT: int = 14

_NB_TENTATIVES = 3  # retry x3 sur les erreurs réseau
_DELAI_RETRY_S = 2.0  # délai de base entre tentatives (doublé à chaque essai)


class ErreurBoamp(RuntimeError):
    """Erreur réseau ou API BOAMP, avec un message lisible pour l'UI."""


def construire_where(mot_cle: str, departements: list[str], jours: int) -> str:
    """Construit la clause ODSQL `where` pour un mot-clé donné.

    Recherche plein texte sur le mot-clé + filtre départements + fenêtre
    de publication en jours.
    """
    date_min = (date.today() - timedelta(days=jours)).isoformat()
    # Les guillemets casseraient la syntaxe ODSQL : on les neutralise
    mot_cle = mot_cle.replace('"', " ").strip()
    clause = f'"{mot_cle}" AND dateparution >= date\'{date_min}\''
    if departements:
        deps = ", ".join(f'"{d.strip()}"' for d in departements if d.strip())
        if deps:
            clause += f" AND code_departement IN ({deps})"
    return clause


def _premier_champ(record: dict[str, Any], *cles: str) -> Any:
    """Retourne la première valeur non vide parmi plusieurs clés candidates."""
    for cle in cles:
        valeur = record.get(cle)
        if valeur not in (None, "", []):
            return valeur
    return None


def parse_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Transforme un enregistrement brut de l'API en dict prêt pour la base.

    Retourne None si l'enregistrement n'a pas d'idweb (inexploitable).
    Fonction pure : testée unitairement dans tests/test_scraper.py.
    """
    # L'API v2.1 renvoie les champs à plat ; on gère aussi l'ancien format
    # imbriqué {"fields": {...}} par précaution.
    champs = record.get("fields", record)

    idweb = _premier_champ(champs, "idweb", "id")
    if not idweb:
        return None

    # code_departement peut être une liste ou une chaîne selon les avis
    departement = _premier_champ(champs, "code_departement", "dep")
    if isinstance(departement, list):
        departement = ", ".join(str(d) for d in departement)

    return {
        "idweb": str(idweb),
        "dateparution": _premier_champ(champs, "dateparution") or "",
        "datelimitereponse": _premier_champ(champs, "datelimitereponse") or "",
        "nomacheteur": _premier_champ(champs, "nomacheteur", "acheteur") or "",
        "objet": _premier_champ(champs, "objet", "titre") or "",
        "code_departement": str(departement or ""),
        "url_avis": _premier_champ(champs, "url_avis", "url") or "",
    }


def _requete_api(params: dict[str, Any]) -> dict[str, Any]:
    """Appelle l'API BOAMP avec retry x3 et messages d'erreur clairs."""
    derniere_erreur: Exception | None = None
    for tentative in range(_NB_TENTATIVES):
        try:
            reponse = requests.get(
                URL_API_BOAMP,
                params=params,
                timeout=30,
                headers={"User-Agent": "AO-PILOT/1.0"},
            )
            if reponse.status_code == 403:
                raise ErreurBoamp(
                    "L'API BOAMP a refusé la requête (403). Réessayez plus tard "
                    "ou vérifiez que votre réseau autorise boamp-datadila.opendatasoft.com."
                )
            if reponse.status_code == 429:
                raise requests.RequestException("Trop de requêtes (429)")
            reponse.raise_for_status()
            return reponse.json()
        except ErreurBoamp:
            raise  # 403 : inutile de réessayer
        except requests.RequestException as exc:
            derniere_erreur = exc
            if tentative < _NB_TENTATIVES - 1:
                time.sleep(_DELAI_RETRY_S * (2**tentative))
    raise ErreurBoamp(
        f"Impossible de joindre l'API BOAMP après {_NB_TENTATIVES} tentatives "
        f"(délai dépassé ou erreur réseau) : {derniere_erreur}"
    )


def scanner_boamp(
    mots_cles: list[str],
    departements: list[str],
    jours: int,
    limite_par_mot: int = 100,
) -> list[dict[str, Any]]:
    """Interroge l'API pour chaque mot-clé et retourne les avis dédupliqués."""
    resultats: dict[str, dict[str, Any]] = {}
    for mot in mots_cles:
        mot = mot.strip()
        if not mot:
            continue
        donnees = _requete_api(
            {
                "where": construire_where(mot, departements, jours),
                "limit": limite_par_mot,
                "order_by": "datelimitereponse",
            }
        )
        for record in donnees.get("results", []):
            avis = parse_record(record)
            if avis:
                resultats[avis["idweb"]] = avis  # déduplication par idweb
    return list(resultats.values())


def enregistrer_marches(avis: list[dict[str, Any]]) -> int:
    """Insère les avis en base (ignore ceux déjà connus). Retourne le nb de nouveaux."""
    conn = get_connection()
    try:
        nouveaux = 0
        for a in avis:
            curseur = conn.execute(
                """
                INSERT OR IGNORE INTO marches
                    (idweb, dateparution, datelimitereponse, nomacheteur,
                     objet, code_departement, url_avis)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    a["idweb"],
                    a["dateparution"],
                    a["datelimitereponse"],
                    a["nomacheteur"],
                    a["objet"],
                    a["code_departement"],
                    a["url_avis"],
                ),
            )
            nouveaux += curseur.rowcount
        conn.commit()
        return nouveaux
    finally:
        conn.close()


def lister_marches(statut: str | None = None) -> list[dict[str, Any]]:
    """Liste les marchés en base, triés par deadline croissante."""
    conn = get_connection()
    try:
        requete = "SELECT * FROM marches"
        params: tuple = ()
        if statut:
            requete += " WHERE statut = ?"
            params = (statut,)
        requete += " ORDER BY datelimitereponse ASC"
        return [dict(ligne) for ligne in conn.execute(requete, params)]
    finally:
        conn.close()


def changer_statut_marche(idweb: str, statut: str) -> None:
    """Met à jour le statut d'un marché (nouveau / vu / prospecté / gagné)."""
    conn = get_connection()
    try:
        conn.execute("UPDATE marches SET statut = ? WHERE idweb = ?", (statut, idweb))
        conn.commit()
    finally:
        conn.close()


def supprimer_marche(idweb: str) -> None:
    """Supprime un marché (les prospects liés sont conservés, lien mis à NULL)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM marches WHERE idweb = ?", (idweb,))
        conn.commit()
    finally:
        conn.close()


def marquer_tous_vus() -> int:
    """Passe tous les marchés 'nouveau' en 'vu'. Retourne le nombre modifié."""
    conn = get_connection()
    try:
        curseur = conn.execute(
            "UPDATE marches SET statut = 'vu' WHERE statut = 'nouveau'"
        )
        conn.commit()
        return curseur.rowcount
    finally:
        conn.close()


def jours_restants(datelimite: str) -> int | None:
    """Nombre de jours avant la date limite de réponse (None si date invalide)."""
    if not datelimite:
        return None
    try:
        # Les dates BOAMP sont en ISO, parfois avec heure/fuseau
        limite = datetime.fromisoformat(datelimite.replace("Z", "+00:00"))
        return (limite.date() - date.today()).days
    except ValueError:
        return None
