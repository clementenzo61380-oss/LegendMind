import subprocess, json, sqlite3, time, os

DB_FILE = "coc-bot.db"
QUERIES = [
    'TH18 attack 3 star', 'TH18 war strategy', 'TH18 clash of clans 2026',
    'TH18 hybrid', 'TH18 lalo', 'TH18 queen walk', 'TH18 super archer',
    'TH18 fireball', 'TH18 smash', 'TH18 root riders', 'TH18 new meta',
    'HDV18 attaque', 'TH18 legend league', 'TH18 CWL', 'TH18 pro attack',
    'TH18 itzu', 'TH18 judo sloth', 'TH18 carbonfin', 'TH18 ash coc'
]

def run_scraper_until_18h():
    target_time = time.mktime(time.strptime('2026-04-28 18:00:00', '%Y-%m-%d %H:%M:%S'))
    conn = sqlite3.connect(DB_FILE)
    conn.execute('''CREATE TABLE IF NOT EXISTS youtube_th (
        video_id TEXT PRIMARY KEY, titre TEXT, lien TEXT, chaine TEXT,
        duree_sec INTEGER, vues INTEGER, date_ajout REAL)''')
    conn.commit()

    print("Scraping massif activé jusqu'à 18h00.")
    while time.time() < target_time:
        for q in QUERIES:
            try:
                r = subprocess.run(
                    ['python3', '-m', 'yt_dlp', f'ytsearch50:{q}', '--dump-json', '--no-download', '--quiet'],
                    capture_output=True, text=True, timeout=120
                )
                count = 0
                for line in r.stdout.splitlines():
                    if not line:
                        continue
                    try:
                        v = json.loads(line)
                        vid = v.get('id')
                        if not vid:
                            continue
                        if conn.execute('SELECT 1 FROM youtube_th WHERE video_id=?', (vid,)).fetchone():
                            continue
                        conn.execute(
                            'INSERT INTO youtube_th VALUES (?,?,?,?,?,?,?)',
                            (vid, v.get('title'), f'https://youtu.be/{vid}', v.get('uploader'),
                             v.get('duration'), v.get('view_count'), time.time())
                        )
                        count += 1
                    except:
                        pass
                conn.commit()
                print(f"[{time.strftime('%H:%M:%S')}] {q} : +{count}")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] {q} : ERREUR")
            time.sleep(10)
        time.sleep(600)

    conn.close()
    print("Entraînement YouTube terminé à 18h00.")

if __name__ == "__main__":
    run_scraper_until_18h()
