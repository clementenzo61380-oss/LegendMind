"""Tests du parsing BOAMP (fonctions pures de modules/scraper.py)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.scraper import construire_where, jours_restants, parse_record


def test_parse_record_champs_a_plat() -> None:
    """Format API Explore v2.1 : champs à plat."""
    record = {
        "idweb": "26-12345",
        "dateparution": "2026-06-20",
        "datelimitereponse": "2026-07-20",
        "nomacheteur": "Ville de Rennes",
        "objet": "Nettoyage des locaux municipaux",
        "code_departement": ["35"],
        "url_avis": "https://www.boamp.fr/avis/detail/26-12345",
    }
    avis = parse_record(record)
    assert avis is not None
    assert avis["idweb"] == "26-12345"
    assert avis["nomacheteur"] == "Ville de Rennes"
    assert avis["code_departement"] == "35"  # liste aplatie en chaîne
    assert avis["url_avis"].endswith("26-12345")


def test_parse_record_format_imbrique() -> None:
    """Ancien format Opendatasoft : champs sous la clé 'fields'."""
    record = {
        "fields": {
            "idweb": "26-99999",
            "objet": "Entretien des espaces verts",
            "code_departement": "44",
        }
    }
    avis = parse_record(record)
    assert avis is not None
    assert avis["idweb"] == "26-99999"
    assert avis["code_departement"] == "44"
    assert avis["dateparution"] == ""  # champ absent -> chaîne vide


def test_parse_record_sans_idweb() -> None:
    """Un enregistrement sans idweb est inexploitable : None."""
    assert parse_record({"objet": "Sans identifiant"}) is None


def test_parse_record_departements_multiples() -> None:
    """Plusieurs départements sont joints par des virgules."""
    avis = parse_record({"idweb": "26-1", "code_departement": ["35", "22"]})
    assert avis is not None
    assert avis["code_departement"] == "35, 22"


def test_construire_where_contient_filtres() -> None:
    """La clause where contient mot-clé, date min et départements."""
    clause = construire_where("nettoyage", ["35", "22"], 14)
    date_min = (date.today() - timedelta(days=14)).isoformat()
    assert '"nettoyage"' in clause
    assert f"date'{date_min}'" in clause
    assert 'code_departement IN ("35", "22")' in clause


def test_construire_where_sans_departements() -> None:
    """Sans départements, pas de clause IN."""
    clause = construire_where("peinture", [], 7)
    assert "code_departement" not in clause


def test_jours_restants() -> None:
    """Calcul du badge J-X."""
    demain = (date.today() + timedelta(days=1)).isoformat()
    assert jours_restants(demain) == 1
    assert jours_restants("") is None
    assert jours_restants("pas-une-date") is None
