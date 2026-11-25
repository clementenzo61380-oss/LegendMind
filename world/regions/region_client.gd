class_name RegionClient
extends Node3D
## Racine d'une région côté joueur : environnement, cycle jour/nuit, interface.
## Chaque région du monde a sa propre scène avec ce script à sa racine.
## (Côté serveur, c'est server/world/region_host.gd qui simule la même région.)

@export var region_id: String = "plains_dawn"

@onready var world_environment: WorldEnvironment = $WorldEnvironment
@onready var day_night: DayNightCycle = $DayNight
@onready var hud_label: Label = $HUD/Info
@onready var help_label: Label = $HUD/Help

var _region_name: String = ""


func _ready() -> void:
	var palette := DataLoader.load_palette(region_id)
	world_environment.environment = EnvironmentBuilder.build(palette)
	day_night.region_id = region_id
	day_night.world_environment = world_environment
	for region in DataLoader.load_regions():
		if region.get("id") == region_id:
			_region_name = tr(region.get("name_key", region_id))
	help_label.text = tr("HUD_HELP")
	day_night.setup()


func _process(_delta: float) -> void:
	var h := int(day_night.hour)
	var m := int((day_night.hour - h) * 60.0)
	var moment: String = tr("HUD_NIGHT") if day_night.is_night() else tr("HUD_DAY")
	var fast: String = ""
	if day_night.speed_multiplier > 1.0:
		fast = "  ×%d" % int(day_night.speed_multiplier)
	hud_label.text = "%s — %02d:%02d (%s)%s\n%d FPS" % [_region_name, h, m, moment, fast, Engine.get_frames_per_second()]


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("debug_fast_time"):
		day_night.toggle_fast_time()
	elif event.is_action_pressed("debug_skip_time"):
		day_night.set_hour(day_night.hour + 3.0)
	elif event.is_action_pressed("toggle_help"):
		help_label.visible = not help_label.visible
