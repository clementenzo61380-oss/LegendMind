#!/usr/bin/env bash
# Installation locale : venv, .env, logs. PostgreSQL : docker compose ou instance locale.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3.12}"
if ! command -v "$PY" &>/dev/null; then PY="python3"; fi

if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements-dev.txt

mkdir -p logs
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "→ Fichier .env créé depuis .env.example"
fi

if command -v docker &>/dev/null && docker compose version &>/dev/null; then
  echo "→ Démarrage PostgreSQL (docker compose)…"
  docker compose up -d postgres
  echo "   Attends ~10 s que Postgres soit prêt, puis :"
fi

echo ""
echo "1) Édite .env et renseigne au minimum :"
echo "   DISCORD_TOKEN, COC_EMAIL, COC_PASSWORD"
echo "   (DATABASE_URL doit pointer vers ta base — défaut localhost:5432)"
echo ""
echo "2) Applique le schéma SQL :"
echo "   source .venv/bin/activate && PYTHONPATH=. python scripts/migrate.py --apply"
echo ""
echo "3) Lance le bot :"
echo "   PYTHONPATH=. python main.py"
echo ""
