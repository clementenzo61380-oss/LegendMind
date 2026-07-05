"""Module 4 — Analyseur de DCE.

Extraction du texte des PDF (CCTP, RC, CCAP, avis) avec pypdf, puis
analyse par l'API Anthropic. Si le dossier dépasse la fenêtre de
contexte, chaque document est analysé séparément puis synthétisé.
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Any, BinaryIO

from .database import get_connection

# Modèle utilisé pour l'analyse (imposé par le cahier des charges)
MODELE_DCE: str = "claude-sonnet-4-6"

# Tarifs claude-sonnet-4-6 en $ par million de tokens (pour l'estimation de coût)
PRIX_INPUT_PAR_MTOK: float = 3.0
PRIX_OUTPUT_PAR_MTOK: float = 15.0

# Au-delà de ce volume de caractères, on découpe document par document.
# ~600 000 caractères ≈ 170 000 tokens : marge confortable sous la fenêtre.
SEUIL_DECOUPAGE_CARS: int = 600_000

PROMPT_SYSTEME_DCE: str = (
    "Tu es un expert en marchés publics côté candidat. Analyse ce DCE et produis :\n"
    "1) fiche d'identité du marché,\n"
    "2) critères de notation exacts avec pondérations,\n"
    "3) contraintes du site,\n"
    "4) pièges et pièces exigées à peine d'irrégularité,\n"
    "5) questions à poser à l'acheteur,\n"
    "6) les 3 arguments qui rapporteront le plus de points."
)


def extraire_texte_pdf(fichier: BinaryIO | bytes, nom: str = "") -> str:
    """Extrait le texte d'un PDF avec pypdf. Retourne une chaîne (peut être vide)."""
    from pypdf import PdfReader  # import local : pypdf n'est requis que pour ce module

    if isinstance(fichier, bytes):
        fichier = BytesIO(fichier)
    lecteur = PdfReader(fichier)
    pages = [page.extract_text() or "" for page in lecteur.pages]
    texte = "\n".join(pages).strip()
    if not texte:
        return f"[Aucun texte extractible du fichier {nom} — PDF scanné ?]"
    return texte


def estimer_tokens(texte: str) -> int:
    """Estimation grossière du nombre de tokens (~3,5 caractères par token en français)."""
    return int(len(texte) / 3.5)


def estimer_cout_analyse(textes: dict[str, str]) -> float:
    """Estimation du coût API en dollars pour une analyse (input + ~4000 tokens de sortie)."""
    tokens_entree = sum(estimer_tokens(t) for t in textes.values())
    # En mode découpage : un appel par document + l'appel de synthèse
    tokens_sortie = 4000 * (len(textes) + 1 if _doit_decouper(textes) else 1)
    return (
        tokens_entree * PRIX_INPUT_PAR_MTOK / 1_000_000
        + tokens_sortie * PRIX_OUTPUT_PAR_MTOK / 1_000_000
    )


def _doit_decouper(textes: dict[str, str]) -> bool:
    """Vrai si le volume total dépasse le seuil de découpage."""
    return sum(len(t) for t in textes.values()) > SEUIL_DECOUPAGE_CARS


def _client_anthropic() -> Any:
    """Crée le client Anthropic (clé lue dans .env / variables d'environnement)."""
    import anthropic

    cle = os.environ.get("ANTHROPIC_API_KEY", "")
    if not cle:
        raise RuntimeError(
            "Clé API Anthropic absente. Créez un fichier .env contenant "
            "ANTHROPIC_API_KEY=sk-ant-... à la racine du projet."
        )
    return anthropic.Anthropic(api_key=cle)


def _appel_api(client: Any, systeme: str, contenu: str, max_tokens: int = 8000) -> str:
    """Un appel API simple : prompt système + contenu utilisateur -> texte."""
    reponse = client.messages.create(
        model=MODELE_DCE,
        max_tokens=max_tokens,
        system=systeme,
        messages=[{"role": "user", "content": contenu}],
    )
    return "".join(bloc.text for bloc in reponse.content if bloc.type == "text")


def analyser_dce(textes: dict[str, str]) -> str:
    """Analyse un DCE (dict nom_fichier -> texte extrait) et retourne le rapport.

    Si le volume dépasse la fenêtre de contexte, chaque document est analysé
    séparément puis une synthèse globale est produite.
    """
    client = _client_anthropic()

    if not _doit_decouper(textes):
        corpus = "\n\n".join(
            f"=== DOCUMENT : {nom} ===\n{texte}" for nom, texte in textes.items()
        )
        return _appel_api(client, PROMPT_SYSTEME_DCE, corpus)

    # DCE volumineux : analyse document par document, puis synthèse
    analyses_partielles: list[str] = []
    for nom, texte in textes.items():
        # Tronque chaque document au seuil pour rester sous la fenêtre
        extrait = texte[:SEUIL_DECOUPAGE_CARS]
        analyse = _appel_api(
            client,
            PROMPT_SYSTEME_DCE
            + "\nTu ne vois qu'UN document du DCE : analyse ce que ce document "
            "permet de savoir, sans inventer le reste.",
            f"=== DOCUMENT : {nom} ===\n{extrait}",
        )
        analyses_partielles.append(f"## Analyse de {nom}\n\n{analyse}")

    synthese = _appel_api(
        client,
        PROMPT_SYSTEME_DCE
        + "\nOn te fournit les analyses partielles de chaque document du DCE. "
        "Fusionne-les en une analyse globale unique, structurée selon les 6 points.",
        "\n\n".join(analyses_partielles),
    )
    return synthese


def sauvegarder_analyse(
    resultat: str, nom_fichiers: str, marche_idweb: str | None = None
) -> int:
    """Enregistre l'analyse en base, liée au marché si fourni. Retourne l'id."""
    conn = get_connection()
    try:
        curseur = conn.execute(
            "INSERT INTO analyses_dce (marche_idweb, nom_fichiers, resultat) VALUES (?, ?, ?)",
            (marche_idweb, nom_fichiers, resultat),
        )
        conn.commit()
        return int(curseur.lastrowid)
    finally:
        conn.close()


def lister_analyses(marche_idweb: str | None = None) -> list[dict[str, Any]]:
    """Liste les analyses sauvegardées (optionnellement filtrées par marché)."""
    conn = get_connection()
    try:
        if marche_idweb:
            lignes = conn.execute(
                "SELECT * FROM analyses_dce WHERE marche_idweb = ? ORDER BY date_analyse DESC",
                (marche_idweb,),
            )
        else:
            lignes = conn.execute(
                "SELECT * FROM analyses_dce ORDER BY date_analyse DESC"
            )
        return [dict(ligne) for ligne in lignes]
    finally:
        conn.close()
