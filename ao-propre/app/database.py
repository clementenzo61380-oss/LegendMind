"""
Connexion SQLite et initialisation du schéma de la base de données.
"""
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "aopropre.db"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Fiches clients
CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nom         TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    siret       TEXT,
    adresse     TEXT,
    code_postal TEXT,
    ville       TEXT,
    telephone   TEXT,
    email       TEXT,
    site_web    TEXT,

    -- Informations métier
    effectif            INTEGER,
    ca_annuel           REAL,
    annee_creation      INTEGER,
    zones_intervention  TEXT,   -- JSON liste de départements
    certifications      TEXT,   -- JSON liste (ex : ISO 9001, NF...)
    references_clients  TEXT,   -- Texte libre ou JSON

    -- Matériels et méthodes
    materiels           TEXT,
    produits_utilises   TEXT,
    demarche_qualite    TEXT,
    politique_rse       TEXT,

    -- Assurances
    assureur            TEXT,
    numero_police       TEXT,
    montant_garantie    REAL,

    -- Contacts internes
    contact_nom         TEXT,
    contact_poste       TEXT,
    contact_telephone   TEXT,
    contact_email       TEXT,

    -- Métadonnées
    cree_le     TEXT DEFAULT (datetime('now')),
    modifie_le  TEXT DEFAULT (datetime('now'))
);

-- Annonces BOAMP détectées par la veille
CREATE TABLE IF NOT EXISTS annonces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    reference       TEXT NOT NULL UNIQUE,   -- Référence BOAMP
    titre           TEXT NOT NULL,
    acheteur        TEXT,
    departement     TEXT,
    date_publication TEXT,
    date_limite     TEXT,
    montant_estime  REAL,
    cpv_codes       TEXT,   -- JSON liste
    description     TEXT,
    url_source      TEXT,
    statut          TEXT DEFAULT 'repérée',  -- repérée | proposée au client | en rédaction | déposée | gagnée | perdue
    cree_le         TEXT DEFAULT (datetime('now'))
);

-- Dossiers de réponse (lien client <-> annonce)
CREATE TABLE IF NOT EXISTS dossiers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    annonce_id      INTEGER NOT NULL REFERENCES annonces(id) ON DELETE CASCADE,

    statut          TEXT DEFAULT 'en rédaction',
    honoraires_fixes REAL,
    taux_commission  REAL,   -- en % du montant du marché

    -- Chemin du mémoire technique généré
    chemin_memoire  TEXT,
    version_memoire INTEGER DEFAULT 1,

    notes           TEXT,
    cree_le         TEXT DEFAULT (datetime('now')),
    modifie_le      TEXT DEFAULT (datetime('now')),

    UNIQUE(client_id, annonce_id)
);

-- Historique des statuts des dossiers
CREATE TABLE IF NOT EXISTS historique_statuts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id  INTEGER NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    ancien_statut TEXT,
    nouveau_statut TEXT NOT NULL,
    commentaire TEXT,
    date_changement TEXT DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    """Retourne une connexion à la base SQLite avec row_factory activé."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Crée les tables si elles n'existent pas encore."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
    print(f"Base de données initialisée : {DB_PATH}")
