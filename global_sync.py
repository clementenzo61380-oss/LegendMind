import yt_dlp
import sqlite3
import time

def deep_scan():
    print("🌪️ Scan mondial TH18 en cours...")
    queries = ["TH18 3 stars pro attack", "HDV18 perf 2026", "Town Hall 18 meta"]
    
    ydl_opts = {
        'quiet': True, 
        'extract_flat': True, 
        'playlist_items': '30',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    all_videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for q in queries:
            try:
                search = ydl.extract_info(f"ytsearch30:{q}", download=False)
                if 'entries' in search:
                    all_videos.extend(search['entries'])
            except:
                continue

    conn = sqlite3.connect("coc_bot.db")
    c = conn.cursor()
    for v in all_videos:
        if v.get('id'):
            c.execute("INSERT OR IGNORE INTO youtube_th18 (video_id, titre, lien, date_ajout) VALUES (?, ?, ?, ?)",
                      (v.get('id'), v.get('title'), f"https://youtu.be/{v.get('id')}", time.time()))
    conn.commit()
    conn.close()
    print(f"✅ {len(all_videos)} vidéos indexées.")

if __name__ == "__main__":
    deep_scan()
