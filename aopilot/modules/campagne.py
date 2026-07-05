"""Campagnes : rapprochement automatique offres BOAMP ↔ base de prospects.

Pour un marché donné, identifie les prospects du bon secteur puis génère
un email pour chacun — soit par fusion de template (gratuit), soit rédigé
par l'IA (personnalisé, ~0,02 $ par email). Les emails générés sont
stockés en base pour être envoyés au rythme de l'utilisateur.
"""

from __future__ import annotations

from typing import Any, Callable

from .database import get_connection
from .dce import MODELE_DCE, _client_anthropic
from .emails import charger_template, extraire_sujet_corps, fusionner, variables_depuis_marche
from .scraper import jours_restants

# Secteur -> mots repérés dans l'objet du marché (minuscules, sans accents variables)
SECTEUR_MOTS_CLES: dict[str, list[str]] = {
    "nettoyage": ["nettoyage", "propreté", "proprete", "entretien des locaux", "entretien ménager"],
    "espaces verts": ["espaces verts", "espace vert", "élagage", "elagage", "tonte", "paysag", "fauchage"],
    "peinture": ["peinture", "ravalement"],
    "second oeuvre": ["second oeuvre", "second œuvre", "menuiserie", "plâtrerie", "platrerie", "cloison", "carrelage", "plomberie", "électricité", "electricite"],
    "sécurité": ["gardiennage", "sécurité", "securite", "surveillance", "télésurveillance", "telesurveillance"],
}

# Statuts de prospects encore démarchables dans une campagne
_STATUTS_CIBLES = ("à contacter", "contacté", "relancé")


def detecter_secteur(objet: str) -> str | None:
    """Déduit le secteur d'activité d'un marché depuis son objet (fonction pure)."""
    texte = (objet or "").lower()
    for secteur, mots in SECTEUR_MOTS_CLES.items():
        if any(mot in texte for mot in mots):
            return secteur
    return None


def prospects_pour_marche(marche: dict[str, Any]) -> list[dict[str, Any]]:
    """Prospects de la base concernés par ce marché (même secteur, démarchables)."""
    secteur = detecter_secteur(marche.get("objet") or "")
    if not secteur:
        return []
    conn = get_connection()
    try:
        lignes = conn.execute(
            f"""
            SELECT * FROM prospects
            WHERE secteur = ? AND statut IN ({','.join('?' * len(_STATUTS_CIBLES))})
            ORDER BY entreprise
            """,
            (secteur, *_STATUTS_CIBLES),
        )
        return [dict(ligne) for ligne in lignes]
    finally:
        conn.close()


def _generer_email_template(
    marche: dict[str, Any], prospect: dict[str, Any]
) -> tuple[str, str]:
    """Email par fusion du template « déclenché par avis » (gratuit, instantané)."""
    variables = variables_depuis_marche(
        marche, prospect, jours_restants(marche.get("datelimitereponse") or "")
    )
    texte = fusionner(charger_template("declenche_par_avis.txt"), variables)
    return extraire_sujet_corps(texte)


_PROMPT_EMAIL_IA = (
    "Tu es un rédacteur de prospection B2B pour un consultant qui rédige des "
    "mémoires techniques d'appels d'offres (marchés publics français). Rédige "
    "un email court (120-180 mots), professionnel et personnalisé, proposant "
    "ce service à l'entreprise destinataire, à propos de l'appel d'offres "
    "fourni. RÈGLES : n'utilise QUE les informations fournies (n'invente ni "
    "chiffre, ni référence, ni nom) ; ne promets rien de chiffré ; termine par "
    "une question d'ouverture. FORMAT : première ligne exactement "
    "« Sujet: ... », puis une ligne vide, puis le corps."
)


def _generer_email_ia(
    client: Any, marche: dict[str, Any], prospect: dict[str, Any]
) -> tuple[str, str]:
    """Email rédigé par l'IA, personnalisé marché + prospect (~0,02 $)."""
    jours = jours_restants(marche.get("datelimitereponse") or "")
    delai = f" (dans {jours} jours)" if jours is not None else ""
    contenu = (
        "APPEL D'OFFRES\n"
        f"- Objet : {marche.get('objet') or '?'}\n"
        f"- Acheteur : {marche.get('nomacheteur') or '?'}\n"
        f"- Date limite : {marche.get('datelimitereponse') or '?'}{delai}\n"
        "\nDESTINATAIRE\n"
        f"- Entreprise : {prospect.get('entreprise')}\n"
        f"- Ville : {prospect.get('ville') or '?'}\n"
        f"- Secteur : {prospect.get('secteur') or '?'}\n"
        f"- Prénom du contact : {prospect.get('prenom_contact') or '(inconnu)'}"
    )
    reponse = client.messages.create(
        model=MODELE_DCE,
        max_tokens=800,
        system=_PROMPT_EMAIL_IA,
        messages=[{"role": "user", "content": contenu}],
    )
    texte = "".join(bloc.text for bloc in reponse.content if bloc.type == "text")
    return extraire_sujet_corps(texte.strip())


def generer_campagne(
    marche: dict[str, Any],
    cibles: list[dict[str, Any]],
    mode: str = "template",
    progression: Callable[[int, int, str], None] | None = None,
) -> int:
    """Génère et stocke un email par prospect ciblé. Retourne le nombre créé.

    mode = 'template' (fusion gratuite) ou 'ia' (rédaction personnalisée).
    Les prospects ayant déjà un email généré pour ce marché sont sautés.
    """
    client = _client_anthropic() if mode == "ia" else None
    deja = {
        e["prospect_id"] for e in lister_emails_campagne(marche["idweb"])
    }
    crees = 0
    for i, prospect in enumerate(cibles, start=1):
        if progression:
            progression(i, len(cibles), prospect["entreprise"])
        if prospect["id"] in deja:
            continue
        if mode == "ia":
            sujet, corps = _generer_email_ia(client, marche, prospect)
        else:
            sujet, corps = _generer_email_template(marche, prospect)
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO emails_generes (marche_idweb, prospect_id, sujet, corps, mode)
                VALUES (?, ?, ?, ?, ?)
                """,
                (marche["idweb"], prospect["id"], sujet, corps, mode),
            )
            conn.commit()
        finally:
            conn.close()
        crees += 1
    return crees


def lister_emails_campagne(marche_idweb: str) -> list[dict[str, Any]]:
    """Emails générés pour un marché, avec les infos du prospect jointes."""
    conn = get_connection()
    try:
        lignes = conn.execute(
            """
            SELECT e.*, p.entreprise, p.email AS email_prospect, p.statut AS statut_prospect
            FROM emails_generes e
            JOIN prospects p ON p.id = e.prospect_id
            WHERE e.marche_idweb = ?
            ORDER BY p.entreprise
            """,
            (marche_idweb,),
        )
        return [dict(ligne) for ligne in lignes]
    finally:
        conn.close()


def marquer_email_envoye(email_id: int) -> None:
    """Marque un email de campagne comme envoyé."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE emails_generes SET statut = 'envoyé' WHERE id = ?", (email_id,)
        )
        conn.commit()
    finally:
        conn.close()


def supprimer_email_campagne(email_id: int) -> None:
    """Supprime un email généré (pour le regénérer, par exemple)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM emails_generes WHERE id = ?", (email_id,))
        conn.commit()
    finally:
        conn.close()
