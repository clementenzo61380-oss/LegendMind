class_name ToonMaterial
extends RefCounted
## Fabrique de matériaux toon. Tout objet du jeu devrait passer par ici
## pour garder un rendu cohérent (ombres tranchées + contour noir).

const TOON_SHADER: Shader = preload("res://rendering/toon.gdshader")
const OUTLINE_SHADER: Shader = preload("res://rendering/outline.gdshader")

## Cache : une seule ressource par combinaison de réglages (meilleures performances).
static var _cache: Dictionary = {}


## Crée (ou réutilise) un matériau toon.
## options possibles : outline (bool), outline_width (float), emission (Color),
## emission_energy (float), bands (int), rim (float), specular (float), shadow_tint (Color).
static func make(color: Color, options: Dictionary = {}) -> ShaderMaterial:
	var key := str(color) + str(options)
	if _cache.has(key):
		return _cache[key]

	var mat := ShaderMaterial.new()
	mat.shader = TOON_SHADER
	mat.set_shader_parameter("albedo", color)
	if options.has("bands"):
		mat.set_shader_parameter("bands", options["bands"])
	if options.has("rim"):
		mat.set_shader_parameter("rim_strength", options["rim"])
	if options.has("specular"):
		mat.set_shader_parameter("specular_strength", options["specular"])
	if options.has("shadow_tint"):
		mat.set_shader_parameter("shadow_tint", options["shadow_tint"])
	if options.has("emission"):
		mat.set_shader_parameter("emission_color", options["emission"])
		mat.set_shader_parameter("emission_energy", options.get("emission_energy", 2.0))

	if options.get("outline", true):
		mat.next_pass = make_outline(options.get("outline_width", 2.0))

	_cache[key] = mat
	return mat


## Matériau de contour seul (passe ajoutée derrière le matériau toon).
static func make_outline(width: float = 2.0, color: Color = Color(0.06, 0.04, 0.1)) -> ShaderMaterial:
	var key := "outline_%s_%s" % [width, color]
	if _cache.has(key):
		return _cache[key]
	var mat := ShaderMaterial.new()
	mat.shader = OUTLINE_SHADER
	mat.set_shader_parameter("outline_width", width)
	mat.set_shader_parameter("outline_color", color)
	_cache[key] = mat
	return mat
