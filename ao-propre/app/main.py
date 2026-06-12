"""
Point d'entrée principal de l'application AO-Propre.
Serveur FastAPI avec templates Jinja2.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import init_db
from . import models

load_dotenv()

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="AO-Propre", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------------------------
# Tableau de bord
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    dossiers = models.lister_dossiers()
    annonces = models.lister_annonces()
    clients = models.lister_clients()

    # Statistiques rapides
    stats = {
        "total_clients": len(clients),
        "total_annonces": len(annonces),
        "dossiers_en_cours": sum(
            1 for d in dossiers
            if d["statut"] in ("en rédaction", "proposée au client", "repérée")
        ),
        "dossiers_gagnes": sum(1 for d in dossiers if d["statut"] == "gagnée"),
    }
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "stats": stats, "dossiers": dossiers[:10]},
    )


# ---------------------------------------------------------------------------
# Clients (stub — complété en Phase 2)
# ---------------------------------------------------------------------------

@app.get("/clients", response_class=HTMLResponse)
def liste_clients(request: Request):
    clients = models.lister_clients()
    return templates.TemplateResponse(
        "clients/liste.html", {"request": request, "clients": clients}
    )


@app.get("/clients/nouveau", response_class=HTMLResponse)
def nouveau_client_form(request: Request):
    return templates.TemplateResponse(
        "clients/formulaire.html", {"request": request, "client": None}
    )


@app.get("/clients/{client_id}", response_class=HTMLResponse)
def detail_client(request: Request, client_id: int):
    client = models.obtenir_client(client_id)
    if not client:
        return RedirectResponse("/clients")
    return templates.TemplateResponse(
        "clients/detail.html", {"request": request, "client": client}
    )


# ---------------------------------------------------------------------------
# Annonces (stub — complété en Phase 4)
# ---------------------------------------------------------------------------

@app.get("/annonces", response_class=HTMLResponse)
def liste_annonces(request: Request):
    annonces = models.lister_annonces()
    return templates.TemplateResponse(
        "annonces/liste.html", {"request": request, "annonces": annonces}
    )


@app.get("/annonces/{annonce_id}", response_class=HTMLResponse)
def detail_annonce(request: Request, annonce_id: int):
    annonce = models.obtenir_annonce(annonce_id)
    if not annonce:
        return RedirectResponse("/annonces")
    return templates.TemplateResponse(
        "annonces/detail.html", {"request": request, "annonce": annonce}
    )


# ---------------------------------------------------------------------------
# Dossiers (stub — complété en Phase 3)
# ---------------------------------------------------------------------------

@app.get("/dossiers", response_class=HTMLResponse)
def liste_dossiers(request: Request):
    dossiers = models.lister_dossiers()
    return templates.TemplateResponse(
        "dossiers/liste.html", {"request": request, "dossiers": dossiers}
    )


@app.get("/dossiers/{dossier_id}", response_class=HTMLResponse)
def detail_dossier(request: Request, dossier_id: int):
    dossier = models.obtenir_dossier(dossier_id)
    if not dossier:
        return RedirectResponse("/dossiers")
    historique = models.historique_dossier(dossier_id)
    return templates.TemplateResponse(
        "dossiers/detail.html",
        {"request": request, "dossier": dossier, "historique": historique},
    )
