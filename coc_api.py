import os
import requests
from dotenv import load_dotenv

load_dotenv()
COC_KEY = os.getenv('COC_API_KEY')
BASE_URL = 'https://api.clashofclans.com/v1'

def get_headers():
    return {
        'Accept': 'application/json',
        'Authorization': f'Bearer {COC_KEY}'
    }

async def get_player(tag):
    tag = tag.replace('#', '%23')
    r = requests.get(f"{BASE_URL}/players/{tag}", headers=get_headers())
    return r.json() if r.status_code == 200 else None

async def get_clan(tag):
    tag = tag.replace('#', '%23')
    r = requests.get(f"{BASE_URL}/clans/{tag}", headers=get_headers())
    return r.json() if r.status_code == 200 else None

async def get_current_war(clan_tag):
    tag = clan_tag.replace('#', '%23')
    r = requests.get(f"{BASE_URL}/clans/{tag}/currentwar", headers=get_headers())
    return r.json() if r.status_code == 200 else None
