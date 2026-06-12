"""
PROSPECTOR — Système de prospection BTP / Rénovation énergétique
Apporteur d'affaires — Rennes Métropole (35)

Lancement : python app.py
Interface : http://127.0.0.1:8000
"""
import os
import sys
from pathlib import Path

# Assurer que le dossier prospector/ est dans le chemin Python
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from database.db import init_db
from routers import leads, artisans, contracts, crm, dashboard, ai_assistant


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    Path("generated_docs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # Auto-prospection en tâche de fond (open data uniquement — voir services/auto_prospect.py)
    import asyncio
    from services.auto_prospect import auto_prospect_loop
    task = asyncio.create_task(auto_prospect_loop())

    print("\n✅ PROSPECTOR démarré — http://127.0.0.1:8000\n")
    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="PROSPECTOR — Apporteur d'affaires BTP Rennes",
    description="Système de prospection BTP/Rénovation énergétique — Rennes Métropole",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers API
app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
app.include_router(artisans.router, prefix="/api/artisans", tags=["artisans"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contrats"])
app.include_router(crm.router, prefix="/api/crm", tags=["crm"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(ai_assistant.router, prefix="/api/ai", tags=["ia"])

# Fichiers statiques
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/generated_docs", StaticFiles(directory="generated_docs"), name="generated_docs")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "app": "PROSPECTOR", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=True)
