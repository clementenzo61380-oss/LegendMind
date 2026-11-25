extends Node
## Point d'entrée unique du jeu.
## Le même projet démarre soit en CLIENT (le jeu du joueur), soit en
## SERVEUR DÉDIÉ (sans fenêtre), selon la ligne de commande :
##   godot --headless -- --server      → serveur
##   (rien de spécial)                 → client
##
## IMPORTANT : le code du serveur est chargé ici par son chemin écrit en texte,
## jamais avec preload(). Ainsi le jeu livré aux joueurs peut ne contenir
## aucun fichier du dossier server/ (secrets des monstres uniques, etc.).

const SERVER_ENTRY := "res://server/server_main.gd"


static func is_server_mode() -> bool:
	return OS.has_feature("dedicated_server") or "--server" in OS.get_cmdline_user_args()


func _ready() -> void:
	if is_server_mode():
		_start_server()
	else:
		_start_client()


func _start_server() -> void:
	if not ResourceLoader.exists(SERVER_ENTRY):
		push_error("[Démarrage] Ce build ne contient pas le serveur (c'est normal pour un build joueur).")
		get_tree().quit(1)
		return
	var server_script: GDScript = load(SERVER_ENTRY)
	var server: Node = server_script.new()
	server.name = "Server"
	add_child(server)


func _start_client() -> void:
	var data: Variant = DataLoader.load_json("res://data/world/regions.json")
	var start_id: String = data.get("start_region", "plains_dawn") if data is Dictionary else "plains_dawn"
	for region in DataLoader.load_regions():
		if region.get("id") == start_id and str(region.get("scene", "")) != "":
			get_tree().change_scene_to_file.call_deferred(region["scene"])
			return
	push_error("[Démarrage] Région de départ introuvable : %s" % start_id)
