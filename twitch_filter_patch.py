import re

# ── Lis le fichier actuel
with open("twitch_scraper.py", "r") as f:
    content = f.read()

# ── 1. Remplace is_th18 par un filtre strict HDV18 uniquement
old_is_th18 = '''def is_th18(texte: str) -> bool:
    return bool(re.search(
        r'TH18|HDV18|TH\\s*18|HDV\\s*18|Town\\s*Hall\\s*18|Hotel\\s*de\\s*Ville\\s*18',
        texte, re.IGNORECASE
    ))'''

new_is_th18 = '''def is_th18(texte: str) -> bool:
    """Filtre STRICT : uniquement HDV18 / TH18"""
    return bool(re.search(
        r'\\bTH\\s*18\\b|\\bHDV\\s*18\\b|\\bTown\\s*Hall\\s*18\\b|\\bH[oô]tel\\s*de\\s*Ville\\s*18\\b',
        texte, re.IGNORECASE
    ))

def is_not_other_th(texte: str) -> bool:
    """Vérifie que ce n'est pas un autre HDV mentionné en priorité"""
    for i in [9,10,11,12,13,14,15,16,17]:
        if re.search(rf'\\bTH\\s*{i}\\b|\\bHDV\\s*{i}\\b', texte, re.IGNORECASE):
            # Si TH18 est aussi mentionné c'est ok, sinon on exclut
            if not re.search(r'\\bTH\\s*18\\b|\\bHDV\\s*18\\b', texte, re.IGNORECASE):
                return False
    return True'''

content = content.replace(old_is_th18, new_is_th18)

# ── 2. Dans scrape_vods : ajoute le filtre strict après création du dict
old_vods_append = '''                all_vods.append({
                    "video_id": v["id"],'''

new_vods_append = '''                # Filtre strict HDV18
                if not is_th18(texte) or not is_not_other_th(texte):
                    continue

                all_vods.append({
                    "video_id": v["id"],'''

content = content.replace(old_vods_append, new_vods_append, 1)

# ── 3. Dans scrape_clips : même filtre
old_clips_append = '''                all_clips.append({
                    "video_id": "clip_" + c["id"],'''

new_clips_append = '''                # Filtre strict HDV18
                if not is_th18(texte) or not is_not_other_th(texte):
                    continue

                all_clips.append({
                    "video_id": "clip_" + c["id"],'''

content = content.replace(old_clips_append, new_clips_append, 1)

# ── 4. Dans scrape_live_streams : même filtre
old_live_append = '''                all_live.append({
                    "video_id": "live_" + s["id"],'''

new_live_append = '''                # Filtre strict HDV18
                if not is_th18(texte) or not is_not_other_th(texte):
                    continue

                all_live.append({
                    "video_id": "live_" + s["id"],'''

content = content.replace(old_live_append, new_live_append, 1)

# ── 5. Dans scrape_by_tag : filtre sur game_name ET titre
old_tag_append = '''                    all_tagged.append({
                        "video_id": "ch_" + ch["id"],'''

new_tag_append = '''                    # Filtre : game doit être CoC ET titre contient TH18
                    titre_ch = ch.get("title", "")
                    if not is_th18(titre_ch):
                        continue

                    all_tagged.append({
                        "video_id": "ch_" + ch["id"],'''

content = content.replace(old_tag_append, new_tag_append, 1)

# ── Sauvegarde
with open("twitch_scraper.py", "w") as f:
    f.write(content)

print("✅ Patch appliqué — filtre strict HDV18 actif sur toutes les phases")
