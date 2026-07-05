"""Tests du module prospects sur une base SQLite temporaire."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.database as db
from modules import prospects


@pytest.fixture(autouse=True)
def base_temporaire(tmp_path: Path, monkeypatch) -> None:
    """Chaque test travaille sur sa propre base SQLite jetable."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_ajout_et_listing() -> None:
    pid = prospects.ajouter_prospect("Alpha", ville="Rennes", email="a@b.fr")
    liste = prospects.lister_prospects()
    assert len(liste) == 1
    assert liste[0]["id"] == pid
    assert liste[0]["statut"] == "à contacter"


def test_statut_invalide_rejete() -> None:
    with pytest.raises(ValueError):
        prospects.ajouter_prospect("Alpha", statut="inconnu")


def test_contact_enregistre_la_date() -> None:
    pid = prospects.ajouter_prospect("Alpha")
    prospects.changer_statut_prospect(pid, "contacté")
    prospect = prospects.lister_prospects()[0]
    assert prospect["statut"] == "contacté"
    assert prospect["date_contact"]  # date du jour enregistrée


def test_relance_due_apres_3_jours() -> None:
    pid = prospects.ajouter_prospect("Alpha")
    prospects.changer_statut_prospect(pid, "contacté")
    assert prospects.relances_dues() == []  # contacté aujourd'hui : pas encore dû
    conn = db.get_connection()
    conn.execute("UPDATE prospects SET date_contact = date('now', '-3 days')")
    conn.commit()
    conn.close()
    assert len(prospects.relances_dues()) == 1


def test_import_csv_ignore_lignes_sans_entreprise() -> None:
    nb = prospects.importer_csv(
        "entreprise,ville,email\nAlpha,Rennes,a@b.fr\n,,vide@x.fr\nBeta,Vannes,\n"
    )
    assert nb == 2
    assert {p["entreprise"] for p in prospects.lister_prospects()} == {"Alpha", "Beta"}


def test_export_csv_reimportable() -> None:
    """L'export CSV se réimporte tel quel (aller-retour sans perte)."""
    prospects.ajouter_prospect("Alpha", ville="Rennes", email="a@b.fr", secteur="nettoyage")
    prospects.ajouter_prospect("Beta", ville="Vannes")
    contenu = prospects.exporter_csv()
    assert contenu.startswith("entreprise,")

    # Réimport dans une base vidée
    conn = db.get_connection()
    conn.execute("DELETE FROM prospects")
    conn.commit()
    conn.close()
    assert prospects.importer_csv(contenu) == 2
    assert {p["entreprise"] for p in prospects.lister_prospects()} == {"Alpha", "Beta"}
