"""Tests de la prospection automatisée (parsing annuaire + enrichissement)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.database as db
from modules import prospection, prospects


@pytest.fixture(autouse=True)
def base_temporaire(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_parse_entreprise_complet() -> None:
    item = {
        "nom_complet": "PROPRETE BRETONNE",
        "siren": "123456789",
        "activite_principale": "81.21Z",
        "siege": {"libelle_commune": "RENNES", "code_postal": "35000"},
        "dirigeants": [{"prenoms": "MARIE, ANNE", "nom": "DUPONT"}],
    }
    prospect = prospection.parse_entreprise(item, "nettoyage")
    assert prospect is not None
    assert prospect["entreprise"] == "Proprete Bretonne"
    assert prospect["ville"] == "Rennes"
    assert prospect["prenom_contact"] == "Marie"  # premier prénom seulement
    assert "123456789" in prospect["notes"]
    assert prospect["source"] == "annuaire entreprises (auto)"


def test_parse_entreprise_sans_nom() -> None:
    assert prospection.parse_entreprise({"siren": "1"}, "nettoyage") is None


def test_parse_entreprise_champs_manquants() -> None:
    prospect = prospection.parse_entreprise({"nom_complet": "Solo SARL"}, "peinture")
    assert prospect is not None
    assert prospect["ville"] == ""
    assert prospect["prenom_contact"] == ""


def test_secteurs_naf_couvrent_les_cibles() -> None:
    """Chaque secteur cible du cahier des charges a ses codes NAF."""
    for secteur in ("nettoyage", "espaces verts", "peinture", "second oeuvre", "sécurité"):
        assert prospection.SECTEURS_NAF[secteur]


def test_import_auto_deduplique(monkeypatch) -> None:
    """Deux recherches successives n'ajoutent pas deux fois les mêmes prospects."""
    candidats = [
        {"entreprise": "Alpha", "ville": "Rennes", "prenom_contact": "",
         "secteur": "nettoyage", "source": "annuaire entreprises (auto)", "notes": ""},
        {"entreprise": "Beta", "ville": "Vannes", "prenom_contact": "",
         "secteur": "nettoyage", "source": "annuaire entreprises (auto)", "notes": ""},
    ]
    monkeypatch.setattr(
        prospection, "rechercher_entreprises", lambda *a, **k: list(candidats)
    )
    assert prospection.importer_prospects_auto("nettoyage", "35") == 2
    assert prospection.importer_prospects_auto("nettoyage", "35") == 0  # doublons évités
    assert len(prospects.lister_prospects()) == 2


def test_secteur_inconnu_rejete() -> None:
    with pytest.raises(ValueError):
        prospection.rechercher_entreprises("plomberie spatiale", "35")


def test_extraire_json() -> None:
    texte = (
        "J'ai trouvé les informations.\n"
        '{"email": "contact@alpha.fr", "telephone": "02 99 00 00 00", '
        '"site_web": "https://alpha.fr", "prenom_contact": ""}'
    )
    objet = prospection.extraire_json(texte)
    assert objet["email"] == "contact@alpha.fr"
    assert objet["prenom_contact"] == ""


def test_extraire_json_sans_json() -> None:
    assert prospection.extraire_json("Aucun résultat trouvé.") == {}


def test_enrichir_ne_pas_ecraser_saisie_manuelle(monkeypatch) -> None:
    """L'enrichissement ne remplace jamais un email déjà saisi à la main."""
    from types import SimpleNamespace

    pid = prospects.ajouter_prospect("Alpha", ville="Rennes", email="manuel@alpha.fr")
    prospect = prospects.lister_prospects()[0]

    class FauxClient:
        def __init__(self) -> None:
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            bloc = SimpleNamespace(
                type="text",
                text='{"email": "ia@alpha.fr", "telephone": "0299000000", '
                '"site_web": "", "prenom_contact": "Paul"}',
            )
            return SimpleNamespace(content=[bloc])

    monkeypatch.setattr(prospection, "_client_anthropic", lambda: FauxClient())
    trouve = prospection.enrichir_prospect(prospect)

    assert "email" not in trouve  # email manuel préservé
    assert trouve["telephone"] == "0299000000"
    maj = prospects.lister_prospects()[0]
    assert maj["email"] == "manuel@alpha.fr"
    assert maj["telephone"] == "0299000000"
    assert maj["prenom_contact"] == "Paul"
