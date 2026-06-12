"""
Service IA — Wrapper Anthropic API
Modèle : claude-sonnet-4-6
Toutes les opérations IA passent par ce module.
"""
import os
import json
from typing import Optional

try:
    import anthropic
    _CLIENT = None

    def get_client():
        global _CLIENT
        if _CLIENT is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY non définie dans .env")
            _CLIENT = anthropic.Anthropic(api_key=api_key)
        return _CLIENT

    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


MODEL = "claude-sonnet-4-6"
APPORTEUR_NOM = os.getenv("APPORTEUR_NOM", "l'apporteur d'affaires")
COMMISSION_DEFAUT = float(os.getenv("COMMISSION_DEFAUT", "5.0"))


def _check_ai():
    if not AI_AVAILABLE:
        raise RuntimeError("Le package 'anthropic' n'est pas installé. Lancez : pip install anthropic")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY non définie dans le fichier .env")


async def extract_lead_from_text(text: str) -> dict:
    """
    Extrait les informations d'un lead depuis un texte libre (post FB, annonce, conversation).
    Retourne un dict structuré pour pré-remplir le formulaire de création de lead.
    """
    _check_ai()

    prompt = f"""Tu es un assistant pour un apporteur d'affaires BTP en France (région Rennes, 35).
Analyse le texte suivant et extrait les informations pour créer une fiche lead.

TEXTE :
{text}

Retourne UNIQUEMENT un JSON valide avec ces champs (null si non trouvé) :
{{
  "type_travaux": "description courte des travaux (ex: Isolation toiture, PAC air/eau, Extension)",
  "budget_estime": <nombre en euros ou null>,
  "localisation": "ville/adresse si mentionnée, sinon null",
  "urgence": <1=pas urgent, 2=quelques mois, 3=normal, 4=bientôt, 5=immédiat — inférer depuis le texte>,
  "contact_nom": "prénom nom si présent, sinon null",
  "contact_tel": "numéro de téléphone si présent, sinon null",
  "contact_email": "email si présent, sinon null",
  "notes": "informations utiles supplémentaires (contraintes, aide MaPrimeRénov, copropriété, etc.)",
  "montant_chantier_estime": <estimation du montant total chantier en euros si possible, sinon null>
}}

Règles :
- Pour le budget : si une fourchette est donnée, prends la médiane
- Pour l'urgence : "dès que possible" = 5, "sous 3 mois" = 4, "cette année" = 3, "pas pressé" = 2
- Pour le type de travaux : sois précis (ex: "Rénovation salle de bain" plutôt que "travaux")
- Si le montant chantier n'est pas explicite, estime-le selon le type de travaux (m², nature)
- Retourne UNIQUEMENT le JSON, sans explication"""

    client = get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()

    # Nettoyer si besoin (blocs markdown)
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(response_text)
        data["source"] = "manual"
        data["raw_text"] = text
        return {"success": True, "data": data}
    except json.JSONDecodeError:
        return {
            "success": False,
            "error": "L'IA n'a pas retourné un JSON valide",
            "raw": response_text
        }


async def generate_artisan_message(artisan: dict, type_message: str = "email") -> dict:
    """
    Génère un message d'approche personnalisé pour un artisan.
    type_message : 'email' ou 'sms'
    ⚠️ DRAFT UNIQUEMENT — jamais envoyé automatiquement.
    """
    _check_ai()

    nom = artisan.get("nom", "")
    metier = artisan.get("metier", "")
    ville = artisan.get("ville", "Rennes")
    forme = artisan.get("forme_juridique", "")
    effectif = artisan.get("effectif", 0) or 0
    apporteur = APPORTEUR_NOM
    commission = COMMISSION_DEFAUT

    taille = "artisan indépendant"
    if effectif >= 5:
        taille = f"entreprise de {effectif} salariés"
    elif effectif >= 2:
        taille = f"entreprise de {effectif} personnes"

    if type_message == "sms":
        longueur = "160 caractères maximum, direct et percutant"
        format_sortie = "SMS unique"
    else:
        longueur = "8-12 lignes maximum, ton direct et professionnel"
        format_sortie = "email complet avec objet"

    prompt = f"""Tu es {apporteur}, apporteur d'affaires BTP dans la région de {ville} (35).
Tu veux contacter un artisan pour lui proposer un partenariat.

PROFIL ARTISAN :
- Nom/Société : {nom}
- Métier : {metier}
- Ville : {ville}
- Type : {taille}
- Forme juridique : {forme}

Rédige un {type_message} d'approche ({longueur}).

TON PITCH :
- Tu lui apportes des chantiers qualifiés, déjà intéressés
- Il ne paye QUE si le devis est signé et l'acompte versé (commission de {commission}%)
- Zéro risque financier pour lui
- Pas de prospection à faire, juste répondre aux opportunités

FORMAT DE SORTIE :
{format_sortie}
Langue : Français, ton direct, pas de blabla corporate
Évite les formules pompeuses ("Je me permets de...", "Suite à notre conversation...")
Commence direct : "Bonjour [prénom si connu],"

⚠️ IMPORTANT : Retourne UNIQUEMENT le texte du message, sans explication."""

    client = get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    contenu = message.content[0].text.strip()
    return {
        "success": True,
        "type": type_message,
        "contenu": contenu,
        "artisan_nom": nom,
    }


async def generate_transmission_email(lead: dict, artisan: dict, apporteur_info: dict) -> dict:
    """
    Génère l'email de transmission horodaté (preuve de transmission).
    ⚠️ DRAFT UNIQUEMENT — jamais envoyé automatiquement.
    """
    from datetime import datetime
    date_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    apporteur_nom = apporteur_info.get("nom", APPORTEUR_NOM)
    contrat_date = apporteur_info.get("contrat_date", "")

    contenu = f"""Objet : Transmission de lead — {lead.get('type_travaux', 'Travaux')} — {date_str}

Bonjour,

Je vous transmets ce jour, le {date_str}, le contact suivant, conformément à notre contrat de partenariat{f" du {contrat_date}" if contrat_date else ""} :

── FICHE LEAD ──────────────────────────────
Contact     : {lead.get('contact_nom') or 'À qualifier'}
Téléphone   : {lead.get('contact_tel') or 'Non renseigné'}
Email       : {lead.get('contact_email') or 'Non renseigné'}
Localisation: {lead.get('localisation') or 'Rennes Métropole'}
Travaux     : {lead.get('type_travaux') or 'À définir'}
Budget estimé: {f"{lead.get('budget_estime'):,.0f} €" if lead.get('budget_estime') else 'À qualifier'}
Urgence     : {lead.get('urgence') or 3}/5
Notes       : {lead.get('notes') or '—'}
────────────────────────────────────────────

Merci de me confirmer la prise en charge de ce contact dans les 48h et de m'informer de l'issue de votre démarche commerciale (devis émis, signé, ou projet abandonné), conformément à nos engagements contractuels.

Cordialement,
{apporteur_nom}
"""

    return {
        "success": True,
        "type": "transmission",
        "contenu": contenu,
        "subject": f"Transmission lead — {lead.get('type_travaux', 'Travaux')} — {date_str}",
        "to": artisan.get("email", ""),
    }


async def generate_relance(commission: dict, lead: dict, artisan: dict, niveau: int) -> dict:
    """
    Génère un message de relance commission.
    niveau 1 = J+30 amiable, niveau 2 = J+45 ferme, niveau 3 = J+60 mise en demeure
    ⚠️ DRAFT UNIQUEMENT.
    """
    _check_ai()

    apporteur_nom = APPORTEUR_NOM
    artisan_nom = artisan.get("nom", "")
    montant = commission.get("montant", 0)
    date_echeance = commission.get("date_echeance", "")
    lead_type = lead.get("type_travaux", "travaux")
    lead_contact = lead.get("contact_nom", "le client transmis")

    niveaux = {
        1: ("relance amiable (J+30)", "courtois mais rappelant l'échéance contractuelle"),
        2: ("relance ferme (J+45)", "ferme, citant les termes du contrat, demandant un règlement immédiat"),
        3: ("mise en demeure (J+60)", "juridiquement formel, mentionnant les voies de recours possibles"),
    }
    label, ton = niveaux.get(niveau, niveaux[1])

    prompt = f"""Tu es {apporteur_nom}, apporteur d'affaires BTP.
Tu dois rédiger un email de {label} pour le paiement d'une commission impayée.

CONTEXTE :
- Artisan : {artisan_nom}
- Lead transmis : {lead_contact} — {lead_type}
- Commission due : {montant:.2f} €
- Échéance : {date_echeance}
- Niveau de relance : {niveau}/3

Rédige un email {ton}.
Français, direct, professionnel.
Inclure : objet + corps du message.
Retourne UNIQUEMENT le texte de l'email."""

    client = get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )

    contenu = message.content[0].text.strip()
    return {
        "success": True,
        "niveau": niveau,
        "label": label,
        "contenu": contenu,
        "artisan_nom": artisan_nom,
        "montant": montant,
    }


async def chat_with_context(message: str, db_context: dict, history: list) -> dict:
    """
    Chat assistant IA avec accès au contexte de la base de données.
    """
    _check_ai()

    system_prompt = f"""Tu es PROSPECTOR AI, l'assistant de {APPORTEUR_NOM}, apporteur d'affaires BTP à Rennes (35).
Tu as accès aux données actuelles de son activité.

CONTEXTE ACTUEL :
- Leads actifs : {db_context.get('leads_actifs', 0)}
- Leads nouveaux : {db_context.get('leads_nouveaux', 0)}
- Artisans partenaires : {db_context.get('artisans_total', 0)} dont {db_context.get('artisans_contrat_signe', 0)} avec contrat signé
- Commissions en attente : {db_context.get('commissions_en_attente', 0)} ({db_context.get('montant_en_attente', 0):.0f} €)
- CA encaissé ce mois : {db_context.get('ca_mois', 0):.0f} €
- Leads sans nouvelle > 7 jours : {db_context.get('leads_en_retard', 0)}

Tu peux :
- Rédiger des relances, emails, messages
- Analyser un lead décrit par l'utilisateur
- Suggérer des artisans selon un type de travaux
- Estimer le panier d'un chantier
- Donner des conseils métier (prospection, négociation, contrats)

Sois direct, concis, en français. Pas de blabla."""

    messages_for_api = []
    for h in history[-10:]:  # Garder les 10 derniers messages
        messages_for_api.append({
            "role": h["role"],
            "content": h["content"]
        })
    messages_for_api.append({"role": "user", "content": message})

    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=messages_for_api
    )

    return {
        "success": True,
        "response": response.content[0].text,
    }


async def suggest_artisan(lead: dict, artisans: list) -> dict:
    """
    Suggère le meilleur artisan pour un lead donné.
    """
    _check_ai()

    if not artisans:
        return {"success": False, "error": "Aucun artisan dans la base"}

    artisans_desc = "\n".join([
        f"- ID {a['id']}: {a['nom']} — {a['metier']} — {a['ville']} — Score fiabilité: {a['score_fiabilite']}/100 — Contrat: {'Oui' if a.get('contrat_signe') else 'Non'}"
        for a in artisans[:20]
    ])

    prompt = f"""Tu es un assistant pour un apporteur d'affaires BTP à Rennes.
Voici un lead à transmettre :

LEAD :
- Travaux : {lead.get('type_travaux', '')}
- Localisation : {lead.get('localisation', '')}
- Budget estimé : {lead.get('budget_estime', 0)} €
- Notes : {lead.get('notes', '')}

ARTISANS DISPONIBLES :
{artisans_desc}

Indique les 2-3 artisans les plus adaptés (par ID) avec une justification courte.
Retourne un JSON :
{{
  "suggestions": [
    {{"id": <id>, "nom": "<nom>", "raison": "<justification courte>"}},
    ...
  ]
}}"""

    client = get_client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(response_text)
        return {"success": True, **data}
    except json.JSONDecodeError:
        return {"success": True, "suggestions": [], "raw": response_text}
