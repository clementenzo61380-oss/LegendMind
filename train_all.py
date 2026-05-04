import os, sqlite3, time, subprocess, json, re, requests, signal, sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

DB_PATH = "coc-bot.db"
TWITCH_CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

# ── Stop à 8h00 Paris ──────────────────────
def should_stop() -> bool:
    now = datetime.now()
    if now.hour >= 8 and now.minute >= 0:
        return True
    return False

def time_left() -> str:
    now = datetime.now()
    target = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now >= target:
        return "0h00"
    delta = int((target - now).total_seconds())
    h, m = divmod(delta // 60, 60)
    return f"{h}h{m:02d}"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ════════════════════════════════════════════
# BASE DE DONNÉES
# ════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS youtube_th18 (
        video_id TEXT PRIMARY KEY, titre TEXT, lien TEXT,
        chaine TEXT, duree_sec INTEGER DEFAULT 0,
        vues INTEGER DEFAULT 0, type_base TEXT DEFAULT 'inconnu',
        compo TEXT DEFAULT 'inconnu', langue TEXT DEFAULT 'en',
        pertinence REAL DEFAULT 0.5, transcription TEXT DEFAULT '',
        date_publication TEXT, date_ajout REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS twitch_coc (
        video_id TEXT PRIMARY KEY, titre TEXT, lien TEXT,
        streamer TEXT, type_contenu TEXT DEFAULT 'vod',
        hdv_detecte TEXT DEFAULT 'inconnu', type_base TEXT DEFAULT 'inconnu',
        compo TEXT DEFAULT 'inconnu', langue TEXT DEFAULT 'inconnu',
        duree_sec INTEGER DEFAULT 0, vues INTEGER DEFAULT 0,
        pertinence REAL DEFAULT 0.5, transcription TEXT DEFAULT '',
        date_stream TEXT, date_ajout REAL)""")
    conn.commit(); conn.close()

def exists(table: str, video_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute(f"SELECT 1 FROM {table} WHERE video_id=?", (video_id,)).fetchone()
    conn.close()
    return r is not None

def count(table: str) -> int:
    try:
        conn = sqlite3.connect(DB_PATH)
        r = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.close()
        return r
    except: return 0

# ════════════════════════════════════════════
# DÉTECTION
# ════════════════════════════════════════════
def is_th18(t: str) -> bool:
    return bool(re.search(r'\bTH\s*18\b|\bHDV\s*18\b|\bTown\s*Hall\s*18\b', t, re.IGNORECASE))

def detect_type_base(t: str) -> str:
    t = t.lower()
    for k, v in [("box","box"),("ring","ring"),("diamond","diamond"),
                 ("anti 3","anti3"),("anti3","anti3"),("anti 2","anti2"),
                 ("hybrid","hybrid"),("triangle","triangle"),("spam","spam")]:
        if k in t: return v
    return "inconnu"

def detect_compo(t: str) -> list:
    t = t.lower()
    tags = []
    kws = {"root rider":"root_riders","thrower":"throwers","rc charge":"rc_charge",
           "blizzard":"blizzard_lalo","sui lalo":"sui_lalo","lalo":"lalo",
           "fireball":"fireball","super witch":"super_witch","drag bat":"drag_bat",
           "electro dragon":"electro_dragon","queen walk":"queen_walk",
           "queen charge":"queen_charge","warden walk":"warden_walk",
           "recall":"recall_spell","smash":"smash","dragon":"dragon",
           "witches":"witches","minion":"minion_prince","golem":"golem"}
    for kw, tag in kws.items():
        if kw in t and tag not in tags: tags.append(tag)
    return tags or ["inconnu"]

def detect_langue(t: str) -> str:
    t = t.lower()
    if any(w in t for w in ["étoile","guerre","attaque","stratégie","hdv","clash clans"]): return "fr"
    if any(w in t for w in ["angriff","krieg","angreifen","sterne"]): return "de"
    if any(w in t for w in ["ataque","guerra","estrella","aldea"]): return "es"
    if any(w in t for w in ["攻撃","戦争","星"]): return "ja"
    return "en"

def parse_duration(dur: str) -> int:
    total = 0
    for num, unit in re.findall(r'(\d+)([hms])', dur or ""):
        if unit == 'h': total += int(num)*3600
        elif unit == 'm': total += int(num)*60
        elif unit == 's': total += int(num)
    return total

# ════════════════════════════════════════════
# TWITCH AUTH
# ════════════════════════════════════════════
_twitch_token = None

def get_token() -> str:
    global _twitch_token
    if _twitch_token: return _twitch_token
    resp = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }, timeout=10)
    _twitch_token = resp.json()["access_token"]
    return _twitch_token

def headers() -> dict:
    return {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {get_token()}"}

# ════════════════════════════════════════════
# TWITCH — TOUS LES STREAMERS SANS EXCEPTION
# ════════════════════════════════════════════
COC_GAME_ID = "65985"

def get_coc_game_id() -> str:
    try:
        r = requests.get("https://api.twitch.tv/helix/games",
            params={"name": "Clash of Clans"}, headers=headers(), timeout=10)
        data = r.json().get("data", [])
        return data[0]["id"] if data else COC_GAME_ID
    except: return COC_GAME_ID

def save_twitch(v: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT OR REPLACE INTO twitch_coc
        (video_id,titre,lien,streamer,type_contenu,hdv_detecte,type_base,
         compo,langue,duree_sec,vues,pertinence,date_stream,date_ajout)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        v["video_id"], v["titre"], v["lien"], v["streamer"],
        v["type"], "18", detect_type_base(v["titre"]),
        json.dumps(detect_compo(v["titre"])),
        detect_langue(v["titre"] + " " + v["streamer"]),
        v.get("duree",0), v.get("vues",0), v.get("score",0.5),
        v.get("date",""), time.time()
    ))
    conn.commit(); conn.close()

def scrape_twitch_vods_ALL(game_id: str):
    """Scrape TOUS les VODs CoC — tous streamers — en boucle jusqu'à 8h"""
    log("🎮 TWITCH VODs — tous streamers CoC")
    cursor = None
    total = 0
    page = 0
    while not should_stop():
        try:
            params = {"game_id": game_id, "type": "archive", "first": 100}
            if cursor: params["after"] = cursor
            r = requests.get("https://api.twitch.tv/helix/videos",
                params=params, headers=headers(), timeout=15)
            data = r.json()
            items = data.get("data", [])
            if not items: break

            saved = 0
            for v in items:
                titre = v.get("title","")
                streamer = v.get("user_name","")
                texte = titre + " " + streamer
                if not is_th18(texte): continue
                vid = v["id"]
                if exists("twitch_coc", vid): continue
                save_twitch({
                    "video_id": vid, "titre": titre,
                    "lien": v.get("url",""), "streamer": streamer,
                    "type": "vod",
                    "duree": parse_duration(v.get("duration","0s")),
                    "vues": v.get("view_count",0),
                    "score": min(0.3 + v.get("view_count",0)/100000*0.5, 1.0),
                    "date": v.get("published_at","")[:10]
                })
                saved += 1
                total += 1

            cursor = data.get("pagination",{}).get("cursor")
            page += 1
            if page % 10 == 0:
                log(f"  VODs page {page} — {total} TH18 sauvegardés — reste {time_left()}")
            if not cursor: 
                log(f"  VODs épuisés après {page} pages. Reprise dans 60s...")
                time.sleep(60)
                cursor = None  # repart du début
            time.sleep(0.3)
        except Exception as e:
            log(f"  ⚠️ VOD erreur : {e}")
            time.sleep(5)

    log(f"  ✅ VODs terminé : {total} TH18 sauvegardés")
    return total

def scrape_twitch_clips_ALL(game_id: str):
    """Scrape TOUS les clips CoC — tous streamers"""
    log("✂️  TWITCH Clips — tous streamers CoC")
    cursor = None
    total = 0
    page = 0
    while not should_stop():
        try:
            params = {"game_id": game_id, "first": 100,
                      "started_at": "2023-01-01T00:00:00Z"}
            if cursor: params["after"] = cursor
            r = requests.get("https://api.twitch.tv/helix/clips",
                params=params, headers=headers(), timeout=15)
            data = r.json()
            items = data.get("data", [])
            if not items: break

            for c in items:
                titre = c.get("title","")
                streamer = c.get("broadcaster_name","")
                if not is_th18(titre + " " + streamer): continue
                vid = "clip_" + c["id"]
                if exists("twitch_coc", vid): continue
                save_twitch({
                    "video_id": vid, "titre": titre,
                    "lien": c.get("url",""), "streamer": streamer,
                    "type": "clip",
                    "duree": int(c.get("duration",0)),
                    "vues": c.get("view_count",0),
                    "score": min(0.3 + c.get("view_count",0)/50000*0.5, 1.0),
                    "date": c.get("created_at","")[:10]
                })
                total += 1

            cursor = data.get("pagination",{}).get("cursor")
            page += 1
            if page % 10 == 0:
                log(f"  Clips page {page} — {total} TH18 — reste {time_left()}")
            if not cursor:
                log(f"  Clips épuisés. Reprise dans 60s...")
                time.sleep(60)
                cursor = None
            time.sleep(0.3)
        except Exception as e:
            log(f"  ⚠️ Clip erreur : {e}")
            time.sleep(5)

    log(f"  ✅ Clips terminé : {total} sauvegardés")
    return total

def scrape_twitch_live_ALL(game_id: str):
    """Streams LIVE CoC en ce moment — tous"""
    log("🔴 TWITCH Live — scan en cours")
    total = 0
    cursor = None
    while True:
        try:
            params = {"game_id": game_id, "first": 100}
            if cursor: params["after"] = cursor
            r = requests.get("https://api.twitch.tv/helix/streams",
                params=params, headers=headers(), timeout=15)
            data = r.json()
            items = data.get("data", [])
            if not items: break
            for s in items:
                titre = s.get("title","")
                streamer = s.get("user_name","")
                texte = titre + " " + streamer + " " + " ".join(s.get("tags",[]))
                if not is_th18(texte): continue
                vid = "live_" + s["id"]
                if exists("twitch_coc", vid): continue
                save_twitch({
                    "video_id": vid,
                    "titre": f"[LIVE] {titre}",
                    "lien": f"https://www.twitch.tv/{s['user_login']}",
                    "streamer": streamer, "type": "live",
                    "duree": 0, "vues": s.get("viewer_count",0),
                    "score": 0.6, "date": s.get("started_at","")[:10]
                })
                total += 1
            cursor = data.get("pagination",{}).get("cursor")
            if not cursor: break
            time.sleep(0.2)
        except Exception as e:
            log(f"  ⚠️ Live erreur : {e}")
            break
    log(f"  ✅ Live : {total} streams TH18")
    return total

# ════════════════════════════════════════════
# YOUTUBE — yt-dlp SANS QUOTA
# ════════════════════════════════════════════
QUERIES_YT = [
    # Attaques génériques
    "TH18 attack 3 star 2026", "TH18 attack 2026", "TH18 war attack 2026",
    "TH18 attack 3 star 2025", "TH18 war 2025", "HDV18 attaque 2026",
    "HDV18 guerre 2026", "HDV 18 3 etoiles 2026", "HDV18 attaque 2025",
    # Compos
    "TH18 root riders 2026", "TH18 throwers 2026", "TH18 rc charge 2026",
    "TH18 blizzard lalo 2026", "TH18 sui lalo 2026", "TH18 super witch 2026",
    "TH18 fireball loons 2026", "TH18 drag bat 2026", "TH18 queen charge 2026",
    "TH18 warden walk 2026", "TH18 recall spell 2026", "TH18 smash army 2026",
    "TH18 electro dragon 2026", "TH18 witches 2026", "TH18 minion prince 2026",
    "TH18 root riders 2025", "TH18 blizzard lalo 2025", "TH18 super witch 2025",
    # Types de bases
    "TH18 box base attack 2026", "TH18 ring base attack 2026",
    "TH18 diamond base attack 2026", "TH18 anti 3 star attack 2026",
    "TH18 hybrid base attack 2026", "TH18 triangle base 2026",
    "TH18 anti eagle attack 2026", "TH18 no eagle attack 2026",
    # Modes de jeu
    "TH18 legend league attack 2026", "TH18 CWL attack 2026",
    "TH18 trophy pushing 2026", "TH18 world championship 2026",
    "TH18 esport attack 2026", "TH18 pro attack 2026",
    # Chaînes pro
    "TH18 blueprint coc 2026", "TH18 itzu 2026", "TH18 judo sloth 2026",
    "TH18 kenny jo 2026", "TH18 carbonfin 2026", "TH18 ash coc 2026",
    "TH18 ds gaming 2026", "TH18 peter17 2026",
    # Langues
    "HDV18 strategie attaque 2026", "HDV18 base guerre 2026",
    "TH18 angriff 2026", "TH18 angriff strategie 2026",
    "TH18 ataque 2026", "TH18 ataque guerra 2026",
    # Répétition 2024 pour l'historique
    "TH18 attack 2024", "TH18 root riders 2024", "TH18 blizzard lalo 2024",
    "TH18 super witch 2024", "HDV18 attaque 2024",
]

def save_youtube(v: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""INSERT OR REPLACE INTO youtube_th18
            (video_id,titre,lien,chaine,duree_sec,vues,type_base,
             compo,langue,pertinence,date_publication,date_ajout)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            v["id"], v.get("title","?"),
            f"https://www.youtube.com/watch?v={v['id']}",
            v.get("uploader","?"), int(v.get("duration") or 0),
            int(v.get("view_count") or 0),
            detect_type_base(v.get("title","")),
            json.dumps(detect_compo(v.get("title",""))),
            detect_langue(v.get("title","")),
            min(0.3 + int(v.get("view_count") or 0)/500000*0.4, 1.0),
            (v.get("upload_date") or "")[:10], time.time()
        ))
        conn.commit(); conn.close()
    except: pass

def run_youtube_loop():
    """Tourne en boucle sur toutes les requêtes jusqu'à 8h"""
    log(f"▶️  YOUTUBE (yt-dlp) — {len(QUERIES_YT)} requêtes en boucle")
    total = 0
    cycle = 0
    while not should_stop():
        cycle += 1
        log(f"  Cycle YouTube #{cycle} — reste {time_left()}")
        for i, q in enumerate(QUERIES_YT, 1):
            if should_stop(): break
            try:
                result = subprocess.run([
                    "yt-dlp", f"ytsearch20:{q}",
                    "--dump-json", "--no-download",
                    "--quiet", "--no-warnings"
                ], capture_output=True, text=True, timeout=45)
                saved = 0
                for line in result.stdout.strip().split("\n"):
                    if not line.strip(): continue
                    try:
                        v = json.loads(line)
                        titre = v.get("title","")
                        if not is_th18(titre): continue
                        vid = v.get("id","")
                        if not vid or exists("youtube_th18", vid): continue
                        save_youtube(v)
                        saved += 1
                        total += 1
                    except: pass
                if saved > 0:
                    log(f"  [{i:02d}/{len(QUERIES_YT)}] '{q[:35]}' → +{saved} (total {total})")
                time.sleep(2)
            except Exception as e:
                log(f"  ⚠️ '{q[:30]}' : {e}")
                time.sleep(3)
        log(f"  ✅ Cycle #{cycle} terminé — {total} vidéos YouTube au total")
        if not should_stop():
            log(f"  💤 Pause 5 min avant cycle #{cycle+1}...")
            time.sleep(300)

# ════════════════════════════════════════════
# STATS EN DIRECT
# ════════════════════════════════════════════
def print_stats():
    yt = count("youtube_th18")
    tw = count("twitch_coc")
    log(f"📊 Base actuelle → YouTube: {yt} | Twitch: {tw} | Total: {yt+tw}")

# ════════════════════════════════════════════
# MAIN — PARALLÈLE TWITCH + YOUTUBE
# ════════════════════════════════════════════
import threading

if __name__ == "__main__":
    print("\n" + "█"*60)
    print(f"  ENTRAÎNEMENT MASSIF jusqu'à 08:00")
    print(f"  Temps restant : {time_left()}")
    print("█"*60 + "\n")

    init_db()
    game_id = get_coc_game_id()
    log(f"Game ID CoC Twitch : {game_id}")

    # Stats toutes les 10 minutes
    def stats_loop():
        while not should_stop():
            time.sleep(600)
            print_stats()
    threading.Thread(target=stats_loop, daemon=True).start()

    # Thread Twitch VODs (le plus volumineux)
    def twitch_thread():
        scrape_twitch_live_ALL(game_id)   # d'abord les lives
        scrape_twitch_clips_ALL(game_id)  # puis les clips
        scrape_twitch_vods_ALL(game_id)   # puis les VODs en boucle
    t_twitch = threading.Thread(target=twitch_thread)
    t_twitch.start()

    # Thread YouTube (tourne en parallèle)
    t_youtube = threading.Thread(target=run_youtube_loop)
    t_youtube.start()

    # Attente jusqu'à 8h
    t_twitch.join()
    t_youtube.join()

    print("\n" + "█"*60)
    print("  ENTRAÎNEMENT TERMINÉ — 08:00 atteint")
    print_stats()
    print("█"*60)
    print("\n✅ Lance maintenant : python3 bot.py")
