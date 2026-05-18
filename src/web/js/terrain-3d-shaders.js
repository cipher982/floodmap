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
out vec3 v_world;
void main() {
  v_uv = a_uv;
  v_normal = a_normal;
  v_height = a_pos.y;
  v_world = a_pos;
  gl_Position = u_matrix * vec4(a_pos, 1.0);
}
`,

  terrainFragment: `#version 300 es
precision highp float;
uniform sampler2D u_map;
uniform vec3 u_light;
uniform vec3 u_fogColor;
in vec2 v_uv;
in vec3 v_normal;
in float v_height;
in vec3 v_world;
out vec4 fragColor;
void main() {
  vec3 base = texture(u_map, v_uv).rgb;
  float light = clamp(dot(normalize(v_normal), normalize(u_light)) * 0.34 + 0.72, 0.52, 1.08);
  float heightTint = smoothstep(-0.18, 0.42, v_height);
  vec3 color = base * light;
  color = mix(color, color + vec3(0.05, 0.045, 0.03), heightTint * 0.20);
  color = mix(color, vec3(0.72, 0.78, 0.84), smoothstep(0.58, 1.10, v_height) * 0.12);
  float edgeFog = smoothstep(0.94, 1.45, length(v_world.xz));
  color = mix(color, u_fogColor, edgeFog * 0.55);
  fragColor = vec4(color, 1.0);
}
`,

  waterVertex: `#version 300 es
precision highp float;
in vec3 a_pos;
in vec2 a_uv;
in float a_depth;
in vec2 a_flow;
uniform mat4 u_matrix;
out vec2 v_uv;
out float v_depth;
out vec2 v_flow;
void main() {
  v_uv = a_uv;
  v_depth = a_depth;
  v_flow = a_flow;
  gl_Position = u_matrix * vec4(a_pos, 1.0);
}
`,

  waterFragment: `#version 300 es
precision highp float;
uniform float u_time;
in vec2 v_uv;
in float v_depth;
in vec2 v_flow;
out vec4 fragColor;
float wave(vec2 p, float t) {
  float a = sin(p.x * 58.0 + p.y * 19.0 + t * 3.2);
  float b = sin(p.x * -31.0 + p.y * 47.0 - t * 4.1);
  float c = sin((p.x + p.y) * 82.0 + t * 2.4);
  return (a + 0.6 * b + 0.35 * c) / 1.95;
}
void main() {
  if (v_depth <= 0.001) discard;
  vec2 flow = normalize(v_flow + vec2(0.001, 0.0));
  vec2 across = vec2(-flow.y, flow.x);
  float along = dot(v_uv, flow);
  float cross = dot(v_uv, across);
  float w = wave(v_uv + flow * u_time * 0.045, u_time);
  float current = sin(along * 118.0 - u_time * 6.4 + sin(cross * 44.0) * 0.8) * 0.5 + 0.5;
  float stripe = smoothstep(0.62, 1.0, current);
  float foam = smoothstep(0.76, 1.0, stripe) * smoothstep(0.02, 0.22, v_depth);
  vec3 shallow = vec3(0.28, 0.74, 0.92);
  vec3 deep = vec3(0.03, 0.20, 0.55);
  vec3 color = mix(shallow, deep, clamp(v_depth, 0.0, 1.0));
  color = mix(color, vec3(0.86, 0.98, 1.0), foam * (0.20 + v_depth * 0.18));
  color += w * vec3(0.025, 0.06, 0.08);
  float alpha = clamp(0.28 + v_depth * 0.32 + foam * 0.12, 0.22, 0.74);
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
