"""Module 3 — Générateur d'emails.

Trois templates éditables (déclenché par avis / relance / hors avis)
stockés dans templates/emails/, fusion de variables et génération de
liens mailto:. Aucun envoi automatique.
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Any

DOSSIER_TEMPLATES: Path = (
    Path(__file__).resolve().parent.parent / "templates" / "emails"
)

# Nom de fichier -> libellé affiché dans l'UI
TEMPLATES_EMAILS: dict[str, str] = {
    "declenche_par_avis.txt": "Déclenché par avis",
    "relance.txt": "Relance",
    "hors_avis.txt": "Hors avis (prospection à froid)",
}

# Variables disponibles pour la fusion (documentées dans l'UI)
VARIABLES_DISPONIBLES: list[str] = [
    "objet",
    "acheteur",
    "deadline",
    "jours_restants",
    "prenom_contact",
    "secteur",
]


def charger_template(nom_fichier: str) -> str:
    """Lit un template d'email depuis le disque."""
    chemin = DOSSIER_TEMPLATES / nom_fichier
    return chemin.read_text(encoding="utf-8")


def sauvegarder_template(nom_fichier: str, contenu: str) -> None:
    """Écrit un template d'email modifié depuis l'UI."""
    chemin = DOSSIER_TEMPLATES / nom_fichier
    chemin.write_text(contenu, encoding="utf-8")


def fusionner(template: str, variables: dict[str, Any]) -> str:
    """Remplace les {variables} du template par leurs valeurs.

    Les variables absentes du dict sont remplacées par un marqueur visible
    [?nom?] pour que l'utilisateur repère ce qui manque avant d'envoyer.
    Fonction pure : testée dans tests/test_emails.py.
    """

    def remplacer(match: re.Match[str]) -> str:
        nom = match.group(1)
        if nom in variables and variables[nom] not in (None, ""):
            return str(variables[nom])
        return f"[?{nom}?]"

    return re.sub(r"\{(\w+)\}", remplacer, template)


def extraire_sujet_corps(texte: str) -> tuple[str, str]:
    """Sépare la première ligne 'Sujet: ...' du corps de l'email.

    Convention des templates : la première ligne commence par 'Sujet:'.
    """
    lignes = texte.splitlines()
    if lignes and lignes[0].lower().startswith("sujet:"):
        sujet = lignes[0].split(":", 1)[1].strip()
        corps = "\n".join(lignes[1:]).lstrip("\n")
        return sujet, corps
    return "", texte


def generer_mailto(destinataire: str, sujet: str, corps: str) -> str:
    """Construit un lien mailto: prérempli (destinataire, sujet, corps)."""
    params = urllib.parse.urlencode(
        {"subject": sujet, "body": corps}, quote_via=urllib.parse.quote
    )
    return f"mailto:{destinataire}?{params}"


def variables_depuis_marche(
    marche: dict[str, Any] | None,
    prospect: dict[str, Any] | None = None,
    jours: int | None = None,
) -> dict[str, Any]:
    """Prépare le dict de variables à partir d'un marché et d'un prospect."""
    variables: dict[str, Any] = {}
    if marche:
        variables["objet"] = marche.get("objet", "")
        variables["acheteur"] = marche.get("nomacheteur", "")
        variables["deadline"] = marche.get("datelimitereponse", "")
        if jours is not None:
            variables["jours_restants"] = jours
    if prospect:
        variables["prenom_contact"] = prospect.get("prenom_contact", "")
        variables["secteur"] = prospect.get("secteur", "")
    return variables
