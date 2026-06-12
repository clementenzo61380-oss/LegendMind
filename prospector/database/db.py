import sqlite3
import os
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(os.getenv("DB_PATH", "data/prospector.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT DEFAULT 'manual',
    raw_text TEXT,
    type_travaux TEXT,
    budget_estime REAL DEFAULT 0,
    localisation TEXT DEFAULT 'Rennes',
    urgence INTEGER DEFAULT 3,
    contact_nom TEXT,
    contact_tel TEXT,
    contact_email TEXT,
    notes TEXT,
    score INTEGER DEFAULT 0,
    statut TEXT DEFAULT 'nouveau',
    artisan_id INTEGER,
    montant_chantier_estime REAL DEFAULT 0,
    commission_attendue REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (artisan_id) REFERENCES artisans(id)
);

CREATE TABLE IF NOT EXISTS artisans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    metier TEXT,
    ville TEXT DEFAULT 'Rennes',
    siren TEXT,
    telephone TEXT,
    email TEXT,
    forme_juridique TEXT,
    date_creation TEXT,
    effectif INTEGER DEFAULT 0,
    score_fiabilite INTEGER DEFAULT 50,
    contrat_signe INTEGER DEFAULT 0,
    taux_commission REAL DEFAULT 5.0,
    historique_paiement TEXT DEFAULT 'inconnu',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transmissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    artisan_id INTEGER NOT NULL,
    date_transmission TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    email_draft TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lead_id) REFERENCES leads(id),
    FOREIGN KEY (artisan_id) REFERENCES artisans(id)
);

CREATE TABLE IF NOT EXISTS commissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    artisan_id INTEGER,
    transmission_id INTEGER,
    montant REAL DEFAULT 0,
    taux REAL DEFAULT 5.0,
    montant_chantier REAL DEFAULT 0,
    date_echeance TEXT,
    date_paiement TEXT,
    statut TEXT DEFAULT 'en_attente',
    relances_count INTEGER DEFAULT 0,
    derniere_relance TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lead_id) REFERENCES leads(id),
    FOREIGN KEY (artisan_id) REFERENCES artisans(id),
    FOREIGN KEY (transmission_id) REFERENCES transmissions(id)
);

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artisan_id INTEGER NOT NULL,
    statut TEXT DEFAULT 'brouillon',
    fichier_docx TEXT,
    fichier_pdf TEXT,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    date_signature TEXT,
    notes TEXT,
    FOREIGN KEY (artisan_id) REFERENCES artisans(id)
);

CREATE TABLE IF NOT EXISTS ai_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,
    reference_id INTEGER,
    reference_type TEXT,
    contenu TEXT,
    validated INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
    # Migrations pour les bases existantes (ADD COLUMN idempotent via try/except)
    migrations = [
        "ALTER TABLE commissions ADD COLUMN date_paiement TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
    conn.commit()
    conn.close()


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    return [dict(r) for r in rows]
