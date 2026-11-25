class_name DayNightCycle
extends Node
## Cycle jour/nuit : fait tourner le soleil et la lune, change les couleurs
## du ciel, de la lumière ambiante et du brouillard selon la palette de la région.
##
## Plus tard (étape 4), l'heure sera donnée par le serveur : il suffira
## d'appeler set_hour() à la réception de l'heure officielle.

signal night_started
signal day_started

@export var sun: DirectionalLight3D
@export var world_environment: WorldEnvironment
@export var region_id: String = "plains_dawn"

## Heure actuelle, de 0 à 24.
var hour: float = 9.0
## Multiplicateur de vitesse (touche T pendant les tests).
var speed_multiplier: float = 1.0

var _palette: Dictionary = {}
var _time_cfg: Dictionary = {}
var _sky_material: ShaderMaterial
var _was_night: bool = false
var _ready_to_run: bool = false


## À appeler une fois l'environnement de la région créé.
func setup() -> void:
	_palette = DataLoader.load_palette(region_id)
	var cfg: Variant = DataLoader.load_json("res://data/world/time.json")
	_time_cfg = cfg if cfg is Dictionary else {}
	hour = float(_time_cfg.get("start_hour", 9.0))
	if world_environment and world_environment.environment and world_environment.environment.sky:
		_sky_material = world_environment.environment.sky.sky_material as ShaderMaterial
	_was_night = is_night()
	_ready_to_run = true
	_apply()


func _process(delta: float) -> void:
	if not _ready_to_run:
		return
	var day_minutes: float = float(_time_cfg.get("day_length_minutes", 24.0))
	# 24 heures de jeu durent « day_minutes » minutes réelles.
	var hours_per_second: float = 24.0 / (day_minutes * 60.0)
	hour = fmod(hour + delta * hours_per_second * speed_multiplier, 24.0)
	_apply()


func set_hour(value: float) -> void:
	hour = fmod(value, 24.0)
	_apply()


func is_night() -> bool:
	var start := float(_time_cfg.get("night_start_hour", 20.0))
	var end := float(_time_cfg.get("night_end_hour", 6.0))
	return hour >= start or hour < end


func toggle_fast_time() -> void:
	var fast := float(_time_cfg.get("debug_fast_multiplier", 60.0))
	speed_multiplier = 1.0 if speed_multiplier > 1.0 else fast


func _col(key: String) -> Color:
	return DataLoader.color(_palette, key)


func _apply() -> void:
	# Angle du soleil : 6 h = lever (est), 12 h = zénith, 18 h = coucher (ouest).
	var angle := (hour - 6.0) / 24.0 * TAU
	var sun_dir := Vector3(cos(angle), sin(angle), 0.35).normalized()
	var height := sun_dir.y

	# 0 = nuit, 1 = jour ; « sunset » vaut 1 quand le soleil est proche de l'horizon.
	var day := smoothstep(-0.12, 0.18, height)
	var sunset := clampf(1.0 - absf(height) / 0.3, 0.0, 1.0)

	# La lumière vient du soleil le jour, de la lune (à l'opposé) la nuit.
	if sun:
		var light_dir := sun_dir if height > -0.05 else -sun_dir
		sun.look_at_from_position(Vector3.ZERO, -light_dir, Vector3.UP if absf(light_dir.y) < 0.99 else Vector3.FORWARD)
		var day_light := _col("sun_light_day").lerp(_col("sun_light_sunset"), sunset)
		if height > -0.05:
			sun.light_color = day_light
			sun.light_energy = float(_palette.get("sun_energy", 1.2)) * smoothstep(-0.05, 0.12, height)
		else:
			sun.light_color = _col("moon_light")
			sun.light_energy = float(_palette.get("moon_energy", 0.3)) * smoothstep(0.05, 0.2, -height)

	if _sky_material:
		var top := _col("sky_night_top").lerp(_col("sky_day_top"), day)
		var horizon := _col("sky_night_horizon").lerp(_col("sky_day_horizon"), day)
		horizon = horizon.lerp(_col("sky_sunset_horizon"), sunset * 0.8)
		_sky_material.set_shader_parameter("top_color", top)
		_sky_material.set_shader_parameter("horizon_color", horizon)
		_sky_material.set_shader_parameter("ground_color", _col("sky_ground") * lerpf(0.35, 1.0, day))
		_sky_material.set_shader_parameter("sun_color", _col("sun_color"))
		_sky_material.set_shader_parameter("moon_color", _col("moon_color"))
		_sky_material.set_shader_parameter("cloud_color", _col("cloud_color").lerp(_col("sky_sunset_horizon"), sunset * 0.5))
		_sky_material.set_shader_parameter("cloud_shadow_color", _col("cloud_shadow_color"))
		_sky_material.set_shader_parameter("sun_direction", sun_dir)
		_sky_material.set_shader_parameter("day_amount", day)

	if world_environment and world_environment.environment:
		var env := world_environment.environment
		env.ambient_light_color = _col("ambient_night").lerp(_col("ambient_day"), day)
		env.ambient_light_energy = lerpf(float(_palette.get("ambient_energy_night", 0.3)), float(_palette.get("ambient_energy_day", 0.5)), day)
		var fog := _col("fog_night").lerp(_col("fog_day"), day)
		env.fog_light_color = fog.lerp(_col("sky_sunset_horizon"), sunset * 0.4)

	var night := is_night()
	if night != _was_night:
		_was_night = night
		if night:
			night_started.emit()
		else:
			day_started.emit()
