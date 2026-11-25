class_name EnvironmentBuilder
extends RefCounted
## Réglage global de l'environnement : ciel stylisé, lumière ambiante,
## bloom (halo lumineux), brouillard et couleurs. Utilisé par toutes les régions,
## seules les couleurs changent (palette de la région).

const SKY_SHADER: Shader = preload("res://rendering/sky_toon.gdshader")


static func build(palette: Dictionary) -> Environment:
	var env := Environment.new()

	# Ciel stylisé (les couleurs sont ensuite animées par le cycle jour/nuit).
	var sky_mat := ShaderMaterial.new()
	sky_mat.shader = SKY_SHADER
	var sky := Sky.new()
	sky.sky_material = sky_mat
	sky.radiance_size = Sky.RADIANCE_SIZE_64
	env.background_mode = Environment.BG_SKY
	env.sky = sky

	# Lumière ambiante unie : les ombres restent colorées et lisibles.
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = DataLoader.color(palette, "ambient_day", Color(0.7, 0.75, 1.0))
	env.ambient_light_energy = float(palette.get("ambient_energy_day", 0.5))
	env.reflected_light_source = Environment.REFLECTION_SOURCE_DISABLED

	# Rendu des couleurs : on garde des couleurs vives (pas de rendu « cinéma » terne).
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	env.tonemap_exposure = 1.0
	env.tonemap_white = 1.0

	# Bloom : seules les choses très lumineuses (soleil, cristaux, sorts) brillent.
	env.glow_enabled = true
	env.glow_normalized = false
	env.glow_intensity = 0.9
	env.glow_strength = 1.0
	env.glow_bloom = 0.05
	env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SCREEN
	env.glow_hdr_threshold = 1.0
	env.glow_hdr_scale = 2.0
	env.set_glow_level(0, 0.0)
	env.set_glow_level(1, 1.0)
	env.set_glow_level(2, 1.0)
	env.set_glow_level(3, 0.8)
	env.set_glow_level(4, 0.6)
	env.set_glow_level(5, 0.3)

	# Brouillard léger et coloré qui donne de la profondeur aux paysages.
	env.fog_enabled = true
	env.fog_mode = Environment.FOG_MODE_EXPONENTIAL
	env.fog_light_color = DataLoader.color(palette, "fog_day", Color(0.8, 0.9, 1.0))
	env.fog_light_energy = 1.0
	env.fog_density = float(palette.get("fog_density", 0.004))
	env.fog_sky_affect = 0.15
	env.fog_aerial_perspective = 0.3

	# Couleurs un peu plus saturées, façon anime.
	env.adjustment_enabled = true
	env.adjustment_saturation = 1.12
	env.adjustment_contrast = 1.05
	env.adjustment_brightness = 1.0

	# Petites ombres de contact entre les objets (plus de relief).
	env.ssao_enabled = false

	return env
