// Contour noir fin, technique de la « coque inversée » :
// on redessine l'objet un peu gonflé, en ne gardant que ses faces arrière.
// Ce qui dépasse derrière l'objet forme le trait.
// L'épaisseur est calculée en pixels à l'écran : le trait reste fin
// de près comme de loin.
shader_type spatial;
render_mode unshaded, cull_front, depth_draw_opaque, shadows_disabled;

uniform vec4 outline_color : source_color = vec4(0.06, 0.04, 0.1, 1.0);
// Épaisseur en pixels (pour une fenêtre de 720 pixels de haut).
uniform float outline_width : hint_range(0.0, 10.0) = 2.0;

void vertex() {
	vec4 clip = PROJECTION_MATRIX * (MODELVIEW_MATRIX * vec4(VERTEX, 1.0));
	vec3 view_normal = normalize(MODELVIEW_NORMAL_MATRIX * NORMAL);
	vec2 screen_dir = (PROJECTION_MATRIX * vec4(view_normal, 0.0)).xy;
	float len = length(screen_dir);
	if (len > 0.0001) {
		screen_dir /= len;
		float scale = VIEWPORT_SIZE.y / 720.0;
		vec2 pixel_offset = screen_dir * outline_width * scale * 2.0 / VIEWPORT_SIZE;
		clip.xy += pixel_offset * clip.w;
	}
	POSITION = clip;
}

void fragment() {
	ALBEDO = outline_color.rgb;
}
