"""
Enrichissement via l'API Sirene / recherche-entreprises.api.gouv.fr
API gratuite, pas de clé requise.
"""
import httpx
from typing import Optional


RECHERCHE_ENTREPRISES_API = "https://recherche-entreprises.api.gouv.fr/search"


async def enrich_from_siren(siren: str) -> dict:
    """
    Interroge l'API recherche-entreprises pour enrichir une fiche artisan.
    Retourne un dict avec les données enrichies ou un dict vide si introuvable.
    """
    siren = siren.replace(" ", "").replace("-", "").strip()
    if len(siren) != 9 or not siren.isdigit():
        return {"error": f"SIREN invalide : '{siren}' (doit être 9 chiffres)"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                RECHERCHE_ENTREPRISES_API,
                params={"q": siren, "page": 1, "per_page": 1}
            )

            if resp.status_code != 200:
                return {"error": f"API Sirene — HTTP {resp.status_code}"}

            data = resp.json()
            results = data.get("results", [])

            if not results:
                return {"error": f"SIREN {siren} introuvable dans Sirene"}

            entreprise = results[0]
            return _parse_entreprise(entreprise)

    except httpx.TimeoutException:
        return {"error": "Timeout — API Sirene non disponible"}
    except Exception as e:
        return {"error": f"Erreur API Sirene : {str(e)}"}


def _parse_entreprise(e: dict) -> dict:
    """Transforme la réponse API en données structurées pour PROSPECTOR."""
    matching = e.get("matching_etablissements", [{}])
    etab = matching[0] if matching else {}

    # Nom
    nom = (
        e.get("nom_complet")
        or e.get("nom_raison_sociale")
        or f"{e.get('prenom_usuel', '')} {e.get('nom', '')}".strip()
        or "Inconnu"
    )

    # Forme juridique
    nature = e.get("nature_juridique", "")
    forme = _nature_to_forme(nature)

    # Date de création
    date_creation = e.get("date_creation", "")

    # Effectif
    tranche = e.get("tranche_effectif_salarie", "")
    effectif = _tranche_to_effectif(tranche)

    # Adresse
    adresse = etab.get("adresse") or e.get("siege", {}).get("adresse", "")
    ville = etab.get("libelle_commune") or e.get("siege", {}).get("libelle_commune", "")
    code_postal = etab.get("code_postal") or e.get("siege", {}).get("code_postal", "")

    # Activité principale
    activite = e.get("activite_principale", "")
    lib_activite = e.get("libelle_activite_principale", "")

    return {
        "nom": nom,
        "siren": e.get("siren", ""),
        "forme_juridique": forme,
        "date_creation": date_creation,
        "effectif": effectif,
        "adresse": adresse,
        "ville": ville or code_postal,
        "code_postal": code_postal,
        "activite_principale": f"{activite} — {lib_activite}".strip(" —"),
        "enrichi": True,
    }


def _nature_to_forme(code: str) -> str:
    mapping = {
        "1000": "Entrepreneur individuel (EI)",
        "2110": "SARL",
        "2120": "SARL",
        "5499": "SARL",
        "5710": "SAS",
        "5720": "SAS",
        "5770": "SAS",
        "5785": "SASU",
        "6540": "SA",
        "1100": "Micro-entrepreneur",
        "1110": "Micro-entrepreneur",
    }
    return mapping.get(str(code), f"Code {code}" if code else "Non renseigné")


def _tranche_to_effectif(tranche: str) -> int:
    mapping = {
        "00": 0, "01": 1, "02": 3, "03": 6, "11": 10,
        "12": 20, "21": 50, "22": 100, "31": 200, "32": 250,
        "41": 500, "42": 1000, "51": 2000, "52": 5000, "53": 10000,
    }
    return mapping.get(str(tranche), 0)
