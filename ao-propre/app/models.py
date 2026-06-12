"""
Fonctions d'accès aux données (couche modèle — SQL pur, sans ORM).
"""
import json
import sqlite3
from typing import Optional
from .database import get_connection


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def lister_clients() -> list:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM clients ORDER BY nom"
        ).fetchall()


def obtenir_client(client_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()


def obtenir_client_par_slug(slug: str) -> Optional[object]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM clients WHERE slug = ?", (slug,)
        ).fetchone()


def creer_client(donnees: dict) -> int:
    colonnes = [k for k in donnees if donnees[k] is not None]
    placeholders = ", ".join("?" * len(colonnes))
    noms = ", ".join(colonnes)
    valeurs = [donnees[k] for k in colonnes]
    with get_connection() as conn:
        cur = conn.execute(
            f"INSERT INTO clients ({noms}) VALUES ({placeholders})", valeurs
        )
        return cur.lastrowid


def mettre_a_jour_client(client_id: int, donnees: dict):
    mises_a_jour = [f"{k} = ?" for k in donnees]
    valeurs = list(donnees.values()) + [client_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE clients SET {', '.join(mises_a_jour)}, modifie_le = datetime('now') WHERE id = ?",
            valeurs,
        )


def supprimer_client(client_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))


# ---------------------------------------------------------------------------
# Annonces
# ---------------------------------------------------------------------------

def lister_annonces(statut: Optional[str] = None) -> list:
    with get_connection() as conn:
        if statut:
            return conn.execute(
                "SELECT * FROM annonces WHERE statut = ? ORDER BY date_limite",
                (statut,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM annonces ORDER BY date_limite"
        ).fetchall()


def obtenir_annonce(annonce_id: int) -> Optional[object]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM annonces WHERE id = ?", (annonce_id,)
        ).fetchone()


def obtenir_annonce_par_reference(reference: str) -> Optional[object]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM annonces WHERE reference = ?", (reference,)
        ).fetchone()


def creer_ou_mettre_a_jour_annonce(donnees: dict) -> int:
    """Insère une annonce ou ignore si la référence existe déjà."""
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO annonces
               (reference, titre, acheteur, departement, date_publication,
                date_limite, montant_estime, cpv_codes, description, url_source)
               VALUES (:reference, :titre, :acheteur, :departement, :date_publication,
                       :date_limite, :montant_estime, :cpv_codes, :description, :url_source)""",
            donnees,
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM annonces WHERE reference = ?", (donnees["reference"],)
        ).fetchone()
        return row["id"]


def changer_statut_annonce(annonce_id: int, nouveau_statut: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE annonces SET statut = ? WHERE id = ?",
            (nouveau_statut, annonce_id),
        )


# ---------------------------------------------------------------------------
# Dossiers
# ---------------------------------------------------------------------------

def lister_dossiers(statut: Optional[str] = None) -> list:
    sql = """
        SELECT d.*, c.nom AS client_nom, a.titre AS annonce_titre,
               a.date_limite, a.acheteur
        FROM dossiers d
        JOIN clients c ON c.id = d.client_id
        JOIN annonces a ON a.id = d.annonce_id
    """
    params = []
    if statut:
        sql += " WHERE d.statut = ?"
        params.append(statut)
    sql += " ORDER BY a.date_limite"
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def obtenir_dossier(dossier_id: int) -> Optional[object]:
    with get_connection() as conn:
        return conn.execute(
            """SELECT d.*, c.nom AS client_nom, a.titre AS annonce_titre,
                      a.date_limite, a.acheteur, a.reference AS annonce_reference
               FROM dossiers d
               JOIN clients c ON c.id = d.client_id
               JOIN annonces a ON a.id = d.annonce_id
               WHERE d.id = ?""",
            (dossier_id,),
        ).fetchone()


def creer_dossier(client_id: int, annonce_id: int, honoraires: float = None, commission: float = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO dossiers (client_id, annonce_id, honoraires_fixes, taux_commission)
               VALUES (?, ?, ?, ?)""",
            (client_id, annonce_id, honoraires, commission),
        )
        return cur.lastrowid


def changer_statut_dossier(dossier_id: int, nouveau_statut: str, commentaire: str = None):
    with get_connection() as conn:
        ancien = conn.execute(
            "SELECT statut FROM dossiers WHERE id = ?", (dossier_id,)
        ).fetchone()
        ancien_statut = ancien["statut"] if ancien else None
        conn.execute(
            "UPDATE dossiers SET statut = ?, modifie_le = datetime('now') WHERE id = ?",
            (nouveau_statut, dossier_id),
        )
        conn.execute(
            """INSERT INTO historique_statuts (dossier_id, ancien_statut, nouveau_statut, commentaire)
               VALUES (?, ?, ?, ?)""",
            (dossier_id, ancien_statut, nouveau_statut, commentaire),
        )


def historique_dossier(dossier_id: int) -> list:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM historique_statuts WHERE dossier_id = ? ORDER BY date_changement DESC",
            (dossier_id,),
        ).fetchall()

