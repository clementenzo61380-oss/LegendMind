# ══════════════════════════════════════════
# LEXIQUE COC — Normalisation des termes
# ══════════════════════════════════════════

TROUPES = {
    "go": "golem", "goglace": "golem_de_glace", "gdg": "golem_de_glace",
    "loon": "ballon", "loons": "ballons", "bal": "ballons",
    "pe": "pekka", "pk": "pekka", "pek": "pekka",
    "drag": "dragon", "baby": "bebe_dragon", "bb drag": "bebe_dragon",
    "electro": "electro_dragon", "ed": "electro_dragon",
    "lava": "molosse", "lava hound": "molosse", "mo": "molosse", "momo": "molosse",
    "hog": "cochon", "hogs": "cochons",
    "min": "mineurs",
    "bo": "boulistes", "bou": "boulistes", "boubou": "boulistes",
    "soso": "sorcier", "wiz": "sorcier", "wi": "sorcier",
    "sosottes": "sorcieres", "wit": "sorcieres",
    "val": "valkyries",
    "gar": "gargouilles", "garg": "gargouilles", "minion": "gargouilles",
    "gob": "gobelins", "sgob": "super_gobelins",
    "arch": "archers", "ba": "barbares", "bar": "barbares",
    "sg": "super_gargouille",
    "yé": "yeti", "yeti": "yeti",
    "hh": "chasseuse_tetes",
    "sap": "sapeur", "wb": "sapeur", "cb": "sapeur",
    "sb": "super_barbare",
}

HEROS = {
    "king": "roi", "k": "roi",
    "queen": "reine", "q": "reine",
    "warden": "grand_gardien", "w": "grand_gardien", "gg": "grand_gardien",
    "rc": "championne_royale", "cr": "championne_royale",
    "aqh": "reine_guevisseuses", "qw": "queen_walk",
}

SORTS = {
    "zap": "foudre", "heal": "soin", "jump": "saut",
    "squel": "sort_squelettique", "freeze": "gel", "clone": "clone",
    "pois": "poison", "seisme": "sismique", "seismes": "sismique",
    "speed": "precipitation", "bats": "chauves_souris",
    "zap quake": "foudre_sismique",
}

COMPOS = {
    "lalo": "molosse_ballons", "mobal": "molosse_ballons",
    "aqh": "reine_guerisseuses",
    "minhog": "mineurs_cochons", "minhogs": "mineurs_cochons",
    "gowipe": "golem_sorcieres_pekka",
    "gowiwi": "golem_sorciers_sorcieres",
    "blizzard": "blimp_super_sorciers_invisibilite",
    "électrone": "electro_dragon_clone",
    "electrone": "electro_dragon_clone",
    "sui lalo": "suicide_molosse_ballons",
    "warden walk": "grand_gardien_guerisseuses",
    "falcon": "reine_guerisseuses_valkyries",
    "donut": "squelette_mobal",
    "skelly": "squelette_mobal",
}

DEFENSES = {
    "tb": "tour_bombes", "tab": "tour_bombes",
    "tda": "tour_archer",
    "tde": "tour_enfer",
    "tds": "tour_sorcier",
    "ea": "eagle_artillery", "aigle": "eagle_artillery",
    "aa": "anti_aerien",
    "ll": "lance_buches", "lb": "lance_buches",
    "cdc": "chateau_clan",
    "cds": "caserne_siege",
    "demo": "demolisseur",
    "diri": "dirigeable",
    "blimp": "dirigeable",
    "ff": "catapulte_esprit",
}

STRUCTURES = {
    "hdv": "hotel_de_ville", "th": "hotel_de_ville",
    "mdo": "maison_ouvriers",
    "compartiment": "compartiment",
    "trash": "batiments_non_defensifs",
    "deadzone": "zone_morte",
    "funnel": "entonnoir",
}

TERMES_TACTIQUES = {
    "anti 3": "anti_3_etoiles",
    "anti3": "anti_3_etoiles",
    "anti 2": "anti_2_etoiles",
    "walkable": "destructible_sans_mur",
    "spam": "pose_groupee",
    "open": "ouverture",
    "open sapeur": "ouverture_sapeur",
    "funnel": "entonnoir",
    "clean": "finition",
    "sui": "suicide_heros",
    "suicide": "suicide_heros",
    "dips": "attaque_hdv_inferieur",
    "scout": "attaque_hdv_superieur",
    "bait": "piege_attaquant",
    "cancer": "attaque_no_skill",
    "fail": "echec",
    "fail time": "echec_temps",
    "horloge": "envoi_circulaire",
    "skitch": "dessin_strategie",
    "strat": "strategie",
    "training": "entrainement",
}

GUERRE = {
    "gdc": "guerre_clan",
    "ldc": "ligue_guerre_clan",
    "jdc": "jeux_de_clan",
    "fw": "guerre_amicale",
    "war": "guerre",
    "bd": "composition_hdv",
    "roster": "liste_participants",
    "ws": "serie_victoires",
    "p1": "premiere_attaque",
    "ks": "heros_seuls_p1",
    "régulate": "regles_gdc",
}

# ── Normalisation d'un texte ──────────────────
def normalize(texte: str) -> str:
    t = texte.lower().strip()
    # Compos en premier (multi-mots)
    for abr, full in COMPOS.items():
        t = t.replace(abr, full)
    for abr, full in {**HEROS, **TROUPES, **SORTS, **DEFENSES, **STRUCTURES, **TERMES_TACTIQUES, **GUERRE}.items():
        t = t.replace(f" {abr} ", f" {full} ")
    return t

def detect_compo_from_text(texte: str) -> list:
    """Détecte les compositions d'attaque dans un message"""
    t = texte.lower()
    found = []
    for abr, full in COMPOS.items():
        if abr in t:
            found.append(full)
    for abr, full in TROUPES.items():
        if f" {abr}" in t or t.startswith(abr):
            found.append(full)
    return list(set(found)) or ["inconnu"]

if __name__ == "__main__":
    tests = ["lalo avec rc", "blizzard sur anti3", "sui reine puis minhogs", "électrone sur le cdc"]
    for t in tests:
        print(f"'{t}' → {detect_compo_from_text(t)}")
