"""Tests de la fusion des templates d'emails (modules/emails.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.emails import (
    TEMPLATES_EMAILS,
    charger_template,
    extraire_sujet_corps,
    fusionner,
    generer_mailto,
    variables_depuis_marche,
)


def test_fusion_variables_presentes() -> None:
    texte = fusionner(
        "Bonjour {prenom_contact}, le marché « {objet} » expire dans {jours_restants} jours.",
        {"prenom_contact": "Marie", "objet": "Nettoyage écoles", "jours_restants": 12},
    )
    assert texte == "Bonjour Marie, le marché « Nettoyage écoles » expire dans 12 jours."


def test_fusion_variable_manquante_marquee() -> None:
    """Une variable absente est signalée par [?nom?], pas silencieusement vidée."""
    texte = fusionner("Bonjour {prenom_contact}", {})
    assert texte == "Bonjour [?prenom_contact?]"


def test_fusion_variable_vide_marquee() -> None:
    """Une variable vide est traitée comme manquante."""
    texte = fusionner("Secteur : {secteur}", {"secteur": ""})
    assert texte == "Secteur : [?secteur?]"


def test_extraire_sujet_corps() -> None:
    sujet, corps = extraire_sujet_corps("Sujet: Mon sujet\n\nCorps du mail")
    assert sujet == "Mon sujet"
    assert corps == "Corps du mail"


def test_extraire_sujet_absent() -> None:
    sujet, corps = extraire_sujet_corps("Pas de ligne sujet")
    assert sujet == ""
    assert corps == "Pas de ligne sujet"


def test_generer_mailto_encode() -> None:
    lien = generer_mailto("contact@exemple.fr", "Sujet & co", "Ligne 1\nLigne 2")
    assert lien.startswith("mailto:contact@exemple.fr?")
    assert "subject=Sujet%20%26%20co" in lien
    assert "Ligne%201%0ALigne%202" in lien


def test_variables_depuis_marche() -> None:
    marche = {
        "objet": "Nettoyage",
        "nomacheteur": "CC Bretagne",
        "datelimitereponse": "2026-08-01",
    }
    prospect = {"prenom_contact": "Paul", "secteur": "nettoyage"}
    variables = variables_depuis_marche(marche, prospect, jours=9)
    assert variables["objet"] == "Nettoyage"
    assert variables["acheteur"] == "CC Bretagne"
    assert variables["jours_restants"] == 9
    assert variables["prenom_contact"] == "Paul"


def test_templates_reels_fusionnent_sans_reste() -> None:
    """Les trois templates livrés fusionnent sans laisser de {variable} brute."""
    variables = {
        "objet": "Nettoyage des écoles",
        "acheteur": "Ville de Vannes",
        "deadline": "2026-08-01",
        "jours_restants": 15,
        "prenom_contact": "Julie",
        "secteur": "nettoyage",
    }
    for fichier in TEMPLATES_EMAILS:
        texte = fusionner(charger_template(fichier), variables)
        assert "{" not in texte, f"variable non fusionnée dans {fichier}"
        assert "[?" not in texte, f"variable manquante dans {fichier}"
