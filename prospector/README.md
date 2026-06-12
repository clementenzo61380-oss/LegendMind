# PROSPECTOR — Système de prospection BTP / Rénovation énergétique

Application locale pour apporteur d'affaires BTP — Rennes Métropole (35).

## Fonctionnalités

| Module | Description |
|---|---|
| 🎯 Leads | Scoring automatique, import IA (copier-coller), veille open data Sitadel |
| ⚙️ Auto-prospection | Veille en tâche de fond : import + dédup + qualification automatiques toutes les 6h |
| 🔨 Artisans | Enrichissement Sirene (INSEE), génération de messages d'approche IA |
| 📄 Contrats | Génération DOCX + PDF, suivi brouillon → envoyé → signé |
| 💰 Commissions | Échéancier, relances IA (J+30/J+45/J+60), mise en demeure |
| 🏠 Dashboard | Pipeline Kanban, alertes, CA mensuel |
| 🤖 Assistant IA | Chat contextuel, extraction de leads, estimation de chantiers |

## Installation (Mac / Linux)

```bash
cd prospector/

# 1. Créer l'environnement virtuel
python3 -m venv .venv
source .venv/bin/activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer l'environnement
cp .env.example .env
# Éditez .env : ajoutez votre ANTHROPIC_API_KEY et vos informations

# 4. Lancer
python app.py
```

Ouvrez http://127.0.0.1:8000

## Configuration (.env)

```env
# Clé API Anthropic (obligatoire pour les fonctionnalités IA)
ANTHROPIC_API_KEY=sk-ant-...

# Votre identité pour les contrats
APPORTEUR_NOM=Prénom NOM
APPORTEUR_SIREN=123456789
APPORTEUR_ADRESSE=Adresse, 35000 Rennes
APPORTEUR_TELEPHONE=06 XX XX XX XX
APPORTEUR_EMAIL=contact@exemple.fr

# Taux de commission par défaut
COMMISSION_DEFAUT=5.0

# Auto-prospection (tâche de fond)
AUTO_PROSPECT_ENABLED=true       # Active la veille automatique
AUTO_PROSPECT_INTERVAL_HOURS=6   # Fréquence des passages
AUTO_QUALIFY_SCORE=70            # Score à partir duquel un lead passe en "qualifié" tout seul
```

## Auto-prospection : ce qui est automatisé (et ce qui ne peut pas l'être)

**Automatisé** (tourne tout seul tant que l'app est lancée) :
- Interrogation de l'open data Sitadel toutes les 6h (permis de construire = futurs chantiers)
- Déduplication contre les leads déjà en base
- Scoring + passage automatique en "qualifié" si score ≥ 70
- Alertes dashboard sur les leads à traiter

**Volontairement NON automatisé** (obligations légales) :
- Scraping Facebook / Leboncoin → interdit par leurs CGU (utilisez l'import IA copier-coller)
- Envoi automatique d'emails/SMS aux particuliers → interdit sans consentement préalable (RGPD/LCEN).
  Tous les messages sont générés en **draft** : c'est vous qui validez et envoyez.

## Import CSV Artisans

Format attendu (en-tête obligatoire) :

```csv
nom,metier,ville,siren,telephone,email
SARL Martin Plomberie,Plombier,Rennes,123456789,0612345678,contact@martin-plomberie.fr
```

## Règles de scoring leads (modifiables)

Éditez `config/scoring.json` pour ajuster les points par critère :
- Budget estimé (4 seuils)
- Urgence (points par niveau 1-5)
- Complétude coordonnées (téléphone, email, nom)
- Localisation Rennes Métropole
- Type de travaux (chaque catégorie a ses points)

## Architecture

```
prospector/
├── app.py              # Entrée FastAPI
├── database/db.py      # SQLite + schéma
├── routers/            # Endpoints API REST
│   ├── leads.py
│   ├── artisans.py
│   ├── contracts.py
│   ├── crm.py          # Transmissions + commissions + alertes
│   ├── dashboard.py
│   └── ai_assistant.py
├── services/           # Logique métier
│   ├── scoring.py      # Scoring leads + artisans
│   ├── open_data.py    # API data.gouv.fr / Sitadel
│   ├── sirene.py       # API Sirene (INSEE, gratuit)
│   ├── ai_service.py   # Wrapper Anthropic
│   └── document_generator.py  # DOCX + PDF
├── static/             # Frontend SPA
└── generated_docs/     # Contrats générés (gitignored)
```

## Règles absolues

1. **Aucun envoi automatique** — tous les emails/SMS sont des drafts à valider manuellement
2. **Pas de scraping** — uniquement des APIs publiques légales (data.gouv.fr, Sirene)
3. **Contrats** — mention "À faire valider par un professionnel du droit" intégrée

## API Documentation

Interface Swagger : http://127.0.0.1:8000/docs

## Base de données

Fichier SQLite local : `data/prospector.db`

Tables : `leads`, `artisans`, `transmissions`, `commissions`, `contracts`, `ai_drafts`
