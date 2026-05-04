from __future__ import annotations
import os, asyncio
from typing import Optional, Tuple
from dotenv import load_dotenv
load_dotenv()
GROQ_KEY = os.getenv("GROQ_API_KEY","")
GEMINI_KEY = os.getenv("GEMINI_API_KEY","")

COC_SYSTEM = (
    "Tu es ClashBot, expert Clash of Clans 2025. "
    "Reponds UNIQUEMENT avec de vraies troupes officielles CoC : "
    "Barbare, Archer, Geant, Gobelin, Briseur de mur, Ballon, Sorcier, Guerisseuse, "
    "Dragon, PEKKA, Mini PEKKA, Golem, Valkyrie, Golem de lave, Witch, Bowler, Mineurs, "
    "Electro Dragon, Yeti, Dragon de glace, Cavalier Racine, Super troupes. "
    "Heros officiels : Roi Barbare, Reine des Archers, Grand Faucon, Marionnettiste Royal, Champion. "
    "N invente AUCUN nom. HDV max : 18. Reponds en francais, simplement et avec fun. "
    "Donne des quantites precises de troupes adaptees a la capacite d armee du HDV concerne."
)

async def ask_groq(prompt: str) -> Tuple[Optional[str], str, float]:
    if not GROQ_KEY:
        return None, "groq", 0.0
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_KEY)
        r = await asyncio.to_thread(lambda: client.chat.completions.create(
            messages=[{"role":"user","content":COC_SYSTEM+"\n\n"+prompt}],
            model="llama-3.3-70b-versatile", max_tokens=1500))
        text = r.choices[0].message.content
        if text and len(text.strip()) > 20:
            return text.strip(), "groq-llama3", 0.0
    except Exception as e:
        print("[Groq]",e)
    return None, "groq", 0.0

async def ask_gemini(prompt: str) -> Tuple[Optional[str], str, float]:
    if not GEMINI_KEY:
        return None, "gemini", 0.0
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_KEY)
        r = await asyncio.to_thread(lambda: client.models.generate_content(
            model="gemini-1.5-flash", contents=COC_SYSTEM+"\n\n"+prompt))
        text = r.text
        if text and len(text.strip()) > 20:
            return text.strip(), "gemini-1.5-flash", 0.0001
    except Exception as e:
        print("[Gemini]",e)
    return None, "gemini", 0.0

async def ask_ai(prompt: str) -> Tuple[str, str, float]:
    for fn in [ask_groq, ask_gemini]:
        result, model, cost = await fn(prompt)
        if result:
            return result, model, cost
    return "IAs indisponibles, reessaie dans quelques secondes !", "none", 0.0
