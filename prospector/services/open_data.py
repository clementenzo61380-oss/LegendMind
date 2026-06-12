"""
Module de veille open data — Permis de construire et déclarations préalables
Source : data.gouv.fr / Sitadel (DGALN)
⚠️  Aucun scraping : uniquement des APIs publiques légales.
"""
import httpx
from datetime import datetime, timedelta
from typing import Optional


SITADEL_DATASET_ID = "sitadel-permis-de-construire-et-permis-de-demolir"
DATAGOUV_API = "https://www.data.gouv.fr/api/1"
TABULAR_API = "https://tabular-api.data.gouv.fr/api/resources"

# Codes INSEE Rennes Métropole (communes principales)
COMMUNES_RENNES_METRO = {
    "35238": "Rennes",
    "35051": "Bruz",
    "35055": "Cesson-Sévigné",
    "35281": "Saint-Grégoire",
    "35235": "Pacé",
    "35024": "Betton",
    "35342": "Thorigné-Fouillard",
    "35001": "Acigné",
    "35344": "Vezin-le-Coquet",
    "35195": "Noyal-Châtillon-sur-Seiche",
    "35189": "Mordelles",
    "35249": "Saint-Jacques-de-la-Lande",
}


async def fetch_permis_construire(
    commune: str = "Rennes",
    code_dept: str = "35",
    limit: int = 20
) -> dict:
    """
    Récupère les permis de construire récents depuis data.gouv.fr / Sitadel.
    Retourne une liste de leads potentiels.
    """
    results = []
    errors = []

    # Chercher le dataset Sitadel sur data.gouv.fr
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Recherche du dataset
            search_resp = await client.get(
                f"{DATAGOUV_API}/datasets/",
                params={"q": "sitadel permis construire", "page_size": 5}
            )
            if search_resp.status_code != 200:
                raise Exception(f"data.gouv.fr HTTP {search_resp.status_code}")
            datasets = search_resp.json().get("data", [])

            resource_id = None
            for ds in datasets:
                if "sitadel" in ds.get("title", "").lower() or "permis" in ds.get("title", "").lower():
                    resources = ds.get("resources", [])
                    for res in resources:
                        if res.get("format", "").lower() in ["csv", "json"] and "dep" in res.get("url", "").lower():
                            resource_id = res.get("id")
                            break
                    if resource_id:
                        break

            # Si on a trouvé un resource ID, on interroge l'API tabulaire
            if resource_id:
                tabular_resp = await client.get(
                    f"{TABULAR_API}/{resource_id}/data/",
                    params={
                        "dep_enquete": code_dept,
                        "page_size": limit,
                        "page": 1,
                    }
                )
                if tabular_resp.status_code == 200:
                    data = tabular_resp.json()
                    for row in data.get("data", []):
                        lead = _parse_sitadel_row(row)
                        if lead:
                            results.append(lead)

    except httpx.TimeoutException:
        errors.append("Timeout lors de la connexion à data.gouv.fr")
    except Exception as e:
        errors.append(f"Erreur API data.gouv.fr : {str(e)}")

    # Si pas de résultats via API tabulaire, retourner des données démo
    if not results:
        results = _get_demo_permits(commune, limit)
        errors.append(
            "API Sitadel non disponible — données de démonstration affichées. "
            "En production, les vrais permis apparaîtront ici."
        )

    return {
        "source": "data.gouv.fr / Sitadel",
        "commune": commune,
        "departement": code_dept,
        "count": len(results),
        "leads": results,
        "errors": errors,
        "fetched_at": datetime.now().isoformat(),
    }


def _parse_sitadel_row(row: dict) -> Optional[dict]:
    """Convertit une ligne Sitadel en format lead."""
    try:
        type_op = row.get("type_op", "") or row.get("lib_type_op", "")
        nature = row.get("lib_nature_permis", "") or row.get("nature_permis", "")
        commune_nom = row.get("lib_commune", "") or row.get("nom_commune", "")
        date_depot = row.get("date_depot_reelle", "") or row.get("date_depot", "")
        surface = row.get("shon_totale", 0) or row.get("surface", 0)

        # Estimer le budget selon la surface
        try:
            surface = float(surface) if surface else 0
        except (ValueError, TypeError):
            surface = 0

        budget_estime = surface * 1500 if surface > 0 else 0

        return {
            "source": "open_data",
            "type_travaux": f"{nature} — {type_op}".strip(" —"),
            "localisation": commune_nom or "Rennes Métropole",
            "budget_estime": budget_estime,
            "urgence": 3,
            "notes": f"Permis déposé le {date_depot}. Surface : {surface} m².",
            "raw_text": str(row),
        }
    except Exception:
        return None


def _get_demo_permits(commune: str, limit: int) -> list:
    """Données de démonstration quand l'API n'est pas accessible."""
    today = datetime.now()
    demos = []
    exemples = [
        {
            "type_travaux": "Construction neuve — maison individuelle",
            "localisation": f"{commune} / Rennes Métropole",
            "budget_estime": 280000,
            "urgence": 3,
            "notes": f"Permis de construire déposé le {(today - timedelta(days=10)).strftime('%d/%m/%Y')}. Surface estimée : 140 m².",
        },
        {
            "type_travaux": "Extension — surélévation",
            "localisation": f"Cesson-Sévigné",
            "budget_estime": 85000,
            "urgence": 3,
            "notes": f"Déclaration préalable déposée le {(today - timedelta(days=5)).strftime('%d/%m/%Y')}. Surface : 45 m².",
        },
        {
            "type_travaux": "Rénovation énergétique — isolation + PAC",
            "localisation": f"Saint-Grégoire",
            "budget_estime": 35000,
            "urgence": 4,
            "notes": f"Permis déposé le {(today - timedelta(days=3)).strftime('%d/%m/%Y')}. Aide MaPrimeRénov' probable.",
        },
        {
            "type_travaux": "Aménagement combles — menuiseries",
            "localisation": f"Bruz",
            "budget_estime": 55000,
            "urgence": 2,
            "notes": f"Déclaration préalable déposée le {(today - timedelta(days=12)).strftime('%d/%m/%Y')}. Surface : 60 m².",
        },
        {
            "type_travaux": "Construction neuve — maison individuelle",
            "localisation": f"Pacé",
            "budget_estime": 320000,
            "urgence": 3,
            "notes": f"Permis déposé le {(today - timedelta(days=8)).strftime('%d/%m/%Y')}. Surface : 160 m².",
        },
    ]

    for i, ex in enumerate(exemples[:limit]):
        demos.append({
            "source": "open_data_demo",
            **ex,
            "contact_nom": None,
            "contact_tel": None,
            "contact_email": None,
            "raw_text": f"[DEMO] {ex['type_travaux']} à {ex['localisation']}",
        })

    return demos
