// Ciel stylisé : dégradé en bandes douces, soleil et lune en disques nets,
// étoiles la nuit et nuages simples.
// Les couleurs sont pilotées par le cycle jour/nuit (core/day_night.gd)
// à partir de la palette de la région.
shader_type sky;

uniform vec3 top_color : source_color = vec3(0.25, 0.55, 0.95);
uniform vec3 horizon_color : source_color = vec3(0.75, 0.88, 1.0);
uniform vec3 ground_color : source_color = vec3(0.45, 0.55, 0.5);
uniform vec3 sun_color : source_color = vec3(1.0, 0.95, 0.8);
uniform vec3 moon_color : source_color = vec3(0.85, 0.9, 1.0);
uniform vec3 cloud_color : source_color = vec3(1.0, 1.0, 1.0);
uniform vec3 cloud_shadow_color : source_color = vec3(0.75, 0.78, 0.92);
// Direction VERS le soleil (la lune est à l'opposé).
uniform vec3 sun_direction = vec3(0.0, 1.0, 0.0);
uniform float sun_size : hint_range(0.0, 0.2) = 0.045;
uniform float moon_size : hint_range(0.0, 0.2) = 0.03;
// 0 = nuit noire, 1 = plein jour.
uniform float day_amount : hint_range(0.0, 1.0) = 1.0;
uniform float star_density : hint_range(0.0, 1.0) = 0.5;
uniform float cloud_coverage : hint_range(0.0, 1.0) = 0.45;
uniform float cloud_speed = 0.004;

float hash(vec2 p) {
	return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	vec2 u = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
			mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}

float fbm(vec2 p) {
	float v = 0.0;
	float a = 0.5;
	for (int i = 0; i < 4; i++) {
		v += a * noise(p);
		p *= 2.03;
		a *= 0.5;
	}
	return v;
}

void sky() {
	vec3 dir = normalize(EYEDIR);
	float h = dir.y;

	// Dégradé en 3 bandes adoucies (look peint, pas réaliste).
	float t = clamp(h, 0.0, 1.0);
	float banded = smoothstep(0.0, 0.12, t) * 0.4 + smoothstep(0.12, 0.45, t) * 0.6;
	vec3 col = mix(horizon_color, top_color, banded);
	if (h < 0.0) {
		col = mix(horizon_color, ground_color, smoothstep(0.0, 0.08, -h));
	}

	vec3 sun_dir = normalize(sun_direction);

	// Halo autour du soleil.
	float sun_dot = dot(dir, sun_dir);
	col += sun_color * pow(max(sun_dot, 0.0), 24.0) * 0.35 * day_amount;

	// Disque du soleil (net) : valeur > 1 pour déclencher le bloom.
	float sun_disc = smoothstep(1.0 - sun_size * 0.02 - 0.0004, 1.0 - sun_size * 0.02, sun_dot);
	col = mix(col, sun_color * 4.0, sun_disc);

	// Lune à l'opposé du soleil.
	float moon_dot = dot(dir, -sun_dir);
	float moon_disc = smoothstep(1.0 - moon_size * 0.02 - 0.0004, 1.0 - moon_size * 0.02, moon_dot);
	col = mix(col, moon_color * 2.0, moon_disc * (1.0 - day_amount));

	// Étoiles, seulement la nuit et en haut du ciel.
	if (h > 0.0) {
		vec2 star_uv = dir.xz / (dir.y + 0.3) * 120.0;
		vec2 cell = floor(star_uv);
		float s = hash(cell);
		float star = step(1.0 - star_density * 0.03, s);
		float twinkle = 0.6 + 0.4 * sin(TIME * 2.0 + s * 100.0);
		col += vec3(1.0, 0.95, 0.85) * star * twinkle * (1.0 - day_amount) * smoothstep(0.05, 0.3, h) * 1.5;
	}

	// Nuages stylisés : bords nets, ombre en dessous.
	if (h > 0.02) {
		vec2 cloud_uv = dir.xz / (dir.y + 0.15) * 1.6 + vec2(TIME * cloud_speed, 0.0);
		float n = fbm(cloud_uv);
		float edge = 1.0 - cloud_coverage;
		float cloud = smoothstep(edge, edge + 0.03, n);
		float cloud_shade = smoothstep(edge + 0.05, edge + 0.15, n);
		vec3 lit_cloud = mix(cloud_shadow_color, cloud_color, cloud_shade);
		lit_cloud *= mix(0.25, 1.0, day_amount);
		col = mix(col, lit_cloud, cloud * smoothstep(0.02, 0.15, h) * 0.9);
	}

	COLOR = col;
}
