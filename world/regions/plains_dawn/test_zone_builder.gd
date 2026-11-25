extends Node3D
## Construit la petite zone de test des Plaines de l'Aube avec des formes simples
## (en attendant les vrais modèles 3D, voir ASSETS.md).
## Le décor est tiré au hasard mais avec une « graine » fixe : il est
## identique à chaque lancement, et le sera aussi pour tous les joueurs.

@export var region_id: String = "plains_dawn"
@export var world_seed: int = 4242
@export var zone_radius: float = 70.0

var _p: Dictionary = {}
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	_p = DataLoader.load_palette(region_id)
	_rng.seed = world_seed
	_build_ground()
	_build_hills()
	_build_pond()
	_build_trees()
	_build_rocks()
	_build_flowers()
	_build_parkour_test()
	_build_shrine()
	_build_crystals()


func _c(key: String) -> Color:
	return DataLoader.color(_p, key)


## Ajoute un objet visible ; avec « solid », on peut marcher dessus (étape 2).
func _add(mesh: Mesh, mat: Material, pos: Vector3, rot: Vector3 = Vector3.ZERO, scl: Vector3 = Vector3.ONE, solid: bool = true, parent: Node3D = self) -> MeshInstance3D:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = mat
	if solid:
		var body := StaticBody3D.new()
		body.position = pos
		body.rotation = rot
		body.scale = scl
		parent.add_child(body)
		body.add_child(mi)
		var shape := CollisionShape3D.new()
		shape.shape = mesh.create_convex_shape()
		body.add_child(shape)
	else:
		mi.position = pos
		mi.rotation = rot
		mi.scale = scl
		parent.add_child(mi)
	return mi


func _build_ground() -> void:
	var plane := PlaneMesh.new()
	plane.size = Vector2(zone_radius * 2.0, zone_radius * 2.0)
	plane.subdivide_width = 8
	plane.subdivide_depth = 8
	var mi := MeshInstance3D.new()
	mi.mesh = plane
	# Pas de contour sur le sol (il serait invisible de toute façon).
	mi.material_override = ToonMaterial.make(_c("ground"), {"outline": false, "rim": 0.0, "specular": 0.0})
	var body := StaticBody3D.new()
	body.name = "Ground"
	add_child(body)
	body.add_child(mi)
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(zone_radius * 2.0, 1.0, zone_radius * 2.0)
	shape.shape = box
	shape.position.y = -0.5
	body.add_child(shape)


func _build_hills() -> void:
	var mat := ToonMaterial.make(_c("ground_dark"), {"rim": 0.15, "specular": 0.0})
	for i in 7:
		var sphere := SphereMesh.new()
		sphere.radius = 1.0
		sphere.height = 2.0
		sphere.radial_segments = 24
		sphere.rings = 12
		var angle := _rng.randf() * TAU
		var dist := _rng.randf_range(35.0, zone_radius - 8.0)
		var size := _rng.randf_range(8.0, 16.0)
		_add(sphere, mat, Vector3(cos(angle) * dist, -size * 0.15, sin(angle) * dist), Vector3.ZERO, Vector3(size, size * 0.45, size))


func _build_pond() -> void:
	var disc := CylinderMesh.new()
	disc.top_radius = 7.0
	disc.bottom_radius = 7.0
	disc.height = 0.05
	disc.radial_segments = 32
	var water := ToonMaterial.make(_c("water"), {"outline": false, "specular": 1.2, "rim": 0.6, "emission": _c("water"), "emission_energy": 0.15})
	_add(disc, water, Vector3(-18.0, 0.03, 14.0), Vector3.ZERO, Vector3.ONE, false)
	# Bord du point d'eau.
	var rim_mat := ToonMaterial.make(_c("rock"), {})
	for i in 14:
		var a := float(i) / 14.0 * TAU
		var stone := SphereMesh.new()
		stone.radius = 0.6
		stone.height = 0.9
		stone.radial_segments = 6
		stone.rings = 3
		_add(stone, rim_mat, Vector3(-18.0 + cos(a) * 7.3, 0.15, 14.0 + sin(a) * 7.3), Vector3(0, a, 0), Vector3.ONE * _rng.randf_range(0.7, 1.3))


func _build_trees() -> void:
	var trunk_mat := ToonMaterial.make(_c("tree_trunk"), {})
	var leaf_mats := [
		ToonMaterial.make(_c("tree_leaves"), {"rim": 0.5}),
		ToonMaterial.make(_c("tree_leaves_alt"), {"rim": 0.5}),
	]
	var pine_mat := ToonMaterial.make(_c("pine_leaves"), {"rim": 0.4})
	var placed := 0
	var tries := 0
	while placed < 26 and tries < 300:
		tries += 1
		var pos := Vector3(_rng.randf_range(-zone_radius + 6, zone_radius - 6), 0.0, _rng.randf_range(-zone_radius + 6, zone_radius - 6))
		# On garde le centre dégagé (zone de départ et parcours d'acrobaties).
		if pos.length() < 14.0 or pos.distance_to(Vector3(-18, 0, 14)) < 10.0:
			continue
		var tree := Node3D.new()
		tree.position = pos
		tree.rotation.y = _rng.randf() * TAU
		add_child(tree)
		var s := _rng.randf_range(0.8, 1.4)
		var trunk := CylinderMesh.new()
		trunk.top_radius = 0.25 * s
		trunk.bottom_radius = 0.4 * s
		trunk.height = 3.0 * s
		trunk.radial_segments = 8
		_add(trunk, trunk_mat, Vector3(0, 1.5 * s, 0), Vector3.ZERO, Vector3.ONE, true, tree)
		if _rng.randf() < 0.35:
			# Sapin : cônes empilés.
			for k in 3:
				var cone := CylinderMesh.new()
				cone.top_radius = 0.0
				cone.bottom_radius = (2.0 - k * 0.5) * s
				cone.height = 2.2 * s
				cone.radial_segments = 8
				_add(cone, pine_mat, Vector3(0, (3.0 + k * 1.3) * s, 0), Vector3.ZERO, Vector3.ONE, false, tree)
		else:
			# Arbre rond : boules de feuillage.
			var leaf_mat: Material = leaf_mats[_rng.randi() % leaf_mats.size()]
			for k in 3:
				var ball := SphereMesh.new()
				ball.radius = 1.0
				ball.height = 2.0
				ball.radial_segments = 16
				ball.rings = 8
				var offset := Vector3(_rng.randf_range(-0.8, 0.8), 3.4 + k * 0.7, _rng.randf_range(-0.8, 0.8)) * s
				_add(ball, leaf_mat, offset, Vector3.ZERO, Vector3.ONE * _rng.randf_range(1.3, 1.9) * s, false, tree)
		placed += 1


func _build_rocks() -> void:
	var mats := [ToonMaterial.make(_c("rock"), {}), ToonMaterial.make(_c("rock_dark"), {})]
	for i in 18:
		var rock := SphereMesh.new()
		rock.radius = 1.0
		rock.height = 1.6
		rock.radial_segments = 6
		rock.rings = 4
		var pos := Vector3(_rng.randf_range(-zone_radius, zone_radius), 0.2, _rng.randf_range(-zone_radius, zone_radius))
		if pos.length() < 10.0:
			continue
		var s := _rng.randf_range(0.6, 2.4)
		_add(rock, mats[i % 2], pos, Vector3(_rng.randf() * 0.4, _rng.randf() * TAU, _rng.randf() * 0.4), Vector3(s, s * _rng.randf_range(0.6, 1.0), s))


func _build_flowers() -> void:
	# Petites touches de couleur, sans collision (décor pur).
	var mats := [
		ToonMaterial.make(_c("flower_a"), {"outline": false}),
		ToonMaterial.make(_c("flower_b"), {"outline": false}),
		ToonMaterial.make(_c("grass_tuft"), {"outline": false}),
	]
	var mesh := SphereMesh.new()
	mesh.radius = 0.15
	mesh.height = 0.3
	mesh.radial_segments = 6
	mesh.rings = 3
	for i in 160:
		var pos := Vector3(_rng.randf_range(-zone_radius, zone_radius), 0.12, _rng.randf_range(-zone_radius, zone_radius))
		_add(mesh, mats[_rng.randi() % mats.size()], pos, Vector3.ZERO, Vector3.ONE * _rng.randf_range(0.7, 1.6), false)


## Parcours de test pour les acrobaties de l'étape 2 :
## un grand mur (course sur les murs), deux murs face à face (rebonds),
## des blocs à hauteurs croissantes (double saut) et une paroi à escalader.
func _build_parkour_test() -> void:
	var root := Node3D.new()
	root.name = "ParkourTest"
	root.position = Vector3(16, 0, -10)
	add_child(root)
	var wall_mat := ToonMaterial.make(_c("stone_wall"), {})
	var wood_mat := ToonMaterial.make(_c("wood_plank"), {})
	var climb_mat := ToonMaterial.make(_c("rock_dark"), {"rim": 0.2})

	# Long mur pour la course sur les murs.
	var long_wall := BoxMesh.new()
	long_wall.size = Vector3(14, 5, 1)
	_add(long_wall, wall_mat, Vector3(0, 2.5, 0), Vector3.ZERO, Vector3.ONE, true, root)

	# Deux murs parallèles pour rebondir de l'un à l'autre.
	var tall := BoxMesh.new()
	tall.size = Vector3(1, 9, 6)
	_add(tall, wall_mat, Vector3(-4, 4.5, 8), Vector3.ZERO, Vector3.ONE, true, root)
	_add(tall, wall_mat, Vector3(0.5, 4.5, 8), Vector3.ZERO, Vector3.ONE, true, root)

	# Escalier de blocs (sauts et double sauts).
	for i in 5:
		var block := BoxMesh.new()
		block.size = Vector3(2.5, 1.0 + i * 1.1, 2.5)
		_add(block, wood_mat, Vector3(6 + i * 3.2, (1.0 + i * 1.1) * 0.5, 6), Vector3.ZERO, Vector3.ONE, true, root)

	# Paroi d'escalade (surface marquée d'une couleur différente).
	var cliff := BoxMesh.new()
	cliff.size = Vector3(8, 12, 3)
	_add(cliff, climb_mat, Vector3(10, 6, -6), Vector3.ZERO, Vector3.ONE, true, root)


## Petit autel lumineux au centre : point de repère et test du bloom.
func _build_shrine() -> void:
	var stone := ToonMaterial.make(_c("stone_wall"), {})
	var base := CylinderMesh.new()
	base.top_radius = 2.2
	base.bottom_radius = 2.6
	base.height = 0.6
	base.radial_segments = 8
	_add(base, stone, Vector3(0, 0.3, 0))
	for i in 4:
		var a := float(i) / 4.0 * TAU + PI / 4.0
		var pillar := BoxMesh.new()
		pillar.size = Vector3(0.5, 3.2, 0.5)
		_add(pillar, stone, Vector3(cos(a) * 1.8, 2.2, sin(a) * 1.8))
	var orb := SphereMesh.new()
	orb.radius = 0.5
	orb.height = 1.0
	var glow := ToonMaterial.make(_c("shrine_glow"), {"emission": _c("shrine_glow"), "emission_energy": 3.0, "outline_width": 1.5})
	var orb_mi := _add(orb, glow, Vector3(0, 2.2, 0), Vector3.ZERO, Vector3.ONE, false)
	orb_mi.name = "ShrineOrb"
	var light := OmniLight3D.new()
	light.light_color = _c("shrine_glow")
	light.light_energy = 2.0
	light.omni_range = 9.0
	light.position = Vector3(0, 2.2, 0)
	add_child(light)


## Cristaux lumineux (très visibles la nuit grâce au bloom).
func _build_crystals() -> void:
	var mat := ToonMaterial.make(_c("crystal"), {"emission": _c("crystal_glow"), "emission_energy": 2.5, "specular": 1.0})
	for i in 6:
		var a := _rng.randf() * TAU
		var d := _rng.randf_range(18.0, 40.0)
		var center := Vector3(cos(a) * d, 0, sin(a) * d)
		for k in 3:
			var prism := CylinderMesh.new()
			prism.top_radius = 0.0
			prism.bottom_radius = 0.35
			prism.height = _rng.randf_range(1.2, 2.4)
			prism.radial_segments = 5
			_add(prism, mat, center + Vector3(_rng.randf_range(-0.6, 0.6), prism.height * 0.4, _rng.randf_range(-0.6, 0.6)), Vector3(_rng.randf_range(-0.35, 0.35), 0, _rng.randf_range(-0.35, 0.35)), Vector3.ONE, false)
