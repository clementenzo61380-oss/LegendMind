"""Tests des chemins IA (DCE et mémoire) avec un client Anthropic simulé.

Aucun appel réseau : on vérifie la logique d'orchestration (découpage des
gros DCE, un appel par section, règle anti-invention dans les prompts).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import modules.database as db
import modules.dce as dce
import modules.memoire as memoire


class FauxClient:
    """Simule anthropic.Anthropic : enregistre les appels, répond un texte fixe."""

    def __init__(self, reponse: str = "Réponse simulée.") -> None:
        self.appels: list[dict[str, Any]] = []
        self._reponse = reponse
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.appels.append(kwargs)
        bloc = SimpleNamespace(type="text", text=self._reponse)
        return SimpleNamespace(content=[bloc])


@pytest.fixture(autouse=True)
def base_temporaire(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()


def test_dce_petit_un_seul_appel(monkeypatch) -> None:
    """Un DCE sous le seuil part en un seul appel contenant tous les documents."""
    faux = FauxClient("Analyse complète.")
    monkeypatch.setattr(dce, "_client_anthropic", lambda: faux)

    resultat = dce.analyser_dce({"cctp.pdf": "texte cctp", "rc.pdf": "texte rc"})

    assert resultat == "Analyse complète."
    assert len(faux.appels) == 1
    contenu = faux.appels[0]["messages"][0]["content"]
    assert "cctp.pdf" in contenu and "rc.pdf" in contenu
    assert faux.appels[0]["model"] == dce.MODELE_DCE
    assert "expert en marchés publics" in faux.appels[0]["system"]


def test_dce_volumineux_decoupe_puis_synthese(monkeypatch) -> None:
    """Au-delà du seuil : un appel par document + un appel de synthèse."""
    faux = FauxClient("Analyse partielle.")
    monkeypatch.setattr(dce, "_client_anthropic", lambda: faux)
    monkeypatch.setattr(dce, "SEUIL_DECOUPAGE_CARS", 100)  # seuil abaissé pour le test

    textes = {"cctp.pdf": "x" * 80, "ccap.pdf": "y" * 80}  # total 160 > 100
    dce.analyser_dce(textes)

    assert len(faux.appels) == 3  # 2 documents + 1 synthèse
    # La synthèse reçoit les analyses partielles, pas les documents bruts
    assert "Analyse partielle." in faux.appels[-1]["messages"][0]["content"]
    assert "Fusionne-les" in faux.appels[-1]["system"]


def test_memoire_un_appel_par_section_et_regle_anti_invention(monkeypatch) -> None:
    """La génération fait un appel par section et injecte la règle anti-invention."""
    faux = FauxClient("Contenu de section.")
    monkeypatch.setattr(memoire, "_client_anthropic", lambda: faux)

    fiche = {"raison_sociale": "Test SARL", "effectif": "12"}
    progression: list[str] = []
    contenu = memoire.generer_memoire(
        fiche, "contexte DCE", "Nettoyage des écoles",
        rappel_progression=lambda i, total, titre: progression.append(titre),
    )

    sections = memoire.charger_sections_template()
    assert len(faux.appels) == len(sections)  # un appel API par section
    assert progression == [t for t, _ in sections]  # barre de progression alimentée
    # Le mémoire assemblé contient le titre principal et chaque titre de section
    assert contenu.startswith("# Mémoire technique — Nettoyage des écoles")
    for titre, _ in sections:
        assert f"## {titre}" in contenu
    # Chaque prompt contient la règle absolue et la fiche entreprise
    for appel in faux.appels:
        assert "RÈGLE ABSOLUE" in appel["system"]
        assert "Test SARL" in appel["messages"][0]["content"]


def test_critique_recoit_le_memoire_et_les_criteres(monkeypatch) -> None:
    faux = FauxClient("Note : 14/20.")
    monkeypatch.setattr(memoire, "_client_anthropic", lambda: faux)

    resultat = memoire.critiquer_memoire("# Mémoire\ncontenu", "Valeur technique 60 %")

    assert resultat == "Note : 14/20."
    contenu = faux.appels[0]["messages"][0]["content"]
    assert "Valeur technique 60 %" in contenu
    assert "# Mémoire" in contenu


def test_client_sans_cle_message_clair(monkeypatch) -> None:
    """Sans ANTHROPIC_API_KEY, l'erreur explique quoi faire (pas de stacktrace brute)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        dce._client_anthropic()
