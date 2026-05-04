import os
import requests
from dotenv import load_dotenv
load_dotenv()
YT_KEY = os.getenv("YOUTUBE_API_KEY", "")

def search_youtube_coc(query, max_results=3):
    if not YT_KEY:
        return []
    try:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "q": query + " Clash of Clans 2025",
                    "type": "video", "maxResults": max_results, "key": YT_KEY},
            timeout=5
        )
        results = []
        for item in r.json().get("items", []):
            results.append({
                "title": item["snippet"]["title"],
                "url": "https://youtu.be/" + item["id"]["videoId"],
                "description": item["snippet"]["description"][:400],
                "channel": item["snippet"]["channelTitle"]
            })
        return results
    except Exception as e:
        print("[YouTube]", e)
        return []

def youtube_context(videos):
    if not videos:
        return ""
    lines = ["Informations issues de vraies videos Clash of Clans sur YouTube :"]
    for v in videos:
        lines.append("- " + v["title"] + " (" + v["channel"] + ") : " + v["description"])
    return "\n".join(lines)
