import subprocess, json, sqlite3, time, re

def is_th18(t):
    return bool(re.search(r'\bTH\s*18\b|\bHDV\s*18\b', t, re.IGNORECASE))

queries = [
    'TH18 attack 3 star 2026','TH18 root riders 2026','TH18 throwers 2026',
    'TH18 blizzard lalo 2026','TH18 super witch 2026','TH18 rc charge 2026',
    'TH18 war attack 2026','TH18 legend league 2026','TH18 pro attack 2026',
    'HDV18 attaque 2026','TH18 sui lalo 2026','TH18 fireball loons 2026',
    'TH18 box base 2026','TH18 anti 3 star 2026','TH18 queen charge 2026',
    'TH18 itzu 2026','TH18 blueprint coc 2026','TH18 judo sloth 2026',
    'TH18 attack 2025','TH18 root riders 2025'
]

conn = sqlite3.connect('coc-bot.db')
conn.execute('''CREATE TABLE IF NOT EXISTS youtube_th18 (
    video_id TEXT PRIMARY KEY, titre TEXT, lien TEXT, chaine TEXT,
    duree_sec INTEGER DEFAULT 0, vues INTEGER DEFAULT 0,
    type_base TEXT DEFAULT "inconnu", compo TEXT DEFAULT "inconnu",
    pertinence REAL DEFAULT 0.5, date_publication TEXT, date_ajout REAL)''')
conn.commit()

total = 0
for q in queries:
    print(f'  {q}...', end=' ', flush=True)
    try:
        r = subprocess.run(
            ['python3', '-m', 'yt_dlp', f'ytsearch20:{q}',
             '--dump-json', '--no-download', '--quiet', '--no-warnings'],
            capture_output=True, text=True, timeout=90
        )
        saved = 0
        for line in r.stdout.strip().split('\n'):
            if not line: continue
            try:
                v = json.loads(line)
                if not is_th18(v.get('title','')): continue
                vid = v.get('id','')
                if not vid: continue
                if conn.execute('SELECT 1 FROM youtube_th18 WHERE video_id=?',(vid,)).fetchone():
                    continue
                conn.execute('INSERT OR REPLACE INTO youtube_th18 VALUES (?,?,?,?,?,?,?,?,?,?,?)',(
                    vid, v.get('title','?'), f'https://youtu.be/{vid}',
                    v.get('uploader','?'), int(v.get('duration') or 0),
                    int(v.get('view_count') or 0), 'inconnu', 'inconnu',
                    min(0.3 + int(v.get('view_count') or 0)/500000*0.4, 1.0),
                    (v.get('upload_date') or '')[:10], time.time()))
                saved += 1; total += 1
            except: pass
        conn.commit()
        print(f'+{saved}')
    except subprocess.TimeoutExpired:
        print('TIMEOUT')
    except Exception as e:
        print(f'ERR: {e}')
    time.sleep(2)

conn.close()
print(f'\n✅ Total YouTube ajouté : {total} vidéos')
