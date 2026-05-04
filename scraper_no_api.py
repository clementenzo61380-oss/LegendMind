import sqlite3, time, json, re
from youtube_transcript_api import YouTubeTranscriptApi
from youtubesearchpython import VideosSearch

DB_PATH = "coc-bot.db"

QUERIES = [
    "TH18 attack 3 star 2026", "TH18 root riders war 2026",
    "TH18 blizzard lalo 2026", "HDV18 strategie 2026",
    "TH18 rc charge throwers 2026", "TH18 sui lalo 2026",
    "TH18 base attack pro 2026", "TH18 war attack 2026",
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS youtube_th18 (
        video_id TEXT PRIMARY KEY, titre TEXT, lien TEXT, chaine TEXT,
        date_publication TEXT, type_base TEXT DEFAULT 'inconnu',
        compo_attaque TEXT DEFAULT 'inconnu', pertinence_score REAL DEFAULT 0.5,
        transcription TEXT DEFAULT '', date_ajout REAL)""")
    conn.commit(); conn.close()

def scrape():
    init_db()
    total = 0
    for q in QUERIES:
        print(f"  → {q}")
        try:
            search = VideosSearch(q, limit=10)
            results = search.result().get("result", [])
            conn = sqlite3.connect(DB_PATH)
            for v in results:
                titre = v.get("title", "")
                if not re.search(r'TH18|HDV18|TH\s*18', titre, re.IGNORECASE):
                    continue
                vid = v.get("id", "")
                try:
                    t = YouTubeTranscriptApi.get_transcript(vid, languages=["fr","en"])
                    transcript = " ".join([x["text"] for x in t[:100]])
                except: transcript = ""
                conn.execute("""INSERT OR IGNORE INTO youtube_th18
                    (video_id,titre,lien,chaine,date_publication,transcription,date_ajout)
                    VALUES (?,?,?,?,?,?,?)""",
                    (vid, titre, f"https://youtu.be/{vid}",
                     v.get("channel",{}).get("name","?"),
                     v.get("publishedTime","?"), transcript, time.time()))
                total += 1
                time.sleep(0.2)
            conn.commit(); conn.close()
        except Exception as e:
            print(f"    ⚠️ {e}")
        time.sleep(1)
    print(f"\n✅ {total} vidéos ajoutées sans quota API")

if __name__ == "__main__": scrape()
