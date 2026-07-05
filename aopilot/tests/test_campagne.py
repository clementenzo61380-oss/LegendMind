"""Tests du rapprochement marché ↔ prospects et de la génération de campagne."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.database as db
from modules import campagne, prospects, scraper

MARCHE = {
    "idweb": "C-1",
    "dateparution": "2026-07-01",
    "datelimitereponse": "2026-08-01",
    "nomacheteur": "Ville de Rennes",
    "objet": "Nettoyage des locaux scolaires",
    "code_departement": "35",
    "url_avis": "",
}


@pytest.fixture(autouse=True)
def base_temporaire(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    scraper.enregistrer_marches([MARCHE])


def test_detecter_secteur() -> None:
    assert campagne.detecter_secteur("Nettoyage des locaux") == "nettoyage"
    assert campagne.detecter_secteur("Entretien des ESPACES VERTS communaux") == "espaces verts"
    assert campagne.detecter_secteur("Travaux de peinture du gymnase") == "peinture"
    assert campagne.detecter_secteur("Gardiennage du site") == "sécurité"
    assert campagne.detecter_secteur("Fourniture de sel de déneigement") is None


def test_prospects_pour_marche_filtre_secteur_et_statut() -> None:
    prospects.ajouter_prospect("Alpha Propreté", secteur="nettoyage")
    prospects.ajouter_prospect("Vert Jardin", secteur="espaces verts")  # autre secteur
    pid = prospects.ajouter_prospect("Perdu SARL", secteur="nettoyage")
    prospects.changer_statut_prospect(pid, "perdu")  # plus démarchable

    cibles = campagne.prospects_pour_marche(MARCHE)
    assert [c["entreprise"] for c in cibles] == ["Alpha Propreté"]


def test_generer_campagne_template_et_deduplication() -> None:
    prospects.ajouter_prospect(
        "Alpha Propreté", secteur="nettoyage", prenom_contact="Julie", email="a@b.fr"
    )
    cibles = campagne.prospects_pour_marche(MARCHE)

    nb = campagne.generer_campagne(MARCHE, cibles, mode="template")
    assert nb == 1
    generes = campagne.lister_emails_campagne("C-1")
    assert len(generes) == 1
    assert "Nettoyage des locaux scolaires" in generes[0]["sujet"]
    assert "Julie" in generes[0]["corps"]
    assert generes[0]["email_prospect"] == "a@b.fr"

    # Regénérer ne crée pas de doublon pour le même prospect
    assert campagne.generer_campagne(MARCHE, cibles, mode="template") == 0
    assert len(campagne.lister_emails_campagne("C-1")) == 1


def test_generer_campagne_ia(monkeypatch) -> None:
    """Le mode IA appelle l'API une fois par prospect et stocke sujet + corps."""
    prospects.ajouter_prospect("Alpha", secteur="nettoyage")
    prospects.ajouter_prospect("Beta", secteur="nettoyage")
    cibles = campagne.prospects_pour_marche(MARCHE)

    appels: list[dict] = []

    class FauxClient:
        def __init__(self) -> None:
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            appels.append(kwargs)
            bloc = SimpleNamespace(
                type="text", text="Sujet: Offre ciblée\n\nBonjour, corps rédigé par IA."
            )
            return SimpleNamespace(content=[bloc])

    monkeypatch.setattr(campagne, "_client_anthropic", lambda: FauxClient())
    progression: list[str] = []
    nb = campagne.generer_campagne(
        MARCHE, cibles, mode="ia",
        progression=lambda i, t, nom: progression.append(nom),
    )

    assert nb == 2
    assert len(appels) == 2  # un appel API par prospect
    assert progression == ["Alpha", "Beta"]
    # Le prompt contient bien le marché et le destinataire
    assert "Nettoyage des locaux scolaires" in appels[0]["messages"][0]["content"]
    assert "Alpha" in appels[0]["messages"][0]["content"]
    generes = campagne.lister_emails_campagne("C-1")
    assert all(e["sujet"] == "Offre ciblée" for e in generes)
    assert all(e["mode"] == "ia" for e in generes)


def test_marquer_envoye_et_suppression() -> None:
    prospects.ajouter_prospect("Alpha", secteur="nettoyage")
    cibles = campagne.prospects_pour_marche(MARCHE)
    campagne.generer_campagne(MARCHE, cibles, mode="template")
    email = campagne.lister_emails_campagne("C-1")[0]

    campagne.marquer_email_envoye(email["id"])
    assert campagne.lister_emails_campagne("C-1")[0]["statut"] == "envoyé"

    campagne.supprimer_email_campagne(email["id"])
    assert campagne.lister_emails_campagne("C-1") == []
