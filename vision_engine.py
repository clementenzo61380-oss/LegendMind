import os, sqlite3, asyncio, base64, aiohttp, io, json
from groq import Groq
from PIL import Image
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

async def analyze_screenshot(image_url, hdv_force=None):
    # Modèles STABLES (Production)
    MODELS = ["llama-3.2-11b-vision", "llama-3.2-90b-vision", "llama-3.2-11b-vision-instruct"]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=5) as resp:
                img_data = await resp.read()
        
        img = Image.open(io.BytesIO(img_data))
        img.thumbnail((400, 400)) 
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=30) 
        base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')

        completion = None
        for model_name in MODELS:
            try:
                completion = await asyncio.to_thread(
                    client.chat.completions.create,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "TH18 base type: Box, Ring, or Diamond? One word answer."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }],
                    model=model_name,
                    temperature=0,
                    max_tokens=10
                )
                print(f"✅ Modèle utilisé : {model_name}")
                break
            except: continue

        if not completion: return {'hdv': '18', 'base_type': 'Inconnu', 'strategy': "Serveurs IA saturés."}

        base_type = completion.choices[0].message.content.strip().replace(".", "")

        conn = sqlite3.connect("coc_bot.db")
        c = conn.cursor()
        c.execute("SELECT titre, lien FROM youtube_th18 WHERE titre LIKE ? LIMIT 3", (f"%{base_type}%",))
        replays = [{"t": r[0], "u": r[1]} for r in c.fetchall()]
        conn.close()

        return {
            'hdv': '18',
            'base_type': base_type,
            'strategy': f"Base identifiée : **{base_type}**. Aucun Aigle (TH18).",
            'replays': replays
        }
    except Exception as e:
        return {'hdv': '18', 'base_type': 'Erreur', 'strategy': f"Erreur : {e}", 'replays': []}
