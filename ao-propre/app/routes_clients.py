"""
Routes du module Fiches clients : CRUD complet, logo, pièces administratives.
"""
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates

from . import models
from .utils import (
    slugifier, chemin_client, preparer_dossier_client,
    verifier_pieces, logo_existe, PIECES_ADMINISTRATIVES,
)

router = APIRouter(prefix="/clients", tags=["clients"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Départements proposés dans le formulaire (zones d'intervention)
DEPARTEMENTS_BRETAGNE = [
    ("22", "Côtes-d'Armor"),
    ("29", "Finistère"),
    ("35", "Ille-et-Vilaine"),
    ("56", "Morbihan"),
]

# Champs texte simples du formulaire, mappés 1:1 sur les colonnes SQL
CHAMPS_SIMPLES = [
    "nom", "siret", "adresse", "code_postal", "ville", "telephone",
    "email", "site_web", "materiels", "produits_utilises",
    "demarche_qualite", "politique_rse", "references_clients",
    "assureur", "numero_police",
    "contact_nom", "contact_poste", "contact_telephone", "contact_email",
]


def _extraire_donnees(form) -> dict:
    """Construit le dict de colonnes SQL à partir du formulaire HTML."""
    donnees = {}
    for champ in CHAMPS_SIMPLES:
        valeur = (form.get(champ) or "").strip()
        donnees[champ] = valeur or None

    # Champs numériques : vides -> NULL
    for champ in ("effectif", "annee_creation"):
        valeur = (form.get(champ) or "").strip()
        donnees[champ] = int(valeur) if valeur.isdigit() else None
    for champ in ("ca_annuel", "montant_garantie"):
        valeur = (form.get(champ) or "").strip().replace(",", ".")
        try:
            donnees[champ] = float(valeur) if valeur else None
        except ValueError:
            donnees[champ] = None

    # Listes -> JSON (zones d'intervention = cases à cocher, certifications = texte multi-lignes)
    zones = form.getlist("zones_intervention")
    donnees["zones_intervention"] = json.dumps(zones) if zones else None
    certifs = [c.strip() for c in (form.get("certifications") or "").splitlines() if c.strip()]
    donnees["certifications"] = json.dumps(certifs) if certifs else None

    return donnees


def _contexte_client(row) -> dict:
    """Convertit une ligne SQL en dict avec les champs JSON décodés."""
    client = dict(row)
    client["zones_liste"] = json.loads(client["zones_intervention"]) if client.get("zones_intervention") else []
    client["certifs_liste"] = json.loads(client["certifications"]) if client.get("certifications") else []
    return client


# ---------------------------------------------------------------------------
# Liste et création
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
def liste_clients(request: Request):
    clients = models.lister_clients()
    return templates.TemplateResponse(
        "clients/liste.html", {"request": request, "clients": clients}
    )


@router.get("/nouveau", response_class=HTMLResponse)
def nouveau_client_form(request: Request):
    return templates.TemplateResponse(
        "clients/formulaire.html",
        {"request": request, "client": None, "departements": DEPARTEMENTS_BRETAGNE},
    )


@router.post("", response_class=HTMLResponse)
async def creer_client(request: Request):
    form = await request.form()
    donnees = _extraire_donnees(form)
    if not donnees.get("nom"):
        return RedirectResponse("/clients/nouveau", status_code=303)

    # Slug unique : on suffixe avec un compteur en cas de collision
    base = slugifier(donnees["nom"])
    slug, i = base, 2
    while models.obtenir_client_par_slug(slug):
        slug = f"{base}-{i}"
        i += 1
    donnees["slug"] = slug

    client_id = models.creer_client(donnees)
    preparer_dossier_client(slug)
    return RedirectResponse(f"/clients/{client_id}", status_code=303)


# ---------------------------------------------------------------------------
# Détail, modification, suppression
# ---------------------------------------------------------------------------

@router.get("/{client_id}", response_class=HTMLResponse)
def detail_client(request: Request, client_id: int):
    row = models.obtenir_client(client_id)
    if not row:
        return RedirectResponse("/clients", status_code=303)
    client = _contexte_client(row)
    return templates.TemplateResponse(
        "clients/detail.html",
        {
            "request": request,
            "client": client,
            "pieces": verifier_pieces(client["slug"]),
            "a_logo": logo_existe(client["slug"]),
        },
    )


@router.get("/{client_id}/modifier", response_class=HTMLResponse)
def modifier_client_form(request: Request, client_id: int):
    row = models.obtenir_client(client_id)
    if not row:
        return RedirectResponse("/clients", status_code=303)
    return templates.TemplateResponse(
        "clients/formulaire.html",
        {"request": request, "client": _contexte_client(row), "departements": DEPARTEMENTS_BRETAGNE},
    )


@router.post("/{client_id}", response_class=HTMLResponse)
async def modifier_client(request: Request, client_id: int):
    row = models.obtenir_client(client_id)
    if not row:
        return RedirectResponse("/clients", status_code=303)
    form = await request.form()
    donnees = _extraire_donnees(form)
    donnees.pop("nom", None) if not donnees.get("nom") else None
    # Le slug ne change jamais après création : les chemins de fichiers en dépendent
    models.mettre_a_jour_client(client_id, donnees)
    return RedirectResponse(f"/clients/{client_id}", status_code=303)


@router.post("/{client_id}/supprimer")
def supprimer_client(client_id: int):
    row = models.obtenir_client(client_id)
    if row:
        # Suppression en base uniquement ; les fichiers restent sur disque par sécurité
        models.supprimer_client(client_id)
    return RedirectResponse("/clients", status_code=303)


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

@router.post("/{client_id}/logo")
async def televerser_logo(client_id: int, logo: UploadFile = File(...)):
    row = models.obtenir_client(client_id)
    if not row:
        return RedirectResponse("/clients", status_code=303)
    preparer_dossier_client(row["slug"])
    destination = chemin_client(row["slug"]) / "logo.png"
    with destination.open("wb") as f:
        shutil.copyfileobj(logo.file, f)
    return RedirectResponse(f"/clients/{client_id}", status_code=303)


@router.get("/{client_id}/logo")
def afficher_logo(client_id: int):
    row = models.obtenir_client(client_id)
    if row:
        logo = chemin_client(row["slug"]) / "logo.png"
        if logo.exists():
            return FileResponse(str(logo), media_type="image/png")
    return RedirectResponse("/static/logo-defaut.png", status_code=303)


# ---------------------------------------------------------------------------
# Pièces administratives
# ---------------------------------------------------------------------------

@router.post("/{client_id}/pieces/{cle}")
async def televerser_piece(client_id: int, cle: str, fichier: UploadFile = File(...)):
    row = models.obtenir_client(client_id)
    cles_valides = {c for c, _ in PIECES_ADMINISTRATIVES}
    if not row or cle not in cles_valides:
        return RedirectResponse("/clients", status_code=303)

    docs = preparer_dossier_client(row["slug"])
    # Le fichier est renommé <cle><extension> pour être détecté par verifier_pieces
    extension = Path(fichier.filename or "").suffix or ".pdf"
    destination = docs / f"{cle}{extension}"
    with destination.open("wb") as f:
        shutil.copyfileobj(fichier.file, f)
    return RedirectResponse(f"/clients/{client_id}", status_code=303)


@router.get("/{client_id}/pieces/{nom_fichier}")
def telecharger_piece(client_id: int, nom_fichier: str):
    row = models.obtenir_client(client_id)
    if row:
        # Path(nom).name neutralise toute tentative de traversée de répertoire
        fichier = chemin_client(row["slug"]) / "docs" / Path(nom_fichier).name
        if fichier.exists():
            return FileResponse(str(fichier), filename=fichier.name)
    return RedirectResponse(f"/clients/{client_id}", status_code=303)
