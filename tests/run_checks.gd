extends SceneTree
## Vérifications automatiques, sans fenêtre :
##   godot --headless -s res://tests/run_checks.gd
## Affiche OK / ÉCHEC pour chaque test et quitte avec le code 1 si un test échoue.

var _failures: int = 0


func _initialize() -> void:
	_check_data_files()
	_check_client_never_references_server()
	await _check_test_zone_builds()
	print("")
	if _failures == 0:
		print("✅ Toutes les vérifications sont passées.")
	else:
		print("❌ %d vérification(s) en échec." % _failures)
	quit(1 if _failures > 0 else 0)


func _ok(cond: bool, label: String) -> void:
	if cond:
		print("  OK     ", label)
	else:
		print("  ÉCHEC  ", label)
		_failures += 1


func _check_data_files() -> void:
	print("Fichiers de données :")
	var regions := DataLoader.load_regions()
	_ok(regions.size() == 3, "3 régions déclarées")
	for region in regions:
		var palette := DataLoader.load_palette(region["id"])
		var scene: String = region.get("scene", "")
		if scene != "":
			_ok(not palette.is_empty(), "palette présente pour %s" % region["id"])
			_ok(ResourceLoader.exists(scene), "scène présente pour %s" % region["id"])
	_ok(DataLoader.load_json("res://data/world/time.json") is Dictionary, "time.json lisible")
	_ok(DataLoader.load_json("res://data/server_only/server_config.json") is Dictionary, "server_config.json lisible")


## Règle anti-triche : aucun fichier livré au joueur ne doit charger
## le code ou les données du serveur (sauf le point d'entrée, par son nom).
func _check_client_never_references_server() -> void:
	print("Séparation client / serveur :")
	var offenders: Array[String] = []
	for dir in ["res://client", "res://core", "res://shared", "res://rendering", "res://world", "res://data/world", "res://data/regions"]:
		_scan(dir, offenders)
	_ok(offenders.is_empty(), "aucune référence au serveur hors de core/boot.gd %s" % (str(offenders) if not offenders.is_empty() else ""))


func _scan(path: String, offenders: Array[String]) -> void:
	var d := DirAccess.open(path)
	if d == null:
		return
	for f in d.get_files():
		if not (f.ends_with(".gd") or f.ends_with(".tscn") or f.ends_with(".tres") or f.ends_with(".json")):
			continue
		var full := path.path_join(f)
		if full == "res://core/boot.gd":
			continue
		var text := FileAccess.get_file_as_string(full)
		if "res://server" in text or "server_only" in text:
			offenders.append(full)
	for sub in d.get_directories():
		_scan(path.path_join(sub), offenders)


func _check_test_zone_builds() -> void:
	print("Zone de test :")
	var packed: PackedScene = load("res://world/regions/plains_dawn/test_zone.tscn")
	_ok(packed != null, "la scène se charge")
	if packed == null:
		return
	var zone := packed.instantiate()
	root.add_child(zone)
	await process_frame
	var meshes := zone.find_children("*", "MeshInstance3D", true, false)
	_ok(meshes.size() > 100, "le décor est construit (%d objets)" % meshes.size())
	var all_toon := true
	for m in meshes:
		var mat := (m as MeshInstance3D).material_override as ShaderMaterial
		if mat == null or mat.shader != ToonMaterial.TOON_SHADER:
			all_toon = false
	_ok(all_toon, "tous les objets utilisent le shader toon")
	var env := (zone.get_node("WorldEnvironment") as WorldEnvironment).environment
	_ok(env != null and env.glow_enabled and env.fog_enabled, "environnement avec bloom et brouillard")
	var dn: DayNightCycle = zone.get_node("DayNight")
	dn.set_hour(23.0)
	_ok(dn.is_night(), "23 h = nuit")
	dn.set_hour(12.0)
	_ok(not dn.is_night(), "12 h = jour")
	zone.queue_free()
