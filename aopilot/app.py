"""AO-PILOT — outil tout-en-un pour la rédaction de mémoires techniques
d'appels d'offres (marchés publics français).

Lancement : streamlit run app.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from modules import dce, emails, graphiques, memoire, prospects, scraper
from modules.database import (
    STATUTS_MARCHE,
    STATUTS_PROSPECT,
    ecrire_reglage,
    get_connection,
    init_db,
    lire_reglage,
)

# Charge .env (ANTHROPIC_API_KEY) depuis la racine du projet
load_dotenv(Path(__file__).resolve().parent / ".env")

st.set_page_config(page_title="AO-PILOT", page_icon="🎯", layout="wide")
init_db()


# ---------------------------------------------------------------------------
# Helpers d'affichage
# ---------------------------------------------------------------------------


def badge_deadline(datelimite: str) -> str:
    """Badge 'J-X' pour une deadline, en rouge si moins de 10 jours."""
    jours = scraper.jours_restants(datelimite)
    if jours is None:
        return "—"
    if jours < 0:
        return f"⚫ dépassé ({-jours} j)"
    if jours < 10:
        return f"🔴 J-{jours}"
    return f"🟢 J-{jours}"


def bandeau_relances() -> None:
    """Affiche en haut de page les relances dues (J+3 après contact)."""
    dues = prospects.relances_dues()
    if dues:
        noms = ", ".join(p["entreprise"] for p in dues[:5])
        suite = f" (+{len(dues) - 5} autres)" if len(dues) > 5 else ""
        st.warning(f"⏰ **{len(dues)} relance(s) due(s)** : {noms}{suite}")


# ---------------------------------------------------------------------------
# Page 1 — Dashboard
# ---------------------------------------------------------------------------


def page_dashboard() -> None:
    st.title("🎯 AO-PILOT — Tableau de bord")
    bandeau_relances()

    conn = get_connection()
    try:
        marches_semaine = conn.execute(
            "SELECT COUNT(*) FROM marches WHERE date_ajout >= datetime('now', '-7 days')"
        ).fetchone()[0]
        memoires_en_cours = conn.execute(
            "SELECT COUNT(*) FROM memoires WHERE statut = 'en cours'"
        ).fetchone()[0]
        ca_facture = conn.execute("SELECT COALESCE(SUM(montant), 0) FROM factures").fetchone()[0]
        ca_paye = conn.execute(
            "SELECT COALESCE(SUM(montant), 0) FROM factures WHERE statut = 'payé'"
        ).fetchone()[0]
    finally:
        conn.close()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Marchés détectés (7 j)", marches_semaine)
    col2.metric("Relances dues aujourd'hui", len(prospects.relances_dues()))
    col3.metric("Mémoires en cours", memoires_en_cours)
    col4.metric("CA facturé", f"{ca_facture:,.0f} €".replace(",", " "),
                delta=f"{ca_paye:,.0f} € encaissés".replace(",", " "))

    # --- Pipeline visuel (entonnoir) ---
    st.subheader("Pipeline")
    compte = _comptes_pipeline()
    g1, g2 = st.columns([3, 2])
    with g1:
        st.altair_chart(
            graphiques.graphique_entonnoir(graphiques.preparer_entonnoir(compte)),
            width="stretch",
        )
    with g2:
        echeances = graphiques.preparer_echeances(scraper.lister_marches())
        st.caption("⏳ Prochaines échéances")
        if echeances:
            for e in echeances:
                badge = f"🔴 J-{e['jours']}" if e["jours"] < 10 else f"🟢 J-{e['jours']}"
                st.markdown(f"**{badge}** — {e['objet'][:55]}")
                st.caption(f"{e['acheteur']} · limite {e['deadline']}")
        else:
            st.caption("Aucune deadline à venir.")

    # --- Statistiques ---
    conn = get_connection()
    try:
        par_departement = dict(
            conn.execute(
                """
                SELECT COALESCE(NULLIF(code_departement, ''), '?') AS dep, COUNT(*)
                FROM marches GROUP BY dep ORDER BY 2 DESC LIMIT 12
                """
            ).fetchall()
        )
        par_semaine = dict(
            conn.execute(
                """
                SELECT strftime('%Y-S%W', date_ajout) AS semaine, COUNT(*)
                FROM marches GROUP BY semaine ORDER BY semaine
                """
            ).fetchall()
        )
        toutes_factures = [
            dict(l) for l in conn.execute("SELECT * FROM factures")
        ]
    finally:
        conn.close()

    g1, g2 = st.columns(2)
    with g1:
        donnees_ca = graphiques.preparer_ca_mensuel(toutes_factures)
        st.caption("💶 CA facturé par mois (payé / dû)")
        if donnees_ca:
            st.altair_chart(
                graphiques.graphique_ca_mensuel(donnees_ca), width="stretch"
            )
        else:
            st.caption("Aucune facture datée.")
    with g2:
        donnees_prospects = graphiques.preparer_prospects_par_statut(
            prospects.lister_prospects()
        )
        st.caption("👥 Prospects par étape du cycle")
        st.altair_chart(
            graphiques.graphique_prospects(donnees_prospects), width="stretch"
        )

    if par_departement:
        g3, g4 = st.columns(2)
        with g3:
            st.caption("🗺️ Marchés par département")
            st.bar_chart(par_departement)
        with g4:
            st.caption("📅 Détections par semaine")
            st.bar_chart(par_semaine)

    # --- Factures (saisie manuelle) ---
    st.subheader("Factures")
    with st.form("form_facture", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
        client = c1.text_input("Client")
        montant = c2.number_input("Montant (€)", min_value=0.0, step=100.0)
        date_fact = c3.date_input("Date", value=date.today())
        statut = c4.selectbox("Statut", ["dû", "payé"])
        if st.form_submit_button("Ajouter la facture") and client and montant > 0:
            conn = get_connection()
            try:
                conn.execute(
                    "INSERT INTO factures (client, montant, date_facture, statut) VALUES (?, ?, ?, ?)",
                    (client, montant, date_fact.isoformat(), statut),
                )
                conn.commit()
            finally:
                conn.close()
            st.rerun()

    conn = get_connection()
    try:
        factures = [dict(l) for l in conn.execute("SELECT * FROM factures ORDER BY date_facture DESC")]
    finally:
        conn.close()
    if factures:
        for f in factures:
            c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 1])
            c1.write(f["client"])
            c2.write(f"{f['montant']:,.0f} €".replace(",", " "))
            c3.write(f["date_facture"] or "—")
            nouveau = c4.selectbox(
                "Statut", ["dû", "payé"],
                index=["dû", "payé"].index(f["statut"]),
                key=f"fact_statut_{f['id']}", label_visibility="collapsed",
            )
            if nouveau != f["statut"]:
                conn = get_connection()
                try:
                    conn.execute("UPDATE factures SET statut=? WHERE id=?", (nouveau, f["id"]))
                    conn.commit()
                finally:
                    conn.close()
                st.rerun()
            if c5.button("🗑️", key=f"fact_del_{f['id']}"):
                conn = get_connection()
                try:
                    conn.execute("DELETE FROM factures WHERE id=?", (f["id"],))
                    conn.commit()
                finally:
                    conn.close()
                st.rerun()
    else:
        st.caption("Aucune facture saisie.")


def _comptes_pipeline() -> dict[str, int]:
    """Compte les éléments à chaque étape du pipeline commercial."""
    conn = get_connection()
    try:
        detecte = conn.execute("SELECT COUNT(*) FROM marches").fetchone()[0]
        prospecte = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE statut IN ('contacté', 'relancé')"
        ).fetchone()[0]
        repondu = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE statut = 'répondu'"
        ).fetchone()[0]
        client = conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE statut = 'client'"
        ).fetchone()[0]
        livre = conn.execute(
            "SELECT COUNT(*) FROM memoires WHERE statut = 'livré'"
        ).fetchone()[0]
        paye = conn.execute(
            "SELECT COUNT(*) FROM factures WHERE statut = 'payé'"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "détecté": detecte,
        "prospecté": prospecte,
        "répondu": repondu,
        "client": client,
        "livré": livre,
        "payé": paye,
    }


# ---------------------------------------------------------------------------
# Page 2 — Radar BOAMP
# ---------------------------------------------------------------------------


def page_radar() -> None:
    st.title("📡 Radar BOAMP")
    bandeau_relances()

    # Filtres persistants : les dernières valeurs utilisées sont rechargées
    with st.expander("Filtres de scan", expanded=True):
        mots = st.text_input(
            "Mots-clés (séparés par des virgules)",
            value=lire_reglage("scan_mots_cles", ", ".join(scraper.MOTS_CLES_DEFAUT)),
        )
        deps = st.text_input(
            "Départements (séparés par des virgules)",
            value=lire_reglage("scan_departements", ", ".join(scraper.DEPARTEMENTS_DEFAUT)),
        )
        jours = st.slider(
            "Fenêtre de publication (jours)", 1, 60,
            int(lire_reglage("scan_jours", str(scraper.FENETRE_JOURS_DEFAUT))),
        )

    if st.button("🔍 Scanner maintenant", type="primary"):
        # Mémorise les filtres pour les prochaines sessions
        ecrire_reglage("scan_mots_cles", mots)
        ecrire_reglage("scan_departements", deps)
        ecrire_reglage("scan_jours", str(jours))
        with st.spinner("Interrogation de l'API BOAMP..."):
            try:
                avis = scraper.scanner_boamp(
                    [m.strip() for m in mots.split(",") if m.strip()],
                    [d.strip() for d in deps.split(",") if d.strip()],
                    jours,
                )
                nouveaux = scraper.enregistrer_marches(avis)
                st.success(f"{len(avis)} avis trouvés, {nouveaux} nouveaux enregistrés.")
            except scraper.ErreurBoamp as exc:
                st.error(str(exc))

    st.subheader("Marchés détectés (tri par deadline croissante)")
    col_filtre, col_action = st.columns([3, 1])
    filtre = col_filtre.selectbox("Filtrer par statut", ["(tous)"] + STATUTS_MARCHE)
    if col_action.button("👁️ Tout marquer vu"):
        nb = scraper.marquer_tous_vus()
        st.toast(f"{nb} marché(s) passé(s) en « vu ».")
        st.rerun()
    recherche = st.text_input("🔎 Rechercher (objet ou acheteur)", "")
    marches = scraper.lister_marches(None if filtre == "(tous)" else filtre)
    if recherche:
        terme = recherche.lower()
        marches = [
            m for m in marches
            if terme in (m["objet"] or "").lower()
            or terme in (m["nomacheteur"] or "").lower()
        ]
    if not marches:
        st.info("Aucun marché ne correspond." if recherche else "Aucun marché en base. Lancez un scan.")
        return

    for m in marches:
        with st.container(border=True):
            c1, c2 = st.columns([5, 2])
            c1.markdown(f"**{m['objet'] or '(objet non précisé)'}**")
            c1.caption(
                f"{m['nomacheteur']} — dépt {m['code_departement']} — "
                f"paru le {m['dateparution'] or '?'}"
            )
            if m["url_avis"]:
                c1.markdown(f"[Voir l'avis]({m['url_avis']})")
            c2.markdown(f"### {badge_deadline(m['datelimitereponse'])}")
            c2.caption(f"Limite : {m['datelimitereponse'] or '?'}")
            statut = c2.selectbox(
                "Statut", STATUTS_MARCHE,
                index=STATUTS_MARCHE.index(m["statut"]) if m["statut"] in STATUTS_MARCHE else 0,
                key=f"marche_statut_{m['idweb']}", label_visibility="collapsed",
            )
            if statut != m["statut"]:
                scraper.changer_statut_marche(m["idweb"], statut)
                st.rerun()
            if c2.button("🗑️ Supprimer", key=f"marche_del_{m['idweb']}"):
                scraper.supprimer_marche(m["idweb"])
                st.rerun()


# ---------------------------------------------------------------------------
# Page 3 — Prospects
# ---------------------------------------------------------------------------


def page_prospects() -> None:
    st.title("👥 Prospects")
    bandeau_relances()

    marches = scraper.lister_marches()
    choix_marches = {"(aucun)": None} | {
        f"{m['objet'][:60]} ({m['idweb']})": m["idweb"] for m in marches
    }

    onglet_saisie, onglet_import, onglet_vue = st.tabs(
        ["➕ Saisie rapide", "📄 Import CSV", "📋 Tableau / Kanban"]
    )

    with onglet_saisie:
        with st.form("form_prospect", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            entreprise = c1.text_input("Entreprise *")
            ville = c2.text_input("Ville")
            secteur = c3.selectbox(
                "Secteur", ["", "nettoyage", "BTP second œuvre", "espaces verts", "sécurité", "autre"]
            )
            c4, c5, c6 = st.columns(3)
            email = c4.text_input("Email")
            telephone = c5.text_input("Téléphone")
            prenom = c6.text_input("Prénom du contact")
            c7, c8 = st.columns(2)
            source = c7.text_input("Source", value="manuel")
            marche_lie = c8.selectbox("Marché lié", list(choix_marches))
            notes = st.text_area("Notes", height=80)
            if st.form_submit_button("Ajouter le prospect", type="primary"):
                if entreprise:
                    prospects.ajouter_prospect(
                        entreprise=entreprise, ville=ville, email=email,
                        telephone=telephone, prenom_contact=prenom, secteur=secteur,
                        source=source, marche_idweb=choix_marches[marche_lie], notes=notes,
                    )
                    st.success(f"Prospect « {entreprise} » ajouté.")
                else:
                    st.error("Le nom d'entreprise est obligatoire.")

    with onglet_import:
        st.caption(
            "Colonnes attendues : entreprise (obligatoire), ville, email, "
            "telephone, prenom_contact, secteur, source"
        )
        fichier = st.file_uploader("Fichier CSV", type="csv")
        marche_import = st.selectbox("Lier au marché", list(choix_marches), key="import_marche")
        if fichier and st.button("Importer"):
            nb = prospects.importer_csv(fichier.read(), choix_marches[marche_import])
            st.success(f"{nb} prospect(s) importé(s).")

    with onglet_vue:
        mode = st.radio("Affichage", ["Tableau", "Kanban"], horizontal=True)
        filtre = st.selectbox("Filtrer par statut", ["(tous)"] + STATUTS_PROSPECT)
        st.download_button(
            "⬇️ Exporter tous les prospects (CSV)",
            prospects.exporter_csv(),
            file_name=f"prospects_{date.today().isoformat()}.csv",
            mime="text/csv",
        )
        liste = prospects.lister_prospects(None if filtre == "(tous)" else filtre)
        if not liste:
            st.info("Aucun prospect.")
        elif mode == "Tableau":
            _tableau_prospects(liste)
        else:
            _kanban_prospects(liste)


def _ligne_prospect(p: dict, prefixe: str) -> None:
    """Affiche une carte prospect avec changement de statut et suppression."""
    with st.container(border=True):
        st.markdown(f"**{p['entreprise']}** — {p['ville'] or '—'}")
        details = " · ".join(
            x for x in [p["email"], p["telephone"], p["secteur"], p["source"]] if x
        )
        if details:
            st.caption(details)
        if p["date_contact"]:
            st.caption(f"Contacté le {p['date_contact']}")
        c1, c2 = st.columns([3, 1])
        statut = c1.selectbox(
            "Statut", STATUTS_PROSPECT,
            index=STATUTS_PROSPECT.index(p["statut"]) if p["statut"] in STATUTS_PROSPECT else 0,
            key=f"{prefixe}_statut_{p['id']}", label_visibility="collapsed",
        )
        if statut != p["statut"]:
            prospects.changer_statut_prospect(p["id"], statut)
            st.rerun()
        if c2.button("🗑️", key=f"{prefixe}_del_{p['id']}"):
            prospects.supprimer_prospect(p["id"])
            st.rerun()


def _tableau_prospects(liste: list[dict]) -> None:
    for p in liste:
        _ligne_prospect(p, "tab")


def _kanban_prospects(liste: list[dict]) -> None:
    colonnes = st.columns(len(STATUTS_PROSPECT))
    for colonne, statut in zip(colonnes, STATUTS_PROSPECT):
        with colonne:
            st.markdown(f"**{statut.capitalize()}**")
            for p in [x for x in liste if x["statut"] == statut]:
                _ligne_prospect(p, "kb")


# ---------------------------------------------------------------------------
# Page 4 — Emails
# ---------------------------------------------------------------------------


def page_emails() -> None:
    st.title("✉️ Générateur d'emails")
    bandeau_relances()

    onglet_generer, onglet_editer = st.tabs(["Générer", "Éditer les templates"])

    with onglet_editer:
        choix = st.selectbox("Template", list(emails.TEMPLATES_EMAILS.values()))
        fichier = next(f for f, lib in emails.TEMPLATES_EMAILS.items() if lib == choix)
        contenu = st.text_area("Contenu", emails.charger_template(fichier), height=400)
        st.caption("Variables : " + ", ".join("{" + v + "}" for v in emails.VARIABLES_DISPONIBLES))
        if st.button("💾 Sauvegarder le template"):
            emails.sauvegarder_template(fichier, contenu)
            st.success("Template sauvegardé.")

    with onglet_generer:
        choix = st.selectbox("Type d'email", list(emails.TEMPLATES_EMAILS.values()), key="gen_type")
        fichier = next(f for f, lib in emails.TEMPLATES_EMAILS.items() if lib == choix)

        marches = scraper.lister_marches()
        choix_marches = {"(aucun)": None} | {
            f"{m['objet'][:60]} ({m['idweb']})": m for m in marches
        }
        selection_marche = st.selectbox("Marché", list(choix_marches))
        marche = choix_marches[selection_marche]

        liste_prospects = prospects.lister_prospects()
        choix_prospects = {"(aucun)": None} | {
            f"{p['entreprise']} ({p['email'] or 'sans email'})": p for p in liste_prospects
        }
        selection_prospect = st.selectbox("Prospect", list(choix_prospects))
        prospect = choix_prospects[selection_prospect]

        jours = scraper.jours_restants(marche["datelimitereponse"]) if marche else None
        variables = emails.variables_depuis_marche(marche, prospect, jours)
        texte = emails.fusionner(emails.charger_template(fichier), variables)
        sujet, corps = emails.extraire_sujet_corps(texte)

        st.text_input("Sujet", sujet, key="email_sujet")
        st.text_area("Corps de l'email (copiez-le)", corps, height=350, key="email_corps")
        st.caption("💡 Les marqueurs [?variable?] signalent une donnée manquante.")

        destinataire = (prospect or {}).get("email", "") or ""
        lien = emails.generer_mailto(destinataire, sujet, corps)
        c1, c2 = st.columns([2, 2])
        c1.markdown(f"[📨 Ouvrir dans votre client mail (mailto)]({lien})")
        # Action rapide : passe le prospect en 'contacté' (déclenche le suivi J+3)
        if prospect and prospect["statut"] in ("à contacter", "contacté"):
            libelle = (
                "✅ Marquer contacté aujourd'hui"
                if prospect["statut"] == "à contacter"
                else "🔁 Marquer relancé aujourd'hui"
            )
            nouveau = "contacté" if prospect["statut"] == "à contacter" else "relancé"
            if c2.button(libelle):
                prospects.changer_statut_prospect(prospect["id"], nouveau)
                st.toast(f"{prospect['entreprise']} → {nouveau}")
                st.rerun()
        st.code(corps, language=None)  # bloc code Streamlit = bouton copier intégré


# ---------------------------------------------------------------------------
# Page 5 — Analyse DCE
# ---------------------------------------------------------------------------


def page_dce() -> None:
    st.title("📑 Analyseur de DCE")
    bandeau_relances()

    marches = scraper.lister_marches()
    choix_marches = {"(aucun)": None} | {
        f"{m['objet'][:60]} ({m['idweb']})": m["idweb"] for m in marches
    }
    marche_lie = st.selectbox("Marché lié", list(choix_marches))

    fichiers = st.file_uploader(
        "PDF du DCE (CCTP, RC, CCAP, avis...)", type="pdf", accept_multiple_files=True
    )

    if fichiers:
        with st.spinner("Extraction du texte des PDF..."):
            textes = {f.name: dce.extraire_texte_pdf(f.read(), f.name) for f in fichiers}
        total_cars = sum(len(t) for t in textes.values())
        st.info(
            f"{len(textes)} fichier(s), ~{total_cars:,} caractères "
            f"(~{dce.estimer_tokens(' '.join(textes.values())):,} tokens). "
            f"Coût API estimé : **{dce.estimer_cout_analyse(textes):.2f} $**".replace(",", " ")
        )
        if st.button("🤖 Analyser le DCE", type="primary"):
            try:
                with st.spinner("Analyse par l'IA en cours (peut prendre 1 à 2 minutes)..."):
                    resultat = dce.analyser_dce(textes)
                dce.sauvegarder_analyse(
                    resultat, ", ".join(textes), choix_marches[marche_lie]
                )
                st.success("Analyse terminée et sauvegardée.")
                st.markdown(resultat)
            except RuntimeError as exc:  # clé API absente
                st.error(str(exc))
            except Exception as exc:  # erreur API
                st.error(f"Erreur pendant l'analyse : {exc}")

    st.subheader("Analyses sauvegardées")
    for analyse in dce.lister_analyses():
        libelle = f"{analyse['date_analyse']} — {analyse['nom_fichiers'] or 'sans nom'}"
        with st.expander(libelle):
            st.download_button(
                "⬇️ Télécharger l'analyse (.md)",
                analyse["resultat"],
                file_name=f"analyse_dce_{analyse['id']}.md",
                mime="text/markdown",
                key=f"dl_analyse_{analyse['id']}",
            )
            st.markdown(analyse["resultat"])


# ---------------------------------------------------------------------------
# Page 6 — Mémoire technique
# ---------------------------------------------------------------------------


def page_memoire() -> None:
    st.title("📝 Générateur de mémoire technique")
    bandeau_relances()

    # --- Fiche entreprise ---
    st.subheader("1. Fiche entreprise cliente")
    fiches = memoire.lister_fiches()
    choix_fiches = {"(nouvelle fiche)": None} | {
        f"{f['raison_sociale']} (maj {f['date_maj']})": f for f in fiches
    }
    selection = st.selectbox("Fiche existante", list(choix_fiches))
    fiche_existante = choix_fiches[selection] or {}

    with st.form("form_fiche"):
        valeurs: dict[str, str] = {}
        colonnes = st.columns(2)
        for i, (champ, libelle) in enumerate(memoire.CHAMPS_FICHE):
            zone = colonnes[i % 2]
            if champ in ("refs", "encadrement", "materiel", "produits"):
                valeurs[champ] = zone.text_area(
                    libelle, fiche_existante.get(champ, ""), height=80
                )
            else:
                valeurs[champ] = zone.text_input(libelle, fiche_existante.get(champ, ""))
        if st.form_submit_button("💾 Sauvegarder la fiche"):
            if valeurs["raison_sociale"]:
                fid = memoire.sauvegarder_fiche(valeurs, fiche_existante.get("id"))
                st.success(f"Fiche sauvegardée (id {fid}).")
                st.rerun()
            else:
                st.error("La raison sociale est obligatoire.")

    if not fiche_existante:
        st.info("Sélectionnez ou créez une fiche entreprise pour générer un mémoire.")
        return

    # --- Contexte du marché ---
    st.subheader("2. Contexte du marché")
    marches = scraper.lister_marches()
    choix_marches = {"(aucun)": None} | {
        f"{m['objet'][:60]} ({m['idweb']})": m for m in marches
    }
    selection_marche = st.selectbox("Marché visé", list(choix_marches), key="mem_marche")
    marche = choix_marches[selection_marche]
    titre_marche = st.text_input(
        "Titre du marché", (marche or {}).get("objet", "") or ""
    )

    analyses = dce.lister_analyses((marche or {}).get("idweb"))
    contexte_dce = ""
    if analyses:
        libelles = {f"{a['date_analyse']} — {a['nom_fichiers']}": a for a in analyses}
        choix_analyse = st.selectbox(
            "Analyse DCE à utiliser comme contexte", ["(aucune)"] + list(libelles)
        )
        if choix_analyse != "(aucune)":
            contexte_dce = libelles[choix_analyse]["resultat"]
    else:
        contexte_dce = st.text_area(
            "Contexte DCE (collez ici l'analyse ou les critères du RC)", height=120
        )

    # --- Génération ---
    st.subheader("3. Génération")
    sections = memoire.charger_sections_template()
    cout = memoire.estimer_cout_memoire(fiche_existante, contexte_dce, len(sections))
    st.info(
        f"{len(sections)} sections à générer (un appel API par section + passe "
        f"critique). Coût API estimé : **{cout:.2f} $**"
    )

    if st.button("🚀 Générer le mémoire", type="primary", disabled=not titre_marche):
        barre = st.progress(0.0, text="Démarrage...")

        def progression(i: int, total: int, titre: str) -> None:
            barre.progress(i / (total + 1), text=f"Section {i}/{total} : {titre}")

        try:
            contenu = memoire.generer_memoire(
                fiche_existante, contexte_dce, titre_marche, progression
            )
            barre.progress(0.95, text="Passe critique (relecture par l'IA)...")
            critique = memoire.critiquer_memoire(contenu, contexte_dce)
            barre.progress(1.0, text="Terminé.")
            memoire_id = memoire.sauvegarder_memoire(
                titre_marche, contenu, critique,
                (marche or {}).get("idweb"), fiche_existante.get("id"),
            )
            st.session_state["dernier_memoire_id"] = memoire_id
            st.success("Mémoire généré et sauvegardé.")
        except RuntimeError as exc:  # clé API absente
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Erreur pendant la génération : {exc}")

    # --- Mémoires existants et exports ---
    st.subheader("4. Mémoires générés")
    for m in memoire.lister_memoires():
        with st.expander(f"{m['date_creation']} — {m['titre'] or 'sans titre'} ({m['statut']})"):
            onglet_contenu, onglet_edition, onglet_critique, onglet_export = st.tabs(
                ["Aperçu", "✏️ Éditer", "Critique IA", "Exporter"]
            )
            with onglet_contenu:
                st.markdown(m["contenu_md"] or "")
            with onglet_edition:
                # Édition du markdown avant export : compléter les
                # [DONNÉE CLIENT : ...] et ajuster le texte de l'IA.
                nb_marqueurs = (m["contenu_md"] or "").count("[DONNÉE CLIENT")
                if nb_marqueurs:
                    st.warning(f"{nb_marqueurs} marqueur(s) [DONNÉE CLIENT : ...] à compléter.")
                edite = st.text_area(
                    "Contenu markdown", m["contenu_md"] or "",
                    height=400, key=f"mem_edit_{m['id']}",
                )
                if st.button("💾 Sauvegarder les modifications", key=f"mem_save_{m['id']}"):
                    memoire.mettre_a_jour_memoire(m["id"], edite)
                    st.success("Modifications sauvegardées.")
                    st.rerun()
            with onglet_critique:
                st.markdown(m["critique"] or "(pas de critique)")
            with onglet_export:
                nom = f"memoire_{m['id']}_{date.today().isoformat()}"
                c1, c2, c3, c4 = st.columns(4)
                c1.download_button(
                    "⬇️ Télécharger .md", m["contenu_md"] or "",
                    file_name=f"{nom}.md", mime="text/markdown",
                    key=f"dl_md_{m['id']}",
                )
                if c2.button("📘 Générer le .docx", key=f"docx_{m['id']}"):
                    chemin = memoire.exporter_docx(
                        m["contenu_md"], nom, marche=m["titre"] or ""
                    )
                    st.session_state[f"docx_pret_{m['id']}"] = str(chemin)
                if st.session_state.get(f"docx_pret_{m['id']}"):
                    chemin_docx = Path(st.session_state[f"docx_pret_{m['id']}"])
                    if chemin_docx.exists():
                        c2.download_button(
                            "⬇️ Télécharger .docx", chemin_docx.read_bytes(),
                            file_name=chemin_docx.name,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=f"dl_docx_{m['id']}",
                        )
                nouveau_statut = c3.selectbox(
                    "Statut", ["en cours", "livré"],
                    index=0 if m["statut"] == "en cours" else 1,
                    key=f"mem_statut_{m['id']}",
                )
                if nouveau_statut != m["statut"]:
                    conn = get_connection()
                    try:
                        conn.execute(
                            "UPDATE memoires SET statut=? WHERE id=?",
                            (nouveau_statut, m["id"]),
                        )
                        conn.commit()
                    finally:
                        conn.close()
                    st.rerun()
                if c4.button("🗑️ Supprimer", key=f"mem_del_{m['id']}"):
                    memoire.supprimer_memoire(m["id"])
                    st.rerun()


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

PAGES = {
    "🎯 Dashboard": page_dashboard,
    "📡 Radar BOAMP": page_radar,
    "👥 Prospects": page_prospects,
    "✉️ Emails": page_emails,
    "📑 Analyse DCE": page_dce,
    "📝 Mémoire technique": page_memoire,
}

with st.sidebar:
    st.markdown("# AO-PILOT")
    st.caption("Pilotage d'activité — mémoires techniques d'appels d'offres")
    page = st.radio("Navigation", list(PAGES), label_visibility="collapsed")

PAGES[page]()
