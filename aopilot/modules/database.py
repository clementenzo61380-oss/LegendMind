"""Couche de persistance SQLite d'AO-PILOT.

Toutes les tables sont créées au premier lancement via init_db().
Le fichier `aopilot.db` vit à la racine du projet.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Chemin de la base : racine du projet (dossier parent de modules/)
DB_PATH: Path = Path(__file__).resolve().parent.parent / "aopilot.db"

# Statuts autorisés pour un marché détecté
STATUTS_MARCHE: list[str] = ["nouveau", "vu", "prospecté", "gagné"]

# Statuts autorisés pour un prospect
STATUTS_PROSPECT: list[str] = [
    "à contacter",
    "contacté",
    "relancé",
    "répondu",
    "client",
    "perdu",
]

# Étapes du pipeline commercial (dashboard)
ETAPES_PIPELINE: list[str] = [
    "détecté",
    "prospecté",
    "répondu",
    "client",
    "livré",
    "payé",
]


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Ouvre une connexion SQLite avec les lignes accessibles par nom de colonne."""
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Crée toutes les tables si elles n'existent pas encore."""
    conn = get_connection(db_path)
    try:
        conn.executescript(
            """
            -- Marchés détectés sur le BOAMP
            CREATE TABLE IF NOT EXISTS marches (
                idweb              TEXT PRIMARY KEY,
                dateparution       TEXT,
                datelimitereponse  TEXT,
                nomacheteur        TEXT,
                objet              TEXT,
                code_departement   TEXT,
                url_avis           TEXT,
                statut             TEXT NOT NULL DEFAULT 'nouveau',
                date_ajout         TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Prospects liés (ou non) à un marché
            CREATE TABLE IF NOT EXISTS prospects (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                marche_idweb  TEXT REFERENCES marches(idweb) ON DELETE SET NULL,
                entreprise    TEXT NOT NULL,
                ville         TEXT,
                email         TEXT,
                telephone     TEXT,
                prenom_contact TEXT,
                secteur       TEXT,
                source        TEXT,
                statut        TEXT NOT NULL DEFAULT 'à contacter',
                date_contact  TEXT,
                notes         TEXT,
                date_ajout    TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Analyses de DCE produites par l'IA
            CREATE TABLE IF NOT EXISTS analyses_dce (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                marche_idweb  TEXT REFERENCES marches(idweb) ON DELETE SET NULL,
                nom_fichiers  TEXT,
                resultat      TEXT NOT NULL,
                date_analyse  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Fiches entreprises clientes (réutilisables pour les mémoires)
            CREATE TABLE IF NOT EXISTS fiches_entreprise (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                raison_sociale TEXT NOT NULL,
                siret          TEXT,
                effectif       TEXT,
                ca             TEXT,
                refs           TEXT,
                certifications TEXT,
                encadrement    TEXT,
                materiel       TEXT,
                produits       TEXT,
                date_maj       TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Mémoires techniques générés
            CREATE TABLE IF NOT EXISTS memoires (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                marche_idweb  TEXT REFERENCES marches(idweb) ON DELETE SET NULL,
                fiche_id      INTEGER REFERENCES fiches_entreprise(id) ON DELETE SET NULL,
                titre         TEXT,
                contenu_md    TEXT,
                critique      TEXT,
                statut        TEXT NOT NULL DEFAULT 'en cours',
                date_creation TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Factures (saisie manuelle, pour le KPI CA)
            CREATE TABLE IF NOT EXISTS factures (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                client   TEXT NOT NULL,
                montant  REAL NOT NULL,
                date_facture TEXT,
                statut   TEXT NOT NULL DEFAULT 'dû'
            );

            -- Réglages persistants (clé/valeur) : filtres de scan, taux, etc.
            CREATE TABLE IF NOT EXISTS reglages (
                cle    TEXT PRIMARY KEY,
                valeur TEXT
            );

            -- Commissions sur dossiers gagnés (modèle : % du montant du marché)
            CREATE TABLE IF NOT EXISTS commissions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                marche_idweb   TEXT REFERENCES marches(idweb) ON DELETE SET NULL,
                client         TEXT NOT NULL,
                montant_marche REAL NOT NULL,
                taux           REAL NOT NULL,
                statut         TEXT NOT NULL DEFAULT 'en attente',
                date_creation  TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def lire_reglage(cle: str, defaut: str = "") -> str:
    """Lit un réglage persistant (retourne `defaut` s'il n'existe pas)."""
    conn = get_connection()
    try:
        ligne = conn.execute(
            "SELECT valeur FROM reglages WHERE cle = ?", (cle,)
        ).fetchone()
        return ligne["valeur"] if ligne else defaut
    finally:
        conn.close()


def ecrire_reglage(cle: str, valeur: str) -> None:
    """Écrit (ou remplace) un réglage persistant."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO reglages (cle, valeur) VALUES (?, ?) "
            "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
            (cle, valeur),
        )
        conn.commit()
    finally:
        conn.close()
