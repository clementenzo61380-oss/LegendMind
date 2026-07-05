"""Prospection automatisée : l'IA construit la base de prospects.

Deux moteurs :
1. Annuaire officiel des entreprises (API publique recherche-entreprises
   .api.gouv.fr, gratuite, sans clé) : trouve les TPE/PME du secteur visé
   dans un département et alimente la table prospects.
2. Enrichissement IA : Claude + recherche web retrouve les coordonnées
   publiques (email, téléphone, contact) d'un prospect, sans rien inventer.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from .database import get_connection
from .dce import MODELE_DCE, _client_anthropic
from .prospects import ajouter_prospect, lister_prospects

URL_ANNUAIRE = "https://recherche-entreprises.api.gouv.fr/search"

# Secteurs cibles -> codes NAF (activité principale) correspondants
SECTEURS_NAF: dict[str, list[str]] = {
    "nettoyage": ["81.21Z", "81.22Z", "81.29A", "81.29B"],
    "espaces verts": ["81.30Z"],
    "peinture": ["43.34Z"],
    "second oeuvre": ["43.32A", "43.32B", "43.33Z", "43.31Z"],
    "sécurité": ["80.10Z", "80.20Z"],
}

_NB_TENTATIVES = 3


class ErreurAnnuaire(RuntimeError):
    """Erreur réseau ou API annuaire, message lisible pour l'UI."""


def parse_entreprise(item: dict[str, Any], secteur: str) -> dict[str, str] | None:
    """Transforme un résultat de l'annuaire en prospect prêt à insérer.

    Fonction pure, testée unitairement. Retourne None si le nom manque.
    """
    nom = (item.get("nom_complet") or item.get("nom_raison_sociale") or "").strip()
    if not nom:
        return None
    siege = item.get("siege") or {}
    ville = (siege.get("libelle_commune") or "").strip().title()
    dirigeants = item.get("dirigeants") or []
    prenom = ""
    if dirigeants and isinstance(dirigeants[0], dict):
        prenom = (dirigeants[0].get("prenoms") or "").split(",")[0].strip().title()
    notes = f"SIREN {item.get('siren', '?')} — NAF {item.get('activite_principale', '?')}"
    return {
        "entreprise": nom.title(),
        "ville": ville,
        "prenom_contact": prenom,
        "secteur": secteur,
        "source": "annuaire entreprises (auto)",
        "notes": notes,
    }


def rechercher_entreprises(
    secteur: str, departement: str, limite: int = 25
) -> list[dict[str, str]]:
    """Interroge l'annuaire officiel et retourne des prospects candidats."""
    codes_naf = SECTEURS_NAF.get(secteur)
    if not codes_naf:
        raise ValueError(f"Secteur inconnu : {secteur}")

    derniere_erreur: Exception | None = None
    for tentative in range(_NB_TENTATIVES):
        try:
            reponse = requests.get(
                URL_ANNUAIRE,
                params={
                    "activite_principale": ",".join(codes_naf),
                    "departement": departement.strip(),
                    "per_page": min(limite, 25),  # maximum accepté par l'API
                    "etat_administratif": "A",  # entreprises actives uniquement
                },
                timeout=30,
                headers={"User-Agent": "AO-PILOT/1.0"},
            )
            reponse.raise_for_status()
            resultats = reponse.json().get("results", [])
            prospects_candidats = []
            for item in resultats[:limite]:
                candidat = parse_entreprise(item, secteur)
                if candidat:
                    prospects_candidats.append(candidat)
            return prospects_candidats
        except requests.RequestException as exc:
            derniere_erreur = exc
            if tentative < _NB_TENTATIVES - 1:
                time.sleep(2.0 * (2**tentative))
    raise ErreurAnnuaire(
        "Impossible de joindre l'annuaire des entreprises "
        f"(recherche-entreprises.api.gouv.fr) : {derniere_erreur}"
    )


def importer_prospects_auto(
    secteur: str,
    departement: str,
    limite: int = 25,
    marche_idweb: str | None = None,
) -> int:
    """Recherche + insertion en base, en évitant les doublons (nom+ville).

    Retourne le nombre de prospects réellement ajoutés.
    """
    existants = {
        (p["entreprise"].lower().strip(), (p["ville"] or "").lower().strip())
        for p in lister_prospects()
    }
    ajoutes = 0
    for candidat in rechercher_entreprises(secteur, departement, limite):
        cle = (candidat["entreprise"].lower().strip(), candidat["ville"].lower().strip())
        if cle in existants:
            continue
        ajouter_prospect(marche_idweb=marche_idweb, **candidat)
        existants.add(cle)
        ajoutes += 1
    return ajoutes


# ---------------------------------------------------------------------------
# Enrichissement des coordonnées par IA (recherche web)
# ---------------------------------------------------------------------------

_PROMPT_ENRICHISSEMENT = (
    "Tu cherches les coordonnées PUBLIQUES d'une entreprise française pour "
    "une prise de contact commerciale légitime (B2B). Utilise la recherche "
    "web. Ne devine JAMAIS : si une information n'est pas trouvée, laisse la "
    "chaîne vide. Réponds UNIQUEMENT par un objet JSON, sans autre texte :\n"
    '{"email": "", "telephone": "", "site_web": "", "prenom_contact": ""}'
)


def extraire_json(texte: str) -> dict[str, str]:
    """Extrait le dernier objet JSON d'une réponse texte (fonction pure, testée)."""
    correspondances = re.findall(r"\{[^{}]*\}", texte, flags=re.DOTALL)
    for brut in reversed(correspondances):
        try:
            objet = json.loads(brut)
            if isinstance(objet, dict):
                return {k: str(v or "") for k, v in objet.items()}
        except json.JSONDecodeError:
            continue
    return {}


def enrichir_prospect(prospect: dict[str, Any]) -> dict[str, str]:
    """Fait rechercher par l'IA les coordonnées d'un prospect et met à jour la base.

    Retourne les champs trouvés (chaînes vides si rien de fiable).
    Coût : un appel API avec ~2-3 recherches web (quelques centimes).
    """
    client = _client_anthropic()
    reponse = client.messages.create(
        model=MODELE_DCE,
        max_tokens=1500,
        system=_PROMPT_ENRICHISSEMENT,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Entreprise : {prospect['entreprise']}\n"
                    f"Ville : {prospect.get('ville') or '(inconnue)'}\n"
                    f"Secteur : {prospect.get('secteur') or '(inconnu)'}\n"
                    f"Note : {prospect.get('notes') or ''}"
                ),
            }
        ],
    )
    texte = "".join(bloc.text for bloc in reponse.content if bloc.type == "text")
    trouve = extraire_json(texte)

    champs: dict[str, str] = {}
    for cle in ("email", "telephone", "prenom_contact"):
        valeur = (trouve.get(cle) or "").strip()
        if valeur and not prospect.get(cle):  # ne jamais écraser une saisie manuelle
            champs[cle] = valeur
    site = (trouve.get("site_web") or "").strip()

    if champs or site:
        conn = get_connection()
        try:
            if champs:
                affectations = ", ".join(f"{c} = ?" for c in champs)
                conn.execute(
                    f"UPDATE prospects SET {affectations} WHERE id = ?",
                    (*champs.values(), prospect["id"]),
                )
            if site:
                conn.execute(
                    "UPDATE prospects SET notes = COALESCE(notes, '') || ? WHERE id = ?",
                    (f"\nSite : {site}", prospect["id"]),
                )
            conn.commit()
        finally:
            conn.close()
    if site:
        champs["site_web"] = site
    return champs
