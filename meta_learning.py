import os
import json
from youtube_transcript_api import YouTubeTranscriptApi
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def update_meta_knowledge():
    # Simulation : Ici le bot enregistre ce qu'il a appris
    knowledge = {
        "18": "Méta Avril 2026 : Utiliser le 'Symmetry Breaker' avec 4 Root Riders et le nouveau sort de Rage Héroïque.",
        "17": "Méta Avril 2026 : Valkyries Évoluées avec sort de Rappel.",
        "16": "Méta Avril 2026 : Super Sorcières avec Druides pour le soin continu."
    }
    with open("meta_brain.json", "w") as f:
        json.dump(knowledge, f)
    print("✅ Le cerveau du bot a été mis à jour avec les dernières stratégies 2026 !")

if __name__ == "__main__":
    update_meta_knowledge()
