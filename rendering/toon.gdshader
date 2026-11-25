// Shader « toon » commun à tout le jeu.
// Ombres en 2 ou 3 niveaux bien tranchés (style dessin animé),
// teinte d'ombre colorée (jamais noire), petit reflet brillant et
// liseré lumineux sur les bords (« rim light »).
// Le contour noir est dessiné par une deuxième passe : voir outline.gdshader.
shader_type spatial;
render_mode cull_back, depth_draw_opaque;

group_uniforms couleur;
uniform vec4 albedo : source_color = vec4(1.0);
uniform sampler2D albedo_texture : source_color, filter_linear_mipmap, hint_default_white;
uniform bool use_texture = false;

group_uniforms ombres;
// 2 = lumière / ombre, 3 = lumière / mi-ombre / ombre
uniform int bands : hint_range(2, 3) = 3;
// Position des seuils entre les niveaux (dans la quantité de lumière reçue, de 0 à 1).
uniform float threshold_shadow : hint_range(0.0, 1.0) = 0.08;
uniform float threshold_mid : hint_range(0.0, 1.0) = 0.45;
// Douceur de la transition entre deux niveaux (0 = coupure nette).
uniform float band_softness : hint_range(0.0, 0.2) = 0.02;
// Couleur ajoutée dans les zones d'ombre (ombres colorées façon anime).
uniform vec4 shadow_tint : source_color = vec4(0.42, 0.36, 0.62, 1.0);
uniform float shadow_tint_strength : hint_range(0.0, 1.0) = 0.35;

group_uniforms reflets;
uniform float specular_strength : hint_range(0.0, 2.0) = 0.25;
uniform float specular_size : hint_range(0.0, 1.0) = 0.12;
uniform vec4 rim_color : source_color = vec4(1.0, 0.97, 0.9, 1.0);
uniform float rim_strength : hint_range(0.0, 2.0) = 0.35;
uniform float rim_width : hint_range(0.0, 1.0) = 0.28;

group_uniforms lueur;
uniform vec4 emission_color : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform float emission_energy : hint_range(0.0, 16.0) = 0.0;

float band_step(float edge, float value) {
	return smoothstep(edge - band_softness, edge + band_softness, value);
}

void fragment() {
	vec3 color = albedo.rgb;
	if (use_texture) {
		color *= texture(albedo_texture, UV).rgb;
	}
	ALBEDO = color;
	ROUGHNESS = 1.0;
	SPECULAR = 0.0;
	EMISSION = emission_color.rgb * emission_energy;
}

void light() {
	// Quantité de lumière reçue (0 à 1), ombres portées comprises.
	float ndl = clamp(dot(NORMAL, LIGHT), 0.0, 1.0);
	float received = ndl * ATTENUATION;

	// Découpage en niveaux nets.
	float level;
	if (bands <= 2) {
		level = band_step(threshold_shadow, received);
	} else {
		level = 0.5 * band_step(threshold_shadow, received) + 0.5 * band_step(threshold_mid, received);
	}

	DIFFUSE_LIGHT += LIGHT_COLOR / PI * level;

	// Teinte colorée dans l'ombre, seulement pour le soleil/la lune
	// (sinon chaque petite lampe ajouterait sa teinte).
	if (LIGHT_IS_DIRECTIONAL) {
		DIFFUSE_LIGHT += LIGHT_COLOR / PI * shadow_tint.rgb * shadow_tint_strength * (1.0 - level);
	}

	// Petit reflet brillant, lui aussi tranché.
	vec3 half_vector = normalize(LIGHT + VIEW);
	float spec = pow(clamp(dot(NORMAL, half_vector), 0.0, 1.0), 64.0);
	float spec_band = step(1.0 - specular_size * 0.2, spec) * level;
	SPECULAR_LIGHT += LIGHT_COLOR / PI * spec_band * specular_strength;

	// Liseré lumineux sur le bord des formes, côté éclairé.
	float fresnel = 1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0);
	float rim = band_step(1.0 - rim_width, fresnel) * level;
	SPECULAR_LIGHT += rim_color.rgb * LIGHT_COLOR / PI * rim * rim_strength;
}
