# AO-PILOT 🎯

Outil local tout-en-un pour l'activité de **rédaction de mémoires techniques
d'appels d'offres** (marchés publics français) à destination des TPE/PME :
nettoyage, BTP second œuvre, espaces verts, sécurité.

## Installation (5 lignes)

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # puis renseignez ANTHROPIC_API_KEY
streamlit run app.py
```

L'application s'ouvre sur http://localhost:8501. Tout fonctionne hors ligne
**sauf** le scan BOAMP et les appels IA (analyse DCE, génération de mémoire).

## Modules

| Module | Page | Description |
|---|---|---|
| **Radar BOAMP** | 📡 | Scan de l'API open data BOAMP par mots-clés / départements / fenêtre de publication. Déduplication par `idweb`, tri par deadline, badge J-X rouge si < 10 jours, statuts (nouveau / vu / prospecté / gagné). |
| **Prospects** | 👥 | Prospects liés aux marchés : saisie rapide, import **et export** CSV, vue tableau ou kanban, rappels de relance automatiques (J+3 après contact) affichés en haut de chaque page. |
| **Emails** | ✉️ | 3 templates éditables (`templates/emails/`) avec fusion de variables `{objet}`, `{acheteur}`, `{deadline}`, `{jours_restants}`, `{prenom_contact}`, `{secteur}`. Bouton copier + lien `mailto:` prérempli + action « marquer contacté/relancé » qui alimente le suivi J+3. Pas d'envoi automatique. |
| **Analyse DCE** | 📑 | Upload de PDF (CCTP, RC, CCAP, avis), extraction texte (pypdf), analyse experte par l'API Anthropic (`claude-sonnet-4-6`). Découpage automatique des DCE volumineux. Sauvegarde en base, liée au marché. |
| **Mémoire technique** | 📝 | Fiche entreprise réutilisable, génération section par section (un appel API par section) selon `templates/memoire_template.md`, règle absolue anti-invention (`[DONNÉE CLIENT : ...]`), **édition du mémoire dans l'UI** (compteur de marqueurs restants), passe critique automatique, téléchargement direct **.docx** (page de garde, sommaire, styles, tableaux) et **.md**. Coût API estimé avant génération. |
| **Dashboard** | 🎯 | KPI (marchés de la semaine, relances dues, mémoires en cours, CA facturé), pipeline visuel détecté → payé, graphiques (par département, par semaine), saisie des factures. |

## Structure

```
aopilot/
├── app.py                    # Interface Streamlit (6 pages)
├── modules/
│   ├── database.py           # SQLite (aopilot.db) : schéma + connexion
│   ├── scraper.py            # Module 1 — Radar BOAMP
│   ├── prospects.py          # Module 2 — Prospects & relances
│   ├── emails.py             # Module 3 — Templates & fusion d'emails
│   ├── dce.py                # Module 4 — Analyse de DCE (IA)
│   └── memoire.py            # Module 5 — Génération de mémoire (IA)
├── templates/
│   ├── emails/               # 3 templates d'emails éditables
│   └── memoire_template.md   # Structure du mémoire (remplaçable par la vôtre)
├── outputs/                  # Exports .docx / .md
├── tests/                    # pytest : parsing BOAMP + fusion emails
└── aopilot.db                # Base SQLite (créée au premier lancement)
```

## Personnaliser le template de mémoire

Remplacez `templates/memoire_template.md` par votre propre structure. Chaque
section commence par `## Titre` ; le texte sous le titre sert de consignes de
rédaction à l'IA.

## Tests

```bash
pytest tests/ -v
```

## Notes

- La clé API est lue depuis `.env` (variable `ANTHROPIC_API_KEY`), jamais stockée en base.
- Coûts API indicatifs (modèle `claude-sonnet-4-6`) : ~0,05–0,30 $ par analyse
  de DCE, ~0,30–0,80 $ par mémoire complet selon le volume.
- En cas d'erreur 403 ou de timeout de l'API BOAMP, le radar réessaie 3 fois
  puis affiche un message clair.
