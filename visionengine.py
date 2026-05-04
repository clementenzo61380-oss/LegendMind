import os, sqlite3, asyncio, base64, json, re, io, requests
from groq import Groq
from PIL import Image
from dotenv import load_dotenv
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DB_PATH = "coc-bot.db"


def compress_image(image_url: str) -> str:
    resp = requests.get(image_url, timeout=10)
    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=35)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def detect_base(image_url: str) -> dict:
    b64 = await asyncio.to_thread(compress_image, image_url)
    prompt = """Tu es un expert Clash of Clans TH18.
Analyse ce screenshot et réponds UNIQUEMENT en JSON :
{
  "type_base": "box ou ring ou diamond ou anti3 ou anti2 ou inconnu",
  "defenses_visibles": ["Eagle Artillery", "Monolith", "Vengeance Tower", ...],
  "position_eagle": "centre ou 3h ou 6h ou 9h ou 12h ou inconnu",
  "position_mairie": "centre ou bord ou inconnu",
  "air_expo": true ou false,
  "compartiments": "ouverts ou fermes ou mixtes ou inconnu"
}
RÈGLE ABSOLUE : N'invente aucune défense. Si tu ne vois pas → inconnu."""
    try:
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}],
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0.1,
            max_tokens=400
        )
        raw = completion.choices[0].message.content
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group()) if match else {"type_base": "inconnu"}
    except Exception as e:
        return {"type_base": "inconnu", "erreur": str(e)}


def get_transcript(video_id: str) -> str:
    """Récupère la transcription YouTube si disponible"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["fr", "en"])
        return " ".join([t["text"] for t in transcript[:120]])
    except:
        return ""


def extract_video_id(lien: str) -> str:
    match = re.search(r"v=([a-zA-Z0-9_-]{11})", lien)
    return match.group(1) if match else ""


def search_youtube(query: str, max_results: int = 5) -> list:
    if not YOUTUBE_API_KEY:
        return []
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        resp = yt.search().list(
            part="snippet",
            q=query,
            maxResults=max_results,
            type="video",
            publishedAfter="2025-01-01T00:00:00Z",
            order="relevance"
        ).execute()
        results = []
        for item in resp.get("items", []):
            titre = item["snippet"]["title"]
            if not re.search(r'TH18|HDV18|TH\s*18|HDV\s*18|Town Hall 18', titre, re.IGNORECASE):
                continue
            results.append({
                "video_id": item["id"]["videoId"],
                "titre": titre,
                "lien": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                "chaine": item["snippet"]["channelTitle"],
                "date": item["snippet"]["publishedAt"][:10],
                "description": item["snippet"].get("description", "")
            })
        return results
    except Exception as e:
        print(f"[YouTube] {e}")
        return []


def score_video(video: dict, detection: dict) -> float:
    score = 0.0
    texte = (video.get("titre", "") + " " + video.get("description", "")).lower()
    type_base = detection.get("type_base", "inconnu").lower()
    defenses = [d.lower() for d in detection.get("defenses_visibles", [])]

    if type_base != "inconnu" and type_base in texte:
        score += 0.40
    for d in defenses:
        if d in texte:
            score += 0.08
    chaines_pro = ["blueprint", "itzu", "judo sloth", "kenny jo", "carbonfin",
                   "ash", "ds gaming", "peter17", "gaku"]
    if any(p in video.get("chaine", "").lower() for p in chaines_pro):
        score += 0.20
    if "2026" in video.get("date", ""):
        score += 0.10
    for kw in ["3 star", "war", "gdc", "cwl", "legend", "pro", "attack"]:
        if kw in texte:
            score += 0.04
    return min(score, 1.0)


def search_sqlite(type_base: str) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT titre, lien, chaine, type_base, date_publication, pertinence_score
            FROM youtube_th18
            WHERE type_base LIKE ? OR titre LIKE ?
            ORDER BY pertinence_score DESC, date_publication DESC
            LIMIT 5
        """, (f"%{type_base}%", "%TH18%"))
        rows = c.fetchall()
        conn.close()
        return [{"titre": r[0], "lien": r[1], "chaine": r[2],
                 "type_base": r[3], "date": r[4], "score": r[5]} for r in rows]
    except:
        return []


async def generate_strategy_from_transcripts(videos: list, detection: dict) -> str:
    """
    Génère une stratégie UNIQUEMENT à partir des transcriptions réelles
    des vidéos similaires. Zéro invention.
    """
    type_base = detection.get("type_base", "inconnu")
    defenses = detection.get("defenses_visibles", [])
    position_eagle = detection.get("position_eagle", "inconnu")

    # Récupère les transcriptions des 3 meilleures vidéos
    transcriptions = []
    for v in videos[:3]:
        video_id = v.get("video_id") or extract_video_id(v.get("lien", ""))
        if video_id:
            transcript = await asyncio.to_thread(get_transcript, video_id)
            if transcript:
                transcriptions.append({
                    "titre": v["titre"],
                    "lien": v["lien"],
                    "chaine": v.get("chaine", "?"),
                    "texte": transcript[:800]
                })

    if not transcriptions:
        return None  # Pas de transcription = pas de stratégie

    # Contexte de la base détectée
    base_context = f"Type: {type_base}"
    if defenses:
        base_context += f", Défenses: {', '.join(defenses[:5])}"
    if position_eagle != "inconnu":
        base_context += f", Eagle à {position_eagle}"

    # Prompt strict — uniquement basé sur les transcriptions
    sources_text = ""
    for i, t in enumerate(transcriptions, 1):
        sources_text += f"\n--- SOURCE {i} : {t['titre']} ({t['chaine']}) ---\n{t['texte']}\n"

    prompt = f"""Tu es un analyste CoC. Tu dois créer une stratégie d'attaque TH18 pour cette base :
BASE DÉTECTÉE : {base_context}

Tu as accès aux transcriptions réelles de {len(transcriptions)} vidéos de bases similaires :
{sources_text}

RÈGLES ABSOLUES :
1. Utilise UNIQUEMENT les informations présentes dans ces transcriptions
2. Si une compo est mentionnée dans les transcriptions → utilise-la
3. Si un point d'entrée est mentionné → utilise-le
4. N'invente PAS de troupes, de sorts ou de tactiques absentes des transcriptions
5. Si les transcriptions sont insuffisantes → dis "Données insuffisantes dans les vidéos disponibles"
6. Indique toujours les sources utilisées

FORMAT DE RÉPONSE :
**Compo** (tirée des vidéos) : [compo exacte mentionnée]
**Point d'entrée** : [position horaire si mentionnée]
**Plan d'attaque** :
1. [étape tirée des vidéos]
2. [étape tirée des vidéos]
3. [étape tirée des vidéos]
**Source** : [titre + lien de la vidéo utilisée]"""

    try:
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            messages=[
                {"role": "system", "content": "Tu es un coach CoC. Tu te bases UNIQUEMENT sur les transcriptions fournies. Tu n'inventes rien."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=600
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Erreur génération stratégie : {e}"


async def analyze_screenshot(image_url: str, hdv_force=None) -> dict:
    # ── 1. Détection visuelle ──
    detection = await detect_base(image_url)
    type_base = detection.get("type_base", "inconnu")
    defenses = detection.get("defenses_visibles", [])
    position_eagle = detection.get("position_eagle", "inconnu")
    air_expo = detection.get("air_expo", False)
    compartiments = detection.get("compartiments", "inconnu")

    # ── 2. SQLite d'abord ──
    videos_sqlite = search_sqlite(type_base)

    # ── 3. YouTube API si SQLite insuffisant ──
    videos_youtube = []
    if len(videos_sqlite) < 3 and YOUTUBE_API_KEY:
        queries = []
        if type_base != "inconnu":
            queries.append(f"TH18 {type_base} base attack 2026")
            queries.append(f"TH18 {type_base} war 3 star 2026")
        queries.append("TH18 base attack 3 star 2026")
        queries.append("TH18 war base 2026 pro attack")
        for query in queries[:4]:
            nouvelles = await asyncio.to_thread(search_youtube, query, 5)
            videos_youtube.extend(nouvelles)
            await asyncio.sleep(0.3)

    # ── 4. Fusion + scoring + dédoublonnage ──
    tous = []
    seen = set()
    for v in videos_sqlite + videos_youtube:
        lien = v.get("lien", "")
        if lien not in seen:
            seen.add(lien)
            v["score"] = score_video(v, detection)
            tous.append(v)

    tous.sort(key=lambda x: x["score"], reverse=True)
    top5 = tous[:5]

    # ── 5. Qualification du match ──
    strategie = None
    strategie_sources = []

    if not top5:
        match_type = "none"
        match_label = "❌ Aucune vidéo trouvée"
    elif top5[0]["score"] >= 0.60:
        match_type = "exact"
        match_label = "🎯 Vidéo correspondante trouvée"
    else:
        match_type = "similaire"
        match_label = "📹 Bases similaires trouvées — stratégie basée sur ces vidéos"
        # Génère stratégie depuis transcriptions réelles
        strategie = await generate_strategy_from_transcripts(top5, detection)
        strategie_sources = [{"titre": v["titre"], "lien": v["lien"]} for v in top5[:3]]

    # ── 6. Résumé détection ──
    resume = []
    if type_base != "inconnu":
        resume.append(f"**Type :** `{type_base.upper()}`")
    if defenses:
        resume.append(f"**Défenses :** {', '.join(defenses[:5])}")
    if position_eagle != "inconnu":
        resume.append(f"**Eagle :** position `{position_eagle}`")
    if air_expo:
        resume.append("⚠️ Air Defenses exposées")
    if compartiments != "inconnu":
        resume.append(f"**Compartiments :** {compartiments}")

    return {
        "hdv": "18",
        "type_base": type_base,
        "detection_resume": "\n".join(resume) or "Détection partielle",
        "match_type": match_type,
        "match_label": match_label,
        "videos": top5,
        "strategie": strategie,
        "strategie_sources": strategie_sources,
        "ia_utilisee": "groq-llama-3.2-vision"
    }

# ══════════════════════════════════════════════
# RECHERCHE TWITCH (en complément YouTube)
# ══════════════════════════════════════════════
def search_twitch_sqlite(type_base: str, compos: list) -> list:
    """Cherche dans la base Twitch locale"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT titre, lien, streamer, type_contenu, hdv_detecte,
                   vues, pertinence, date_stream
            FROM twitch_coc
            WHERE hdv_detecte = '18'
               OR titre LIKE '%TH18%'
               OR titre LIKE '%HDV18%'
            ORDER BY pertinence DESC, vues DESC
            LIMIT 5
        """)
        rows = c.fetchall()
        conn.close()
        results = []
        for r in rows:
            badge = {"vod": "📼", "clip": "✂️", "live": "🔴", "channel": "📺"}.get(r[3], "🎮")
            results.append({
                "titre": r[0],
                "lien": r[1],
                "chaine": r[2],
                "source": "twitch",
                "badge": badge,
                "vues": r[5],
                "score": r[6],
                "date": r[7] or "?"
            })
        return results
    except:
        return []

# ══════════════════════════════════════════════
# RECHERCHE TWITCH (en complément YouTube)
# ══════════════════════════════════════════════
def search_twitch_sqlite(type_base: str, compos: list) -> list:
    """Cherche dans la base Twitch locale"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT titre, lien, streamer, type_contenu, hdv_detecte,
                   vues, pertinence, date_stream
            FROM twitch_coc
            WHERE hdv_detecte = '18'
               OR titre LIKE '%TH18%'
               OR titre LIKE '%HDV18%'
            ORDER BY pertinence DESC, vues DESC
            LIMIT 5
        """)
        rows = c.fetchall()
        conn.close()
        results = []
        for r in rows:
            badge = {"vod": "📼", "clip": "✂️", "live": "🔴", "channel": "📺"}.get(r[3], "🎮")
            results.append({
                "titre": r[0],
                "lien": r[1],
                "chaine": r[2],
                "source": "twitch",
                "badge": badge,
                "vues": r[5],
                "score": r[6],
                "date": r[7] or "?"
            })
        return results
    except:
        return []
