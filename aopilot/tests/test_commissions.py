"""Tests du suivi des commissions sur dossiers gagnés."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.database as db
from modules import commissions, scraper


def _creer_marche(idweb: str) -> None:
    """La table commissions référence marches : crée un marché de test."""
    scraper.enregistrer_marches([{
        "idweb": idweb, "dateparution": "2026-07-01",
        "datelimitereponse": "2026-08-01", "nomacheteur": "Test",
        "objet": "Marché test", "code_departement": "35", "url_avis": "",
    }])


@pytest.fixture(autouse=True)
def base_temporaire(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_calcul_montant_commission() -> None:
    assert commissions.montant_commission(50_000, 5.0) == 2_500.0
    assert commissions.montant_commission(33_333, 7.5) == 2_499.97  # arrondi au centime


def test_commission_marche_inconnu_rejetee() -> None:
    """La clé étrangère refuse une commission liée à un marché inexistant."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        commissions.enregistrer_commission("X", 10_000, 5.0, "marche-inexistant")


def test_enregistrement_et_listing() -> None:
    _creer_marche("26-1")
    cid = commissions.enregistrer_commission("Alpha Nettoyage", 80_000, 5.0, "26-1")
    liste = commissions.lister_commissions()
    assert len(liste) == 1
    assert liste[0]["id"] == cid
    assert liste[0]["statut"] == "en attente"
    assert liste[0]["montant_commission"] == 4_000.0


def test_montant_ou_taux_invalide_rejete() -> None:
    with pytest.raises(ValueError):
        commissions.enregistrer_commission("X", 0, 5.0)
    with pytest.raises(ValueError):
        commissions.enregistrer_commission("X", 10_000, 0)


def test_cycle_de_vie_et_totaux() -> None:
    c1 = commissions.enregistrer_commission("Alpha", 100_000, 5.0)  # 5 000 €
    commissions.enregistrer_commission("Beta", 40_000, 5.0)  # 2 000 €
    commissions.changer_statut_commission(c1, "payée")

    totaux = commissions.totaux()
    assert totaux["encaissees"] == 5_000.0
    assert totaux["en_attente"] == 2_000.0  # 'facturée' et 'en attente' non encaissées

    with pytest.raises(ValueError):
        commissions.changer_statut_commission(c1, "inconnu")


def test_marche_a_commission() -> None:
    _creer_marche("26-9")
    assert not commissions.marche_a_commission("26-9")
    commissions.enregistrer_commission("Alpha", 10_000, 5.0, "26-9")
    assert commissions.marche_a_commission("26-9")


def test_taux_par_defaut_memorise() -> None:
    assert commissions.taux_par_defaut() == commissions.TAUX_DEFAUT
    commissions.definir_taux_par_defaut(7.5)
    assert commissions.taux_par_defaut() == 7.5
