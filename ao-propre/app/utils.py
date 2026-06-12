"""
Fonctions utilitaires : slug, gestion des fichiers clients.
"""
import re
import unicodedata
from pathlib import Path

# Racine du projet (dossier ao-propre/)
RACINE = Path(__file__).parent.parent
DOSSIER_CLIENTS = RACINE / "clients"
DOSSIER_DOSSIERS = RACINE / "dossiers"

# Pièces administratives attendues pour répondre à un marché public.
# La clé sert de préfixe de nom de fichier dans clients/<slug>/docs/
PIECES_ADMINISTRATIVES = [
    ("kbis",        "Extrait Kbis (moins de 3 mois)"),
    ("urssaf",      "Attestation de vigilance URSSAF"),
    ("fiscale",     "Attestation de régularité fiscale"),
    ("assurance",   "Attestation d'assurance RC professionnelle"),
    ("rib",         "RIB de l'entreprise"),
    ("dc1",         "Formulaire DC1 (lettre de candidature)"),
    ("dc2",         "Formulaire DC2 (déclaration du candidat)"),
]


def slugifier(texte: str) -> str:
    """Transforme un nom d'entreprise en slug pour les chemins de fichiers.
    Ex : 'Net'Éclair Bretagne' -> 'net-eclair-bretagne'
    """
    texte = unicodedata.normalize("NFKD", texte)
    texte = texte.encode("ascii", "ignore").decode("ascii")
    texte = re.sub(r"[^a-zA-Z0-9]+", "-", texte).strip("-").lower()
    return texte or "client"


def chemin_client(slug: str) -> Path:
    """Retourne le dossier racine d'un client (clients/<slug>/)."""
    return DOSSIER_CLIENTS / slug


def preparer_dossier_client(slug: str) -> Path:
    """Crée l'arborescence clients/<slug>/docs/ si nécessaire."""
    docs = chemin_client(slug) / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    return docs


def verifier_pieces(slug: str) -> list:
    """Vérifie quelles pièces administratives sont présentes dans docs/.
    Une pièce est considérée présente si un fichier commence par sa clé.
    Retourne une liste de dicts {cle, libelle, present, fichier}.
    """
    docs = chemin_client(slug) / "docs"
    fichiers = list(docs.glob("*")) if docs.exists() else []
    resultat = []
    for cle, libelle in PIECES_ADMINISTRATIVES:
        trouve = next((f.name for f in fichiers if f.name.lower().startswith(cle)), None)
        resultat.append({
            "cle": cle,
            "libelle": libelle,
            "present": trouve is not None,
            "fichier": trouve,
        })
    return resultat


def logo_existe(slug: str) -> bool:
    """Indique si le client a un logo (clients/<slug>/logo.png)."""
    return (chemin_client(slug) / "logo.png").exists()
