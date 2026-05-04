
import asyncio, aiosqlite, requests, time, os
from dotenv import load_dotenv
load_dotenv()

DB_PATH = os.getenv("DB_PATH","data/bot.db")
YT_KEY = os.getenv("YOUTUBE_API_KEY","")

HDV_LIST = [9,10,11,12,13,14,15,16,17,18]
QUERIES = ["meta meilleure armee","Lalo guide","Dragbat guide","strategie guerre clan","CWL strategie","compo attaque"]

async def init_cache_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sources_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT,
                hdv INTEGER,
                source TEXT,
                title TEXT,
                url TEXT,
                description TEXT,
                collected_at INTEGER
            )
        """)
        await db.commit()

def fetch_youtube(query, hdv):
    if not YT_KEY:
        return []
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part":"snippet","q":"HDV"+str(hdv)+" "+query+" Clash of Clans 2025",
                    "type":"video","maxResults":5,"order":"date","key":YT_KEY},
            timeout=5
        )
        out = []
        for item in r.json().get("items",[]):
            out.append({
                "source":"YouTube",
                "title":item["snippet"]["title"],
                "url":"https://youtu.be/"+item["id"]["videoId"],
                "desc":item["snippet"]["description"][:400]
            })
        return out
    except Exception as e:
        print("[YT bg]",e)
        return []

def fetch_ccn(query, hdv):
    try:
        from bs4 import BeautifulSoup
        r = requests.get(
            "https://clashchamps.com/?s=HDV"+str(hdv)+"+"+query.replace(" ","+"),
            timeout=5, headers={"User-Agent":"Mozilla/5.0"}
        )
        soup = BeautifulSoup(r.text,"html.parser")
        out = []
        for a in soup.select("article h2 a, article h3 a")[:3]:
            out.append({
                "source":"ClashChamps",
                "title":a.text.strip(),
                "url":a.get("href",""),
                "desc":"Guide pro Clash Champs"
            })
        return out
    except Exception as e:
        print("[CCN bg]",e)
        return []

async def store_results(query, hdv, results):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM sources_cache WHERE query=? AND hdv=?",
            (query, hdv)
        )
        for r in results:
            await db.execute(
                "INSERT INTO sources_cache (query,hdv,source,title,url,description,collected_at) VALUES (?,?,?,?,?,?,?)",
                (query, hdv, r["source"], r["title"], r["url"], r["desc"], int(time.time()))
            )
        await db.commit()

async def get_cached_sources(query, hdv):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT source,title,url,description FROM sources_cache WHERE hdv=? AND collected_at > ? ORDER BY collected_at DESC LIMIT 6",
            (hdv, int(time.time())-86400)
        ) as c:
            rows = await c.fetchall()
    return [{"source":r[0],"title":r[1],"url":r[2],"desc":r[3]} for r in rows]

async def scrape_all():
    await init_cache_table()
    print("[BG] Debut du scraping...")
    for hdv in HDV_LIST:
        for query in QUERIES:
            results = []
            results += fetch_youtube(query, hdv)
            results += fetch_ccn(query, hdv)
            if results:
                await store_results(query, hdv, results)
                print(f"[BG] HDV{hdv} {query} : {len(results)} resultats")
            await asyncio.sleep(1)
    print("[BG] Scraping termine !")

async def run_forever():
    while True:
        try:
            await scrape_all()
        except Exception as e:
            print("[BG] Erreur:",e)
        print("[BG] Prochain scraping dans 1h...")
        await asyncio.sleep(3600)
