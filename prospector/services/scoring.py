import json
from pathlib import Path
from datetime import date


def load_scoring_config():
    config_path = Path("config/scoring.json")
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "config" / "scoring.json"
    with open(config_path) as f:
        return json.load(f)


def score_lead(lead: dict) -> int:
    """Score un lead de 0 à 100 selon les règles de config/scoring.json."""
    try:
        config = load_scoring_config()
    except Exception:
        return 50

    score = 0

    # Budget estimé
    budget = lead.get("budget_estime") or 0
    bc = config["budget"]
    if budget >= bc["seuil_tres_haut"]:
        score += bc["points_tres_haut"]
    elif budget >= bc["seuil_haut"]:
        score += bc["points_haut"]
    elif budget >= bc["seuil_moyen"]:
        score += bc["points_moyen"]
    elif budget >= bc["seuil_bas"]:
        score += bc["points_bas"]

    # Urgence (1-5)
    urgence = lead.get("urgence") or 3
    urgence = max(1, min(5, int(urgence)))
    score += urgence * config["urgence"]["points_par_niveau"]

    # Complétude coordonnées
    cc = config["coordonnees"]
    if lead.get("contact_tel"):
        score += cc["points_tel"]
    if lead.get("contact_email"):
        score += cc["points_email"]
    if lead.get("contact_nom"):
        score += cc["points_nom"]

    # Localisation Rennes Métropole
    localisation = (lead.get("localisation") or "").lower()
    for ville in config["localisation"]["villes_bonus"]:
        if ville.lower() in localisation:
            score += config["localisation"]["bonus"]
            break

    # Type de travaux
    type_travaux = (lead.get("type_travaux") or "").lower()
    for travaux_key, points in config["type_travaux"].items():
        if travaux_key.lower() in type_travaux:
            score += points
            break

    return min(100, max(0, score))


def score_artisan(artisan: dict) -> int:
    """Score la fiabilité d'un artisan de 0 à 100."""
    score = 40  # base

    # Ancienneté
    date_creation = artisan.get("date_creation")
    if date_creation:
        try:
            year = int(str(date_creation)[:4])
            years = date.today().year - year
            if years >= 10:
                score += 20
            elif years >= 5:
                score += 15
            elif years >= 3:
                score += 10
            elif years >= 1:
                score += 5
            else:
                score -= 5
        except (ValueError, TypeError):
            pass

    # Forme juridique
    forme = (artisan.get("forme_juridique") or "").upper()
    if any(f in forme for f in ["SARL", "SAS", "EURL", "SA "]):
        score += 15
    elif "EI" in forme:
        score += 8
    elif "AUTO" in forme or "MICRO" in forme:
        score += 5

    # Effectif
    effectif = artisan.get("effectif") or 0
    if effectif >= 10:
        score += 15
    elif effectif >= 5:
        score += 12
    elif effectif >= 2:
        score += 8
    elif effectif >= 1:
        score += 4

    # Historique paiement
    historique = artisan.get("historique_paiement") or "inconnu"
    if historique == "fiable":
        score += 15
    elif historique == "retardataire":
        score -= 20
    elif historique == "inconnu":
        pass

    # Contrat signé
    if artisan.get("contrat_signe"):
        score += 10

    # SIREN renseigné
    if artisan.get("siren"):
        score += 5

    return min(100, max(0, score))
