import os
import requests
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()
YT_KEY = os.getenv("YOUTUBE_API_KEY")

def get_exact_youtube_videos(query):
    results = []
    if not YT_KEY: return results
    try:
        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote(query)}&type=video&maxResults=2&key={YT_KEY}"
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            for item in r.json().get('items', []):
                results.append({'source': 'YouTube', 'title': item['snippet']['title'], 'url': f"https://youtu.be/{item['id']['videoId']}", 'badge': '▶️'})
    except Exception as e: 
        pass
    return results

def format_all_sources(results):
    if not results: return "Aucun replay trouvé."
    return '\n\n'.join([f"{r['badge']} **{r['source']}** : {r['title']}\n🔗 {r['url']}" for r in results])

async def get_all_sources(query, hdv=None): return get_exact_youtube_videos(query)
def format_sources(results): return format_all_sources(results)
def format_links(results): 
    if not results: return "Aucun lien."
    return '\n'.join([f"🔗 {r['url']}" for r in results])

def get_pro_sources(query, hdv=None):
    search_term = f"Clash of Clans TH{hdv} {query} 2026" if hdv else f"Clash of Clans {query} 2026"
    return get_exact_youtube_videos(search_term)
