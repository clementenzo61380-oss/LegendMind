from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from database.db import get_db, rows_to_list, row_to_dict

router = APIRouter()


class ChatMessage(BaseModel):
    role: str  # "user" ou "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


class EstimateRequest(BaseModel):
    description: str


@router.post("/chat")
async def chat(req: ChatRequest):
    """Chat avec l'assistant IA — contexte base de données inclus."""
    from services.ai_service import chat_with_context

    # Construire le contexte depuis la base
    with get_db() as db:
        leads_actifs = db.execute(
            "SELECT COUNT(*) FROM leads WHERE statut NOT IN ('perdu', 'commission_payee')"
        ).fetchone()[0]
        leads_nouveaux = db.execute("SELECT COUNT(*) FROM leads WHERE statut='nouveau'").fetchone()[0]
        artisans_total = db.execute("SELECT COUNT(*) FROM artisans").fetchone()[0]
        artisans_contrat_signe = db.execute("SELECT COUNT(*) FROM artisans WHERE contrat_signe=1").fetchone()[0]

        cm_row = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(montant),0) FROM commissions WHERE statut IN ('en_attente','en_retard')"
        ).fetchone()
        commissions_en_attente = cm_row[0]
        montant_en_attente = cm_row[1]

        import datetime
        first_day = datetime.date.today().replace(day=1).isoformat()
        ca_mois = db.execute(
            "SELECT COALESCE(SUM(montant),0) FROM commissions WHERE statut='payee' AND updated_at >= ?",
            [first_day]
        ).fetchone()[0]

        leads_en_retard = db.execute(
            "SELECT COUNT(*) FROM leads WHERE statut='transmis' AND date(updated_at) <= date('now', '-7 days')"
        ).fetchone()[0]

    db_context = {
        "leads_actifs": leads_actifs,
        "leads_nouveaux": leads_nouveaux,
        "artisans_total": artisans_total,
        "artisans_contrat_signe": artisans_contrat_signe,
        "commissions_en_attente": commissions_en_attente,
        "montant_en_attente": montant_en_attente,
        "ca_mois": ca_mois,
        "leads_en_retard": leads_en_retard,
    }

    history = [{"role": m.role, "content": m.content} for m in req.history]
    result = await chat_with_context(req.message, db_context, history)
    return result


@router.post("/extract-lead")
async def extract_lead(req: EstimateRequest):
    """Extraction IA depuis un texte libre."""
    from services.ai_service import extract_lead_from_text
    return await extract_lead_from_text(req.description)


@router.post("/estimate-chantier")
async def estimate_chantier(req: EstimateRequest):
    """Estime le montant d'un chantier depuis une description."""
    from services.ai_service import get_client, MODEL
    import json

    try:
        client = get_client()
    except Exception as e:
        raise HTTPException(503, str(e))

    prompt = f"""Tu es expert en chiffrage de travaux BTP en France (région Bretagne).
Estime le coût total HT d'un chantier décrit ci-dessous.

DESCRIPTION : {req.description}

Retourne UNIQUEMENT un JSON :
{{
  "estimation_min": <montant HT minimum en euros>,
  "estimation_max": <montant HT maximum en euros>,
  "estimation_centrale": <montant HT le plus probable>,
  "type_travaux": "<qualification précise des travaux>",
  "hypotheses": "<liste des hypothèses principales>",
  "commission_5pct": <5% de l'estimation centrale>,
  "fiabilite": "<faible|moyenne|haute> selon les informations disponibles"
}}"""

    message = client.messages.create(
        model=MODEL, max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )
    text = message.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        return {"success": True, "data": json.loads(text)}
    except json.JSONDecodeError:
        return {"success": False, "raw": text}


@router.get("/drafts")
def list_drafts(type_filter: Optional[str] = None, limit: int = 20):
    """Liste tous les drafts IA générés."""
    with get_db() as db:
        where = "1=1"
        params = []
        if type_filter:
            where = "type LIKE ?"
            params.append(f"%{type_filter}%")
        drafts = rows_to_list(
            db.execute(
                f"SELECT * FROM ai_drafts WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        )
    return {"drafts": drafts, "total": len(drafts)}
