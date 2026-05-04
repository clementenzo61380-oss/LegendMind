import os
import json
import requests
from bs4 import BeautifulSoup

def search_youtube_strats(hdv_level):
    query = f"TH{hdv_level} meta attack 2026"
    url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    print(f"🌐 Recherche YouTube pour HDV {hdv_level}...")
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # On cherche les IDs de vidéos dans le texte brut (méthode rapide)
    video_ids = list(set(re.findall(r"watch\?v=([\w-]{11})", response.text)))[:3]
    
    videos = []
    for vid_id in video_ids:
        videos.append({
            "title": f"Stratégie Pro HDV {hdv_level}",
            "link": f"https://www.youtube.com/watch?v={vid_id}"
        })
    return videos

import re
if __name__ == "__main__":
    # On simule une mise à jour globale
    knowledge = {}
    for hdv in ["16", "17", "18"]:
        knowledge[hdv] = {
            "last_strats": search_youtube_strats(hdv)
        }
    
    with open("meta_brain.json", "w") as f:
        json.dump(knowledge, f)
    print("✅ Cerveau mis à jour avec de vrais liens YouTube !")
