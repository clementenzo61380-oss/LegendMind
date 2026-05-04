import os, sqlite3, asyncio, json, re, time, requests
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv
load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DB_PATH = "coc-bot.db"

# ══════════════════════════════════════════════════════
# REQUÊTES ULTRA-LARGES — CAPTURE TOUT CE QUI CONTIENT
# TH18 ou HDV18 sur YouTube
# ══════════════════════════════════════════════════════
MEGA_QUERIES = [
    # Requêtes larges — filet maximum
    "TH18", "TH 18", "HDV18", "HDV 18",
    "Town Hall 18", "Hotel de Ville 18",

    # Par année
    "TH18 2026", "TH18 2025", "TH18 2024",
    "HDV18 2026", "HDV18 2025",

    # Par contexte
    "TH18 attack", "TH18 base", "TH18 war",
    "TH18 defense", "TH18 upgrade", "TH18 guide",
    "TH18 army", "TH18 strategy", "TH18 tips",
    "TH18 3 star", "TH18 legend", "TH18 CWL",
    "TH18 replay", "TH18 review", "TH18 tutorial",
    "HDV18 attaque", "HDV18 base", "HDV18 guerre",
    "HDV18 armée", "HDV18 stratégie", "HDV18 guide",

    # Par compo
    "TH18 root riders", "TH18 throwers",
    "TH18 queen charge", "TH18 rc charge",
    "TH18 blizzard lalo", "TH18 sui lalo",
    "TH18 fireball", "TH18 rocket loons",
    "TH18 super witch", "TH18 meteor golem",
    "TH18 drag bat", "TH18 electro dragon",
    "TH18 zap dragon", "TH18 super bowler",
    "TH18 warden walk", "TH18 queen walk",
    "TH18 ice thrower", "TH18 recall spell",

    # Par type de base
    "TH18 box base", "TH18 ring base",
    "TH18 diamond base", "TH18 anti 3 star",
    "TH18 anti 2 star", "TH18 hybrid base",
    "TH18 war base link", "TH18 base link",
    "TH18 best base", "TH18 trophy base",
    "TH18 legend base", "TH18 farming base",

    # Chaînes pro
    "Blueprint CoC TH18", "Itzu TH18",
    "Judo Sloth TH18", "Kenny Jo TH18",
    "CarbonFin TH18", "Ash CoC TH18",
    "DS Gaming TH18", "Peter17 TH18",
    "Gaku TH18", "GalaxyStars TH18",
    "clash bashing TH18", "cocbases TH18",

    # Langues
    "HDV 18 clash of clans",
    "TH18 clash of clans français",
    "TH18 攻撃 2026",
    "TH18 angriff 2026",
    "TH18 ataque 2026",
    "TH18 攻略 2026",
]

# Chaînes pro — scraping direct exhaustif
CANAUX_PRO = {
    "UCpBLZpIqQRjFdUJBWzQ4rew": "Blueprint CoC",
    "UCFpBzTTkWqTkDjBjSmHF6EA": "Judo Sloth Gaming",
    "UCRlwlJ5szYlQaFuJMxFlP1g": "Kenny Jo",
    "UC7HMhSaG3A8T-xKMDLO9gkA": "CarbonFin Gaming",
    "UCkCrQgIiZfVj0NqJYdFYvLg": "Ash - Clash of Clans",
    "UCsaS5STZ0QPLFh1LnMcfVyQ": "DS Gaming",
    "UCGCBxJqn2LmqoANpQF0IOYQ": "Peter17$",
    "UCXYDLUc4SB_HOEOJbO_HSTA": "Itzu",
    "UC7k4MHY5PATqylooSbB3rMQ": "GalaxyStars CoC",
    "UCpEMaBGMGDDkWbhsE2RMOUA": "Clash Bashing",
}


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS youtube_th18 (
            video_id TEXT PRIMARY KEY,
            titre TEXT,
            lien TEXT,
            chaine TEXT,
            date_publication TEXT,
            hdv TEXT DEFAULT 'TH18',
            type_base TEXT DEFAULT 'inconnu',
            style_base TEXT DEFAULT 'inconnu',
            compo_attaque TEXT DEFAULT 'inconnu',
            resultat TEXT DEFAULT 'inconnu',
            point_entree TEXT DEFAULT 'inconnu',
            pertinence_score REAL DEFAULT 0.0,
            tags TEXT DEFAULT '',
            transcription TEXT DEFAULT '',
            date_ajout REAL
        )
    """)
    conn.commit()
    conn.close()


def detect_type_base(t):
    t = t.lower()
    if "box" in t: return "box"
    if "ring" in t: return "ring"
    if "diamond" in t: return "diamond"
    if "anti 3" in t or "anti3" in t or "anti-3" in t: return "anti3"
    if "anti 2" in t or "anti2" in t or "anti-2" in t: return "anti2"
    if "hybrid" in t: return "hybrid"
    return "inconnu"


def detect_compo(t):
    t = t.lower()
    found = []
    kws = {
        "rc charge": "rc_charge_throwers",
        "root rider": "root_riders",
        "ice thrower": "ice_throwers",
        "thrower": "throwers",
        "blizzard": "blizzard_lalo",
        "sui lalo": "sui_lalo",
        "lalo": "lalo",
        "lava hound": "lalo",
        "fireball": "fireball_loons",
        "rocket loon": "rocket_loons",
        "super witch": "super_witch",
        "drag bat": "drag_bat",
        "electro dragon": "electro_dragon",
        "zap dragon": "zap_dragon",
        "meteor golem": "meteor_golem",
        "recall": "recall_spell",
        "queen walk": "queen_walk",
        "queen charge": "queen_charge",
        "warden walk": "warden_walk",
        "super bowler": "super_bowlers",
        "smash": "smash",
        "balloon": "lalo",
        "dragon": "dragon",
    }
    for kw, tag in kws.items():
        if kw in t and tag not in found:
            found.append(tag)
    return found if found else ["inconnu"]


def detect_style(t):
    t = t.lower()
    if "legend" in t: return "legend"
    if "war" in t or "cwl" in t or "gdc" in t: return "war"
    if "anti 3" in t or "anti-3" in t: return "anti-3stars"
    if "trophy" in t: return "trophy"
    if "farming" in t: return "farming"
    return "inconnu"


def detect_point_entree(txt):
    m = re.findall(r'\b([0-9]{1,2})\s*(?:h|o\'clock|oclock)\b', txt.lower())
    return f"{m[0]}h" if m else "inconnu"


def detect_resultat(t):
    t = t.lower()
    if "3 star" in t or "triple" in t or "3 étoile" in t: return "3 étoiles"
    if "2 star" in t or "2 étoile" in t: return "2 étoiles"
    return "inconnu"


def calc_score(chaine, titre, date, has_transcript, type_base, compos):
    score = 0.4
    pros = ["blueprint", "itzu", "judo sloth", "kenny jo", "carbonfin",
            "ash", "ds gaming", "peter17", "gaku", "galaxystars", "clash bashing"]
    if any(p in chaine.lower() for p in pros):
        score += 0.25
    if type_base != "inconnu": score += 0.10
    if compos != ["inconnu"]: score += 0.05
    if has_transcript: score += 0.10
    if "2026" in date: score += 0.07
    elif "2025" in date: score += 0.03
    for kw in ["3 star", "war", "cwl", "legend", "pro", "attack"]:
        if kw in titre.lower(): score += 0.03
    return min(score, 1.0)


def get_transcript_safe(video_id):
    try:
        t = YouTubeTranscriptApi.get_transcript(video_id, languages=["fr", "en", "de", "es", "ja"])
        return " ".join([x["text"] for x in t[:150]])
    except:
        return ""


def save_video(v):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO youtube_th18
        (video_id, titre, lien, chaine, date_publication, hdv,
         type_base, style_base, compo_attaque, resultat,
         point_entree, pertinence_score, tags, transcription, date_ajout)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        v["video_id"], v["titre"], v["lien"], v["chaine"], v["date"],
        "TH18", v["type_base"], v["style"],
        json.dumps(v["compos"]), v["resultat"],
        v["point_entree"], v["score"],
        json.dumps(v["compos"]), v["transcript"][:3000], time.time()
    ))
    conn.commit()
    conn.close()


def already_exists(video_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM youtube_th18 WHERE video_id=?", (video_id,)).fetchone()
    conn.close()
    return row is not None


def fetch_all_pages(query, max_pages=5):
    """Récupère jusqu'à 5 pages de résultats (50 vidéos) par requête"""
    if not YOUTUBE_API_KEY:
        return []
    all_items = []
    next_token = None
    yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    for _ in range(max_pages):
        try:
            params = dict(
                part="snippet", q=query,
                maxResults=10, type="video",
                publishedAfter="2023-01-01T00:00:00Z",
                order="relevance"
            )
            if next_token:
                params["pageToken"] = next_token
            resp = yt.search().list(**params).execute()
            items = resp.get("items", [])
            for item in items:
                titre = item["snippet"]["title"]
                # FILTRE STRICT
                if not re.search(
                    r'TH18|HDV18|TH\s*18|HDV\s*18|Town\s*Hall\s*18|Hotel\s*de\s*Ville\s*18',
                    titre, re.IGNORECASE
                ):
                    continue
                all_items.append({
                    "video_id": item["id"]["videoId"],
                    "titre": titre,
                    "lien": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    "chaine": item["snippet"]["channelTitle"],
                    "date": item["snippet"]["publishedAt"][:10],
                    "description": item["snippet"].get("description", "")
                })
            next_token = resp.get("nextPageToken")
            if not next_token:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"    [API] {e}")
            break
    return all_items


def fetch_channel_all(channel_id, channel_name, max_pages=10):
    """Récupère toutes les vidéos TH18 d'une chaîne (jusqu'à 100)"""
    if not YOUTUBE_API_KEY:
        return []
    all_items = []
    next_token = None
    yt = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    for _ in range(max_pages):
        try:
            params = dict(
                part="snippet", channelId=channel_id,
                q="TH18 OR HDV18", maxResults=10,
                type="video", publishedAfter="2023-01-01T00:00:00Z",
                order="date"
            )
            if next_token:
                params["pageToken"] = next_token
            resp = yt.search().list(**params).execute()
            for item in resp.get("items", []):
                titre = item["snippet"]["title"]
                if not re.search(r'TH18|HDV18|TH\s*18|HDV\s*18', titre, re.IGNORECASE):
                    continue
                all_items.append({
                    "video_id": item["id"]["videoId"],
                    "titre": titre,
                    "lien": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    "chaine": channel_name,
                    "date": item["snippet"]["publishedAt"][:10],
                    "description": item["snippet"].get("description", "")
                })
            next_token = resp.get("nextPageToken")
            if not next_token:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"    [Channel {channel_name}] {e}")
            break
    return all_items


def process_and_save(videos):
    """Traite et sauvegarde une liste de vidéos"""
    saved = 0
    for v in videos:
        if already_exists(v["video_id"]):
            continue
        texte = v["titre"] + " " + v.get("description", "")
        transcript = get_transcript_safe(v["video_id"])
        texte_full = texte + " " + transcript

        type_base = detect_type_base(texte_full)
        style = detect_style(texte_full)
        compos = detect_compo(texte_full)
        resultat = detect_resultat(texte_full)
        point_entree = detect_point_entree(transcript)
        score = calc_score(
            v["chaine"], v["titre"], v["date"],
            bool(transcript), type_base, compos
        )
        save_video({
            **v,
            "type_base": type_base,
            "style": style,
            "compos": compos,
            "resultat": resultat,
            "point_entree": point_entree,
            "transcript": transcript,
            "score": score
        })
        saved += 1
        time.sleep(0.15)
    return saved


def print_stats():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM youtube_th18").fetchone()[0]
    types = conn.execute(
        "SELECT type_base, COUNT(*) FROM youtube_th18 GROUP BY type_base ORDER BY COUNT(*) DESC"
    ).fetchall()
    transcripts = conn.execute(
        "SELECT COUNT(*) FROM youtube_th18 WHERE transcription != ''"
    ).fetchone()[0]
    top_chaines = conn.execute(
        "SELECT chaine, COUNT(*) FROM youtube_th18 GROUP BY chaine ORDER BY COUNT(*) DESC LIMIT 8"
    ).fetchall()
    conn.close()

    print("\n" + "="*60)
    print("  RÉSULTAT FINAL")
    print("="*60)
    print(f"  Total vidéos      : {total}")
    print(f"  Avec transcription: {transcripts} ({int(transcripts/max(total,1)*100)}%)")
    print("\n  Par type de base :")
    for r in types:
        bar = "█" * min(int(r[1]/5), 20)
        print(f"    {r[0]:15} {bar} {r[1]}")
    print("\n  Top chaînes :")
    for r in top_chaines:
        print(f"    {r[0][:30]:30} → {r[1]} vidéos")


def run():
    print("\n" + "="*60)
    print("  ENTRAÎNEMENT MAXIMAL — TOUTES VIDÉOS TH18/HDV18")
    print("="*60)

    init_db()

    conn = sqlite3.connect(DB_PATH)
    avant = conn.execute("SELECT COUNT(*) FROM youtube_th18").fetchone()[0]
    conn.close()
    print(f"\n  Vidéos en base avant : {avant}")
    print(f"  Requêtes prévues     : {len(MEGA_QUERIES)}")
    print(f"  Chaînes pro          : {len(CANAUX_PRO)}")
    print(f"  Quota estimé         : ~{(len(MEGA_QUERIES) * 5 + len(CANAUX_PRO) * 10) * 100} unités\n")

    total = 0

    # ── PHASE 1 : Chaînes pro ────────────────────────────────────
    print("📺 PHASE 1 — Chaînes pro (scraping exhaustif)")
    for ch_id, ch_name in CANAUX_PRO.items():
        print(f"  → {ch_name}...", end=" ", flush=True)
        videos = fetch_channel_all(ch_id, ch_name, max_pages=10)
        saved = process_and_save(videos)
        total += saved
        print(f"{len(videos)} trouvées, {saved} nouvelles")
        time.sleep(1)

    # ── PHASE 2 : Requêtes larges ────────────────────────────────
    print(f"\n🔍 PHASE 2 — {len(MEGA_QUERIES)} requêtes (5 pages chacune)")
    for i, query in enumerate(MEGA_QUERIES):
        print(f"  [{i+1:3}/{len(MEGA_QUERIES)}] {query:<45}", end=" ", flush=True)
        videos = fetch_all_pages(query, max_pages=5)
        saved = process_and_save(videos)
        total += saved
        print(f"{len(videos)} trouvées, {saved} nouvelles")
        time.sleep(0.5)

    print(f"\n✅ {total} nouvelles vidéos ajoutées")
    print_stats()


if __name__ == "__main__":
    run()
