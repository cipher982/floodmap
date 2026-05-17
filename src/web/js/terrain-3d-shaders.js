/*
 * Shader sources for the 3D terrain milestone.
 */

const Terrain3dShaders = {
  terrainVertex: `#version 300 es
precision highp float;
in vec3 a_pos;
in vec2 a_uv;
in vec3 a_normal;
uniform mat4 u_matrix;
out vec2 v_uv;
out vec3 v_normal;
out float v_height;
void main() {
  v_uv = a_uv;
  v_normal = a_normal;
  v_height = a_pos.y;
  gl_Position = u_matrix * vec4(a_pos, 1.0);
}
`,

  terrainFragment: `#version 300 es
precision highp float;
uniform sampler2D u_map;
uniform vec3 u_light;
in vec2 v_uv;
in vec3 v_normal;
in float v_height;
out vec4 fragColor;
void main() {
  vec3 base = texture(u_map, v_uv).rgb;
  float light = clamp(dot(normalize(v_normal), normalize(u_light)) * 0.5 + 0.62, 0.36, 1.18);
  float heightTint = smoothstep(-0.18, 0.42, v_height);
  vec3 color = base * light;
  color = mix(color, color + vec3(0.06, 0.05, 0.025), heightTint * 0.25);
  fragColor = vec4(color, 1.0);
}
`,

  waterVertex: `#version 300 es
precision highp float;
in vec3 a_pos;
in vec2 a_uv;
in float a_depth;
uniform mat4 u_matrix;
out vec2 v_uv;
out float v_depth;
void main() {
  v_uv = a_uv;
  v_depth = a_depth;
  gl_Position = u_matrix * vec4(a_pos, 1.0);
}
`,

  waterFragment: `#version 300 es
precision highp float;
uniform float u_time;
in vec2 v_uv;
in float v_depth;
out vec4 fragColor;
float wave(vec2 p, float t) {
  float a = sin(p.x * 58.0 + p.y * 19.0 + t * 3.2);
  float b = sin(p.x * -31.0 + p.y * 47.0 - t * 4.1);
  float c = sin((p.x + p.y) * 82.0 + t * 2.4);
  return (a + 0.6 * b + 0.35 * c) / 1.95;
}
void main() {
  if (v_depth <= 0.001) discard;
  float w = wave(v_uv, u_time);
  float stripe = smoothstep(0.42, 1.0, sin(v_uv.x * 88.0 + v_uv.y * 42.0 - u_time * 5.8) * 0.5 + 0.5);
  vec3 shallow = vec3(0.20, 0.82, 0.96);
  vec3 deep = vec3(0.02, 0.18, 0.62);
  vec3 color = mix(shallow, deep, clamp(v_depth, 0.0, 1.0));
  color = mix(color, vec3(0.86, 0.98, 1.0), stripe * (0.16 + v_depth * 0.22));
  color += w * vec3(0.035, 0.08, 0.10);
  float alpha = clamp(0.42 + v_depth * 0.34 + stripe * 0.12, 0.34, 0.86);
  fragColor = vec4(color, alpha);
}
`
};

if (typeof window !== "undefined") {
  window.Terrain3dShaders = Terrain3dShaders;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dShaders };
}
