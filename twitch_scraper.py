import os, sqlite3, time, json, re, requests
from dotenv import load_dotenv
load_dotenv()

TWITCH_CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
DB_PATH = "coc-bot.db"

# ══════════════════════════════════════════════
# AUTH TWITCH — TOKEN OAUTH2
# ══════════════════════════════════════════════
def get_twitch_token() -> str:
    resp = requests.post("https://id.twitch.tv/oauth2/token", data={
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    })
    return resp.json()["access_token"]


def twitch_headers(token: str) -> dict:
    return {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }


# ══════════════════════════════════════════════
# BASE DE DONNÉES — TABLE TWITCH
# ══════════════════════════════════════════════
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS twitch_coc (
            video_id     TEXT PRIMARY KEY,
            titre        TEXT,
            lien         TEXT,
            streamer     TEXT,
            type_contenu TEXT DEFAULT 'vod',
            hdv_detecte  TEXT DEFAULT 'inconnu',
            type_base    TEXT DEFAULT 'inconnu',
            compo        TEXT DEFAULT 'inconnu',
            langue       TEXT DEFAULT 'inconnu',
            duree_sec    INTEGER DEFAULT 0,
            vues         INTEGER DEFAULT 0,
            pertinence   REAL DEFAULT 0.5,
            transcription TEXT DEFAULT '',
            date_stream  TEXT,
            date_ajout   REAL
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Table twitch_coc initialisée.")


# ══════════════════════════════════════════════
# DÉTECTION CONTENU TH18/HDV18
# ══════════════════════════════════════════════
def is_th18(texte: str) -> bool:
    """Filtre STRICT : uniquement HDV18 / TH18"""
    return bool(re.search(
        r'\bTH\s*18\b|\bHDV\s*18\b|\bTown\s*Hall\s*18\b|\bH[oô]tel\s*de\s*Ville\s*18\b',
        texte, re.IGNORECASE
    ))

def is_not_other_th(texte: str) -> bool:
    """Vérifie que ce n'est pas un autre HDV mentionné en priorité"""
    for i in [9,10,11,12,13,14,15,16,17]:
        if re.search(rf'\bTH\s*{i}\b|\bHDV\s*{i}\b', texte, re.IGNORECASE):
            # Si TH18 est aussi mentionné c'est ok, sinon on exclut
            if not re.search(r'\bTH\s*18\b|\bHDV\s*18\b', texte, re.IGNORECASE):
                return False
    return True


def detect_hdv(texte: str) -> str:
    for i in range(18, 8, -1):
        if re.search(rf'TH{i}|HDV{i}|TH\s*{i}|HDV\s*{i}', texte, re.IGNORECASE):
            return str(i)
    return "inconnu"


def detect_type_base(t: str) -> str:
    t = t.lower()
    if "box" in t: return "box"
    if "ring" in t: return "ring"
    if "diamond" in t: return "diamond"
    if "anti 3" in t or "anti3" in t: return "anti3"
    if "anti 2" in t or "anti2" in t: return "anti2"
    if "hybrid" in t: return "hybrid"
    return "inconnu"


def detect_compo(t: str) -> list:
    t = t.lower()
    found = []
    kws = {
        "root rider": "root_riders", "thrower": "throwers",
        "rc charge": "rc_charge", "blizzard": "blizzard_lalo",
        "sui lalo": "sui_lalo", "lalo": "lalo",
        "fireball": "fireball_loons", "super witch": "super_witch",
        "drag bat": "drag_bat", "electro dragon": "electro_dragon",
        "queen walk": "queen_walk", "queen charge": "queen_charge",
        "warden walk": "warden_walk", "recall": "recall_spell",
        "smash": "smash", "dragon": "dragon",
    }
    for kw, tag in kws.items():
        if kw in t and tag not in found:
            found.append(tag)
    return found if found else ["inconnu"]


def detect_langue(texte: str, streamer_login: str) -> str:
    t = texte.lower()
    if any(w in t for w in ["étoile", "guerre", "attaque", "stratégie", "hdv"]):
        return "fr"
    if any(w in t for w in ["angriff", "krieg", "angreifen"]):
        return "de"
    if any(w in t for w in ["ataque", "guerra", "estrella"]):
        return "es"
    return "en"


def calc_score(titre: str, vues: int, duree: int, has_th18: bool, streamer: str) -> float:
    score = 0.3
    if has_th18: score += 0.25
    if vues > 10000: score += 0.15
    elif vues > 1000: score += 0.08
    if duree > 600: score += 0.10
    pros = ["blueprint", "itzu", "judo", "kenny", "carbonfin", "ash coc",
            "galadon", "clash with eric", "dave coc", "powerbang"]
    if any(p in streamer.lower() for p in pros):
        score += 0.20
    for kw in ["3 star", "war", "cwl", "legend", "pro", "attack", "th18"]:
        if kw in titre.lower(): score += 0.03
    return min(score, 1.0)


def save_twitch(v: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO twitch_coc
        (video_id, titre, lien, streamer, type_contenu, hdv_detecte,
         type_base, compo, langue, duree_sec, vues, pertinence,
         transcription, date_stream, date_ajout)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        v["video_id"], v["titre"], v["lien"], v["streamer"],
        v["type_contenu"], v["hdv"], v["type_base"],
        json.dumps(v["compo"]), v["langue"],
        v["duree_sec"], v["vues"], v["score"],
        v.get("transcription", ""), v["date"], time.time()
    ))
    conn.commit()
    conn.close()


def already_exists_twitch(video_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute("SELECT 1 FROM twitch_coc WHERE video_id=?", (video_id,)).fetchone()
    conn.close()
    return r is not None


def parse_duration(dur: str) -> int:
    """Convertit '1h23m45s' en secondes"""
    total = 0
    for num, unit in re.findall(r'(\d+)([hms])', dur):
        if unit == 'h': total += int(num) * 3600
        elif unit == 'm': total += int(num) * 60
        elif unit == 's': total += int(num)
    return total


# ══════════════════════════════════════════════
# SCRAPING TWITCH — GAME ID CoC
# ══════════════════════════════════════════════
COC_GAME_ID = "65985"  # ID Twitch officiel de Clash of Clans

def get_coc_game_id(token: str) -> str:
    """Récupère l'ID exact du jeu CoC sur Twitch"""
    resp = requests.get(
        "https://api.twitch.tv/helix/games",
        params={"name": "Clash of Clans"},
        headers=twitch_headers(token)
    )
    data = resp.json().get("data", [])
    if data:
        gid = data[0]["id"]
        print(f"[Twitch] Game ID CoC : {gid}")
        return gid
    return COC_GAME_ID


def scrape_vods(token: str, game_id: str, max_pages: int = 20) -> list:
    """Scrape tous les VODs CoC récents"""
    all_vods = []
    cursor = None
    headers = twitch_headers(token)

    for page in range(max_pages):
        params = {
            "game_id": game_id,
            "type": "archive",
            "first": 100,
            "sort": "time"
        }
        if cursor:
            params["after"] = cursor

        try:
            resp = requests.get(
                "https://api.twitch.tv/helix/videos",
                params=params, headers=headers, timeout=10
            )
            data = resp.json()
            items = data.get("data", [])
            if not items:
                break

            for v in items:
                titre = v.get("title", "")
                streamer = v.get("user_name", "")
                texte = titre + " " + streamer
                duree = parse_duration(v.get("duration", "0s"))

                # Filtre strict HDV18
                if not is_th18(texte) or not is_not_other_th(texte):
                    continue

                all_vods.append({
                    "video_id": v["id"],
                    "titre": titre,
                    "lien": v["url"],
                    "streamer": streamer,
                    "type_contenu": "vod",
                    "hdv": detect_hdv(texte),
                    "type_base": detect_type_base(texte),
                    "compo": detect_compo(texte),
                    "langue": detect_langue(texte, streamer),
                    "duree_sec": duree,
                    "vues": v.get("view_count", 0),
                    "date": v.get("published_at", "")[:10],
                    "score": calc_score(titre, v.get("view_count", 0),
                                        duree, is_th18(texte), streamer)
                })

            cursor = data.get("pagination", {}).get("cursor")
            if not cursor:
                break

            print(f"  Page {page+1} — {len(all_vods)} VODs récupérés", end="\r")
            time.sleep(0.3)

        except Exception as e:
            print(f"\n  [VOD] Erreur page {page+1} : {e}")
            break

    return all_vods


def scrape_clips(token: str, game_id: str, max_pages: int = 20) -> list:
    """Scrape tous les clips CoC"""
    all_clips = []
    cursor = None
    headers = twitch_headers(token)

    for page in range(max_pages):
        params = {
            "game_id": game_id,
            "first": 100,
            "started_at": "2024-01-01T00:00:00Z"
        }
        if cursor:
            params["after"] = cursor

        try:
            resp = requests.get(
                "https://api.twitch.tv/helix/clips",
                params=params, headers=headers, timeout=10
            )
            data = resp.json()
            items = data.get("data", [])
            if not items:
                break

            for c in items:
                titre = c.get("title", "")
                streamer = c.get("broadcaster_name", "")
                texte = titre + " " + streamer

                # Filtre strict HDV18
                if not is_th18(texte) or not is_not_other_th(texte):
                    continue

                all_clips.append({
                    "video_id": "clip_" + c["id"],
                    "titre": titre,
                    "lien": c["url"],
                    "streamer": streamer,
                    "type_contenu": "clip",
                    "hdv": detect_hdv(texte),
                    "type_base": detect_type_base(texte),
                    "compo": detect_compo(texte),
                    "langue": detect_langue(texte, streamer),
                    "duree_sec": int(c.get("duration", 0)),
                    "vues": c.get("view_count", 0),
                    "date": c.get("created_at", "")[:10],
                    "score": calc_score(titre, c.get("view_count", 0),
                                        int(c.get("duration", 0)),
                                        is_th18(texte), streamer)
                })

            cursor = data.get("pagination", {}).get("cursor")
            if not cursor:
                break

            print(f"  Page {page+1} — {len(all_clips)} clips récupérés", end="\r")
            time.sleep(0.3)

        except Exception as e:
            print(f"\n  [Clip] Erreur page {page+1} : {e}")
            break

    return all_clips


def scrape_live_streams(token: str, game_id: str) -> list:
    """Récupère tous les streams CoC EN DIRECT maintenant"""
    headers = twitch_headers(token)
    all_live = []
    cursor = None

    while True:
        params = {"game_id": game_id, "first": 100}
        if cursor:
            params["after"] = cursor
        try:
            resp = requests.get(
                "https://api.twitch.tv/helix/streams",
                params=params, headers=headers, timeout=10
            )
            data = resp.json()
            items = data.get("data", [])
            if not items:
                break
            for s in items:
                titre = s.get("title", "")
                streamer = s.get("user_name", "")
                texte = titre + " " + streamer + " " + " ".join(s.get("tags", []))
                # Filtre strict HDV18
                if not is_th18(texte) or not is_not_other_th(texte):
                    continue

                all_live.append({
                    "video_id": "live_" + s["id"],
                    "titre": f"[LIVE] {titre}",
                    "lien": f"https://www.twitch.tv/{s['user_login']}",
                    "streamer": streamer,
                    "type_contenu": "live",
                    "hdv": detect_hdv(texte),
                    "type_base": detect_type_base(texte),
                    "compo": detect_compo(texte),
                    "langue": detect_langue(texte, streamer),
                    "duree_sec": 0,
                    "vues": s.get("viewer_count", 0),
                    "date": s.get("started_at", "")[:10],
                    "score": calc_score(titre, s.get("viewer_count", 0),
                                        0, is_th18(texte), streamer)
                })
            cursor = data.get("pagination", {}).get("cursor")
            if not cursor:
                break
            time.sleep(0.2)
        except Exception as e:
            print(f"  [Live] Erreur : {e}")
            break

    return all_live


def scrape_by_tag(token: str) -> list:
    """Cherche via tag 'Clash of Clans' et 'CoC' sur les streams"""
    headers = twitch_headers(token)
    all_tagged = []
    for tag_query in ["Clash of Clans", "CoC", "TH18", "HDV18", "clash"]:
        try:
            resp = requests.get(
                "https://api.twitch.tv/helix/search/channels",
                params={"query": tag_query, "first": 100, "live_only": False},
                headers=headers, timeout=10
            )
            items = resp.json().get("data", [])
            for ch in items:
                if ch.get("game_name", "").lower() == "clash of clans":
                    # Filtre : game doit être CoC ET titre contient TH18
                    titre_ch = ch.get("title", "")
                    if not is_th18(titre_ch):
                        continue

                    all_tagged.append({
                        "video_id": "ch_" + ch["id"],
                        "titre": f"[Chaîne] {ch['display_name']} — {ch.get('title','')}",
                        "lien": f"https://www.twitch.tv/{ch['broadcaster_login']}",
                        "streamer": ch["display_name"],
                        "type_contenu": "channel",
                        "hdv": detect_hdv(ch.get("title", "")),
                        "type_base": "inconnu",
                        "compo": ["inconnu"],
                        "langue": detect_langue(ch.get("title",""), ch["display_name"]),
                        "duree_sec": 0,
                        "vues": 0,
                        "date": "",
                        "score": 0.4
                    })
            time.sleep(0.3)
        except Exception as e:
            print(f"  [Tag] {tag_query} : {e}")
    return all_tagged


def print_stats():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM twitch_coc").fetchone()[0]
    types = conn.execute(
        "SELECT type_contenu, COUNT(*) FROM twitch_coc GROUP BY type_contenu"
    ).fetchall()
    hdvs = conn.execute(
        "SELECT hdv_detecte, COUNT(*) FROM twitch_coc GROUP BY hdv_detecte ORDER BY COUNT(*) DESC LIMIT 5"
    ).fetchall()
    langues = conn.execute(
        "SELECT langue, COUNT(*) FROM twitch_coc GROUP BY langue ORDER BY COUNT(*) DESC"
    ).fetchall()
    top_streamers = conn.execute(
        "SELECT streamer, COUNT(*) FROM twitch_coc GROUP BY streamer ORDER BY COUNT(*) DESC LIMIT 8"
    ).fetchall()
    conn.close()

    print("\n" + "="*60)
    print("  RÉSULTAT SCRAPING TWITCH")
    print("="*60)
    print(f"  Total entrées      : {total}")
    print("\n  Par type :")
    for r in types:
        print(f"    {r[0]:15} → {r[1]}")
    print("\n  HDV détectés :")
    for r in hdvs:
        print(f"    HDV{r[0]:5} → {r[1]}")
    print("\n  Langues :")
    for r in langues:
        print(f"    {r[0]:10} → {r[1]}")
    print("\n  Top streamers :")
    for r in top_streamers:
        print(f"    {r[0][:30]:30} → {r[1]}")


def run():
    print("\n" + "="*60)
    print("  TWITCH SCRAPER — TOUT CLASH OF CLANS")
    print("="*60)

    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        print("\n❌ TWITCH_CLIENT_ID ou TWITCH_CLIENT_SECRET manquant dans .env")
        print("   → Va sur https://dev.twitch.tv/console et crée une app")
        return

    init_db()

    print("\n🔑 Authentification Twitch...")
    token = get_twitch_token()
    print("  ✅ Token OK")

    game_id = get_coc_game_id(token)

    total = 0

    # ── Phase 1 : VODs ─────────────────────────────
    print(f"\n📼 PHASE 1 — VODs (jusqu'à 2000)")
    vods = scrape_vods(token, game_id, max_pages=20)
    saved = 0
    for v in vods:
        if not already_exists_twitch(v["video_id"]):
            save_twitch(v)
            saved += 1
    total += saved
    print(f"\n  ✅ {len(vods)} VODs récupérés, {saved} nouveaux")

    # ── Phase 2 : Clips ────────────────────────────
    print(f"\n✂️  PHASE 2 — Clips (jusqu'à 2000)")
    clips = scrape_clips(token, game_id, max_pages=20)
    saved = 0
    for c in clips:
        if not already_exists_twitch(c["video_id"]):
            save_twitch(c)
            saved += 1
    total += saved
    print(f"\n  ✅ {len(clips)} clips récupérés, {saved} nouveaux")

    # ── Phase 3 : Streams live ─────────────────────
    print(f"\n🔴 PHASE 3 — Streams EN DIRECT")
    lives = scrape_live_streams(token, game_id)
    saved = 0
    for l in lives:
        if not already_exists_twitch(l["video_id"]):
            save_twitch(l)
            saved += 1
    total += saved
    print(f"  ✅ {len(lives)} streams live, {saved} sauvegardés")

    # ── Phase 4 : Recherche par tag ────────────────
    print(f"\n🏷️  PHASE 4 — Chaînes par tag CoC")
    tagged = scrape_by_tag(token)
    saved = 0
    for t in tagged:
        if not already_exists_twitch(t["video_id"]):
            save_twitch(t)
            saved += 1
    total += saved
    print(f"  ✅ {len(tagged)} chaînes, {saved} nouvelles")

    print(f"\n🎉 Total ajouté : {total} entrées Twitch")
    print_stats()


if __name__ == "__main__":
    run()
