"""Tests des fonctions de préparation de données des graphiques (pures)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.database import ETAPES_PIPELINE, STATUTS_PROSPECT
from modules.graphiques import (
    preparer_ca_mensuel,
    preparer_echeances,
    preparer_entonnoir,
    preparer_prospects_par_statut,
)


def test_entonnoir_ordonne_et_complet() -> None:
    donnees = preparer_entonnoir({"détecté": 10, "client": 2})
    assert len(donnees) == len(ETAPES_PIPELINE)
    assert donnees[0] == {"etape": "1. détecté", "nombre": 10}
    # Les étapes sans données apparaissent à zéro (entonnoir complet)
    assert {"etape": "6. payé", "nombre": 0} in donnees


def test_ca_mensuel_agrege_par_mois_et_statut() -> None:
    factures = [
        {"date_facture": "2026-06-01", "montant": 1000, "statut": "payé"},
        {"date_facture": "2026-06-15", "montant": 500, "statut": "payé"},
        {"date_facture": "2026-06-20", "montant": 800, "statut": "dû"},
        {"date_facture": "2026-07-02", "montant": 300, "statut": "dû"},
        {"date_facture": "", "montant": 999, "statut": "dû"},  # sans date : ignorée
    ]
    donnees = preparer_ca_mensuel(factures)
    assert {"mois": "2026-06", "statut": "payé", "montant": 1500.0} in donnees
    assert {"mois": "2026-06", "statut": "dû", "montant": 800.0} in donnees
    assert {"mois": "2026-07", "statut": "dû", "montant": 300.0} in donnees
    assert len(donnees) == 3  # la facture sans date n'apparaît pas


def test_prospects_par_statut_ordre_du_cycle() -> None:
    liste = [{"statut": "contacté"}, {"statut": "contacté"}, {"statut": "client"}]
    donnees = preparer_prospects_par_statut(liste)
    assert len(donnees) == len(STATUTS_PROSPECT)
    assert donnees[1] == {"statut": "2. contacté", "nombre": 2}
    assert donnees[4] == {"statut": "5. client", "nombre": 1}


def test_echeances_triees_et_filtrees() -> None:
    dans_3j = (date.today() + timedelta(days=3)).isoformat()
    dans_20j = (date.today() + timedelta(days=20)).isoformat()
    hier = (date.today() - timedelta(days=1)).isoformat()
    marches = [
        {"objet": "Loin", "datelimitereponse": dans_20j},
        {"objet": "Proche", "datelimitereponse": dans_3j},
        {"objet": "Dépassé", "datelimitereponse": hier},
        {"objet": "Sans date", "datelimitereponse": ""},
    ]
    echeances = preparer_echeances(marches)
    # Dépassées et sans date exclues ; tri par urgence croissante
    assert [e["objet"] for e in echeances] == ["Proche", "Loin"]
    assert echeances[0]["jours"] == 3


def test_echeances_limite() -> None:
    demain = (date.today() + timedelta(days=1)).isoformat()
    marches = [{"objet": f"M{i}", "datelimitereponse": demain} for i in range(10)]
    assert len(preparer_echeances(marches, limite=5)) == 5
