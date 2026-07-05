"""Graphiques du dashboard (Altair, fourni avec Streamlit).

Les fonctions `preparer_*` sont pures (listes de dicts en entrée/sortie)
et testées unitairement ; les fonctions `graphique_*` construisent les
objets Altair à partir de ces données.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .database import ETAPES_PIPELINE, STATUTS_PROSPECT

# Couleurs sobres, lisibles en thème clair comme sombre
COULEUR_PRINCIPALE = "#4C78A8"
COULEUR_PAYE = "#59A14F"
COULEUR_DU = "#E8985E"


# ---------------------------------------------------------------------------
# Préparation des données (fonctions pures)
# ---------------------------------------------------------------------------


def preparer_entonnoir(compte: dict[str, int]) -> list[dict[str, Any]]:
    """Transforme les comptes du pipeline en lignes ordonnées pour l'entonnoir."""
    return [
        {"etape": f"{i + 1}. {etape}", "nombre": compte.get(etape, 0)}
        for i, etape in enumerate(ETAPES_PIPELINE)
    ]


def preparer_ca_mensuel(factures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrège les factures par mois (AAAA-MM) et par statut (dû / payé)."""
    cumul: dict[tuple[str, str], float] = {}
    for facture in factures:
        brut = facture.get("date_facture") or ""
        try:
            mois = datetime.fromisoformat(brut).strftime("%Y-%m")
        except ValueError:
            continue  # facture sans date exploitable : ignorée du graphique
        statut = facture.get("statut") or "dû"
        cle = (mois, statut)
        cumul[cle] = cumul.get(cle, 0.0) + float(facture.get("montant") or 0)
    return [
        {"mois": mois, "statut": statut, "montant": montant}
        for (mois, statut), montant in sorted(cumul.items())
    ]


def preparer_prospects_par_statut(
    liste: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compte les prospects par statut, dans l'ordre du cycle de vie."""
    compte = {statut: 0 for statut in STATUTS_PROSPECT}
    for prospect in liste:
        statut = prospect.get("statut")
        if statut in compte:
            compte[statut] += 1
    return [
        {"statut": f"{i + 1}. {statut}", "nombre": nombre}
        for i, (statut, nombre) in enumerate(compte.items())
    ]


def preparer_echeances(
    marches: list[dict[str, Any]], limite: int = 5
) -> list[dict[str, Any]]:
    """Prochaines deadlines non dépassées, avec jours restants, triées."""
    echeances: list[dict[str, Any]] = []
    for marche in marches:
        brut = marche.get("datelimitereponse") or ""
        try:
            limite_date = datetime.fromisoformat(brut.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        jours = (limite_date - date.today()).days
        if jours < 0:
            continue  # deadline dépassée : hors du radar
        echeances.append(
            {
                "objet": marche.get("objet") or "(objet non précisé)",
                "acheteur": marche.get("nomacheteur") or "",
                "deadline": limite_date.isoformat(),
                "jours": jours,
            }
        )
    echeances.sort(key=lambda e: e["jours"])
    return echeances[:limite]


# ---------------------------------------------------------------------------
# Construction des graphiques Altair
# ---------------------------------------------------------------------------


def graphique_entonnoir(donnees: list[dict[str, Any]]) -> Any:
    """Entonnoir horizontal du pipeline commercial."""
    import altair as alt

    return (
        alt.Chart(alt.Data(values=donnees))
        .mark_bar(color=COULEUR_PRINCIPALE, cornerRadius=3)
        .encode(
            x=alt.X("nombre:Q", title=None, axis=alt.Axis(format="d", tickMinStep=1)),
            y=alt.Y("etape:N", sort=None, title=None),
            tooltip=["etape:N", "nombre:Q"],
        )
        .properties(height=180)
    )


def graphique_ca_mensuel(donnees: list[dict[str, Any]]) -> Any:
    """Barres empilées du CA facturé par mois, ventilé dû / payé."""
    import altair as alt

    return (
        alt.Chart(alt.Data(values=donnees))
        .mark_bar(cornerRadius=2)
        .encode(
            x=alt.X("mois:N", title=None, sort=None),
            y=alt.Y("montant:Q", title="€"),
            color=alt.Color(
                "statut:N",
                title=None,
                scale=alt.Scale(domain=["payé", "dû"], range=[COULEUR_PAYE, COULEUR_DU]),
            ),
            tooltip=["mois:N", "statut:N", alt.Tooltip("montant:Q", format=",.0f")],
        )
        .properties(height=220)
    )


def graphique_prospects(donnees: list[dict[str, Any]]) -> Any:
    """Répartition des prospects le long du cycle de vie."""
    import altair as alt

    return (
        alt.Chart(alt.Data(values=donnees))
        .mark_bar(color=COULEUR_PRINCIPALE, cornerRadius=3)
        .encode(
            x=alt.X("statut:N", sort=None, title=None, axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("nombre:Q", title=None, axis=alt.Axis(format="d", tickMinStep=1)),
            tooltip=["statut:N", "nombre:Q"],
        )
        .properties(height=220)
    )
