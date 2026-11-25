class_name FreeCamera
extends Camera3D
## Caméra libre pour visiter la zone de test (remplacée à l'étape 2
## par la caméra à la troisième personne qui suit le personnage).
## Les touches sont définies dans le projet (Projet > Paramètres > Contrôles),
## par leur position sur le clavier : ZQSD en AZERTY, WASD en QWERTY.

@export var move_speed: float = 12.0
@export var fast_multiplier: float = 3.5
@export var mouse_sensitivity: float = 0.0025

var _yaw: float = 0.0
var _pitch: float = 0.0


func _ready() -> void:
	_yaw = rotation.y
	_pitch = rotation.x
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_yaw -= event.relative.x * mouse_sensitivity
		_pitch = clampf(_pitch - event.relative.y * mouse_sensitivity, -1.5, 1.5)
		rotation = Vector3(_pitch, _yaw, 0.0)
	elif event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _process(delta: float) -> void:
	var input := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var vertical := Input.get_axis("move_down", "move_up")
	var dir := (global_basis * Vector3(input.x, 0.0, input.y)) + Vector3.UP * vertical
	if dir.length() > 1.0:
		dir = dir.normalized()
	var speed := move_speed * (fast_multiplier if Input.is_action_pressed("sprint") else 1.0)
	global_position += dir * speed * delta
