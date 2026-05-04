import aiosqlite, time, os
from dotenv import load_dotenv
load_dotenv()
DB_PATH = os.getenv("DB_PATH","data/bot.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS cache(cache_key TEXT PRIMARY KEY,value TEXT,source TEXT,created INTEGER);
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id TEXT,user_id TEXT,command TEXT,result TEXT,ai_used TEXT,cost REAL,created INTEGER);
            CREATE TABLE IF NOT EXISTS blacklist(user_id TEXT PRIMARY KEY,reason TEXT,created INTEGER);
            CREATE TABLE IF NOT EXISTS rate_limit(user_id TEXT PRIMARY KEY,count INTEGER,window_start INTEGER);
            CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT,guild_id TEXT,lien TEXT,note INTEGER,commentaire TEXT,created INTEGER);
            CREATE TABLE IF NOT EXISTS replays_3stars(id INTEGER PRIMARY KEY AUTOINCREMENT,player_tag TEXT,guild_id TEXT,hdv INTEGER,base_type TEXT,compo TEXT,lien TEXT,note TEXT,created INTEGER);
        """)
        await db.commit()

async def get_cache(key):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT value,created FROM cache WHERE cache_key=?",(key,)) as c:
                row = await c.fetchone()
                if row and (time.time()-row[1])<86400:
                    return row[0]
    except Exception:
        pass
    return None

async def set_cache(key,value,source="",hours=24):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO cache(cache_key,value,source,created) VALUES(?,?,?,?)",(key,value,source,int(time.time())))
            await db.commit()
    except Exception:
        pass

async def is_blacklisted(user_id):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM blacklist WHERE user_id=?",(user_id,)) as c:
                return await c.fetchone() is not None
    except Exception:
        return False

async def check_rate_limit(user_id,limit=10,window=3600):
    try:
        now = int(time.time())
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT count,window_start FROM rate_limit WHERE user_id=?",(user_id,)) as c:
                row = await c.fetchone()
            if row:
                count,start = row
                if now-start>window:
                    await db.execute("UPDATE rate_limit SET count=1,window_start=? WHERE user_id=?",(now,user_id))
                elif count>=limit:
                    await db.commit()
                    return False
                else:
                    await db.execute("UPDATE rate_limit SET count=count+1 WHERE user_id=?",(user_id,))
            else:
                await db.execute("INSERT INTO rate_limit(user_id,count,window_start) VALUES(?,1,?)",(user_id,now))
            await db.commit()
        return True
    except Exception:
        return True

async def log_command(guild_id,user_id,command,result,ai_used="",cost=0.0):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO logs(guild_id,user_id,command,result,ai_used,cost,created) VALUES(?,?,?,?,?,?,?)",(str(guild_id),str(user_id),command,result,ai_used,cost,int(time.time())))
            await db.commit()
    except Exception:
        pass

def init_youtube_table():
    import sqlite3, os
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
            compo_attaque TEXT,
            resultat TEXT DEFAULT 'inconnu',
            point_entree TEXT,
            timestamp_attaque TEXT,
            pertinence_score REAL DEFAULT 0.0,
            tags TEXT,
            date_ajout REAL
        );
    """)
    conn.commit()
    conn.close()
    print("[DB] Table youtube_th18 initialisée pour la méta 2026.")

if __name__ == "__main__":
    init_youtube_table()

def init_youtube_table():
    import sqlite3, os
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
            compo_attaque TEXT,
            resultat TEXT DEFAULT 'inconnu',
            point_entree TEXT,
            timestamp_attaque TEXT,
            pertinence_score REAL DEFAULT 0.0,
            tags TEXT,
            date_ajout REAL
        );
    """)
    conn.commit()
    conn.close()
    print("[DB] Table youtube_th18 initialisée pour la méta 2026.")

if __name__ == "__main__":
    init_youtube_table()
