import os, asyncio, base64, json, re
import requests as req
from dotenv import load_dotenv
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY","")
ROBOFLOW_KEY = os.getenv("ROBOFLOW_API_KEY","")

async def detect_with_roboflow(image_url):
    if not ROBOFLOW_KEY:
        return None
    try:
        r = req.post(
            "https://detect.roboflow.com/clash-of-clans-vop4y/4",
            params={"api_key":ROBOFLOW_KEY,"image":image_url},
            timeout=10
        )
        data = r.json()
        predictions = data.get("predictions",[])
        if predictions:
            best = max(predictions, key=lambda x: x.get("confidence",0))
            confidence = best.get("confidence",0)*100
            label = best.get("class","").lower()
            hdv_match = re.search(r"th(\d{1,2})", label)
            hdv = int(hdv_match.group(1)) if hdv_match else 0
            return {"hdv":hdv,"confidence":confidence,"label":label,"source":"roboflow"}
    except Exception as e:
        print("[Roboflow]",e)
    return None

async def detect_with_gemini(image_url, prompt_extra=""):
    if not GEMINI_KEY:
        return None
    try:
        img_data = req.get(image_url, timeout=10).content
        content_type = "image/png"
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_KEY)
        prompt = (
            "Tu es un expert Clash of Clans. Analyse ce screenshot.\n"
            + prompt_extra
            + "Reponds UNIQUEMENT en JSON valide sans markdown :\n"
            + '{"hdv":X,"type_base":"diamond|box|ring|anti3|hybrid",'
            + '"style":"anti_air|anti_ground|anti_3stars|anti_2stars|farming",'
            + '"description":"description courte",'
            + '"points_forts":"forces de la base",'
            + '"points_faibles":"faiblesses de la base",'
            + '"confidence":X}'
        )
        response = await asyncio.to_thread(lambda: client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=img_data, mime_type=content_type),
                types.Part.from_text(text=prompt)
            ]
        ))
        text = response.text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print("[GeminiVision]",e)
    return None

async def analyze_base_image(image_url):
    default = {"hdv":0,"type_base":"unknown","style":"unknown","description":"Analyse impossible","points_forts":"","points_faibles":"","confidence":0}
    # 1. Roboflow en premier
    robo = await detect_with_roboflow(image_url)
    if robo and robo.get("confidence",0) >= 80:
        # Confiance suffisante avec Roboflow
        result = default.copy()
        result.update({"hdv":robo["hdv"],"confidence":robo["confidence"],"source":"roboflow"})
        # Enrichir avec Gemini pour les details
        gemini = await detect_with_gemini(image_url, "Roboflow a detecte TH"+str(robo["hdv"])+". Confirme et donne les details. ")
        if gemini:
            result.update(gemini)
        return result
    # 2. Gemini Vision si Roboflow insuffisant
    gemini = await detect_with_gemini(image_url)
    if gemini:
        return gemini
    return default

async def analyze_attack_image(image_url):
    default = {"compo":"inconnue","etoiles":0,"pourcentage":0,"erreurs":[],"points_positifs":[],"note":5,"description":"Analyse impossible"}
    if not GEMINI_KEY:
        return default
    try:
        img_data = req.get(image_url, timeout=10).content
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_KEY)
        prompt = (
            "Analyse ce replay d attaque Clash of Clans.\n"
            + "Reponds UNIQUEMENT en JSON valide :\n"
            + '{"compo":"composition detectee","etoiles":X,"pourcentage":X,'
            + '"erreurs":["erreur1","erreur2"],"points_positifs":["point1"],'
            + '"note":X,"description":"description de l attaque"}'
        )
        response = await asyncio.to_thread(lambda: client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=img_data, mime_type="image/png"),
                types.Part.from_text(text=prompt)
            ]
        ))
        import re, json
        match = re.search(r"\{.*\}", response.text.strip(), re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print("[VisionAttack]",e)
    return default
