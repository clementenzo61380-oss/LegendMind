#!/usr/bin/env python3
"""Applique ``schema.sql`` + la file de migrations (identique au boot du bot).

Usage::

    cd coc_coach_pro
    python scripts/migrate.py --apply
    python scripts/migrate.py --dry-run   # affiche seulement la taille des SQL
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Résout les imports `services` depuis la racine du package.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import infer_database_ssl  # noqa: E402
from services.db import Database  # noqa: E402


async def _apply() -> None:
    load_dotenv(_ROOT / ".env")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "DATABASE_URL manquant : renseigne-le dans .env "
            "(PostgreSQL doit tourner avant cette étape).",
        )
    db = Database(dsn, ssl=infer_database_ssl())
    await db.connect()
    print("Migrations + schéma : OK")
    await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migration LegendMind V3")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ouvre le pool, applique schema.sql + _MIGRATIONS, ferme.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ne se connecte pas : uniquement vérifier que le module charge.",
    )
    args = parser.parse_args()
    if args.dry_run:
        schema = (_ROOT / "schema.sql").read_text(encoding="utf-8")
        print(f"schema.sql : {len(schema)} caractères (dry-run, rien d'appliqué).")
        return
    if not args.apply:
        parser.print_help()
        raise SystemExit(1)
    asyncio.run(_apply())


if __name__ == "__main__":
    main()
