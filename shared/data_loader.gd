class_name DataLoader
extends RefCounted
## Lecture des fichiers de données (JSON) du dossier res://data.
## Toutes les valeurs de réglage du jeu (palettes, EXP, butin…) passent par ici,
## pour ne jamais les écrire en dur dans le code.


## Charge un fichier JSON et renvoie son contenu (Dictionary ou Array).
## Renvoie null et affiche une erreur claire si le fichier est absent ou mal écrit.
static func load_json(path: String) -> Variant:
	if not FileAccess.file_exists(path):
		push_error("[Données] Fichier introuvable : %s" % path)
		return null
	var text := FileAccess.get_file_as_string(path)
	var json := JSON.new()
	var err := json.parse(text)
	if err != OK:
		push_error("[Données] Erreur dans %s, ligne %d : %s" % [path, json.get_error_line(), json.get_error_message()])
		return null
	return json.data


## Lit une couleur écrite "#RRGGBB" (ou "#RRGGBBAA") dans un fichier de données.
static func color(dict: Dictionary, key: String, fallback: Color = Color.MAGENTA) -> Color:
	if not dict.has(key):
		push_warning("[Données] Couleur manquante : %s" % key)
		return fallback
	return Color.html(str(dict[key]))


## Liste des régions du monde (data/world/regions.json).
static func load_regions() -> Array:
	var data: Variant = load_json("res://data/world/regions.json")
	if data is Dictionary and data.has("regions"):
		return data["regions"]
	return []


## Palette de couleurs d'une région (data/regions/<id>/palette.json).
static func load_palette(region_id: String) -> Dictionary:
	var data: Variant = load_json("res://data/regions/%s/palette.json" % region_id)
	if data is Dictionary:
		return data
	return {}
