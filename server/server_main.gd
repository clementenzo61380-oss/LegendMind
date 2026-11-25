extends Node
## Serveur dédié (« le serveur fait foi »).
## ⚠ Tout ce qui est dans server/ et data/server_only/ n'est JAMAIS livré au joueur.
##
## Étape 1 : le serveur démarre, lit sa configuration et prépare une
## « hôte de région » par région du monde. Le réseau arrive à l'étape 4.
##
## Découpage par régions (préparé, pas encore utilisé) : chaque région est
## simulée par son propre RegionHost. Plus tard, un serveur pourra n'en lancer
## qu'une partie (option --regions=plains_dawn,dark_forest) et tourner sur
## une machine différente des autres.

const RegionHost := preload("res://server/world/region_host.gd")

var config: Dictionary = {}
var region_hosts: Dictionary = {}


func _ready() -> void:
	var cfg: Variant = DataLoader.load_json("res://data/server_only/server_config.json")
	config = cfg if cfg is Dictionary else {}
	Engine.physics_ticks_per_second = int(config.get("tick_rate", 30))

	var wanted := _regions_from_cmdline()
	for region in DataLoader.load_regions():
		var id: String = region.get("id", "")
		if wanted.is_empty() or id in wanted:
			var host = RegionHost.new()
			host.name = "Region_%s" % id
			host.region_id = id
			add_child(host)
			region_hosts[id] = host

	print("[Serveur] Éclats d'Éther — serveur prêt.")
	print("[Serveur] Port prévu : %d | Cadence : %d mises à jour/s | Régions : %s" % [
		int(config.get("port", 24800)), Engine.physics_ticks_per_second, ", ".join(PackedStringArray(region_hosts.keys()))])


func _regions_from_cmdline() -> Array:
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--regions="):
			return Array(arg.trim_prefix("--regions=").split(",", false))
	return []
