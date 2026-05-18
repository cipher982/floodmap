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
  base = clamp(base * 0.92 + vec3(0.035, 0.040, 0.046), 0.0, 1.0);
  float ink = 1.0 - smoothstep(0.18, 0.58, dot(base, vec3(0.299, 0.587, 0.114)));
  float light = clamp(dot(normalize(v_normal), normalize(u_light)) * 0.42 + 0.74, 0.50, 1.03);
  float heightTint = smoothstep(-0.18, 0.42, v_height);
  vec3 color = base * light;
  color = mix(color, base * 0.62, ink * 0.58);
  color = mix(color, color + vec3(0.018, 0.022, 0.012), heightTint * 0.08);
  color = mix(color, vec3(0.64, 0.70, 0.75), smoothstep(0.66, 1.12, v_height) * 0.035);
  float edgeFog = smoothstep(0.94, 1.45, length(v_world.xz));
  color = mix(color, u_fogColor, edgeFog * 0.30);
  fragColor = vec4(color, 1.0);
}
`,

  waterVertex: `#version 300 es
precision highp float;
in vec3 a_pos;
in vec2 a_uv;
in float a_hand;
in vec2 a_flow;
uniform mat4 u_matrix;
uniform float u_waterMeters;
out vec2 v_uv;
out float v_depth;
out vec2 v_flow;
void main() {
  float depth = a_hand >= 0.0 ? max(0.0, u_waterMeters - a_hand) : 0.0;
  float spillMeters = max(0.6, min(12.0, u_waterMeters * 0.08));
  float spillDepth = a_hand >= 0.0 ? max(0.0, 1.0 - max(0.0, a_hand - u_waterMeters) / spillMeters) * 0.18 : 0.0;
  float depthT = depth > 0.0 ? min(1.0, depth / max(1.0, u_waterMeters * 0.18)) : spillDepth;
  vec3 pos = a_pos;
  pos.y += 0.018 + depthT * 0.035;
  v_uv = a_uv;
  v_depth = depthT;
  v_flow = a_flow;
  gl_Position = u_matrix * vec4(pos, 1.0);
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
  float foam = smoothstep(0.82, 1.0, stripe) * smoothstep(0.06, 0.30, v_depth);
  vec3 shallow = vec3(0.05, 0.58, 0.95);
  vec3 deep = vec3(0.01, 0.12, 0.52);
  vec3 color = mix(shallow, deep, clamp(v_depth, 0.0, 1.0));
  color = mix(color, vec3(0.72, 0.94, 1.0), foam * (0.18 + v_depth * 0.16));
  color += w * vec3(0.024, 0.060, 0.095);
  float alpha = clamp(0.30 + v_depth * 0.34 + foam * 0.10, 0.24, 0.74);
  fragColor = vec4(color, alpha);
}
`,

  flowVertex: `#version 300 es
precision highp float;
in vec3 a_pos;
in vec2 a_flow;
in float a_phase;
in float a_strength;
uniform mat4 u_matrix;
uniform float u_time;
out float v_strength;
out float v_phase;
void main() {
  vec2 flow = normalize(a_flow + vec2(0.001, 0.0));
  float pulse = fract(a_phase + u_time * (0.18 + a_strength * 0.28));
  vec3 pos = a_pos;
  pos.x += flow.x * (pulse - 0.5) * 0.055;
  pos.z -= flow.y * (pulse - 0.5) * 0.055;
  pos.y += sin((pulse + a_phase) * 6.28318) * 0.012;
  v_strength = a_strength;
  v_phase = pulse;
  gl_Position = u_matrix * vec4(pos, 1.0);
  gl_PointSize = 3.2 + a_strength * 10.0;
}
`,

  flowFragment: `#version 300 es
precision highp float;
in float v_strength;
in float v_phase;
out vec4 fragColor;
void main() {
  vec2 p = gl_PointCoord - vec2(0.5);
  float d = length(p);
  if (d > 0.5) discard;
  float core = smoothstep(0.5, 0.08, d);
  float tail = smoothstep(0.96, 0.18, v_phase);
  vec3 color = mix(vec3(0.02, 0.50, 1.0), vec3(0.88, 0.99, 1.0), core);
  float alpha = core * tail * (0.36 + v_strength * 0.72);
  fragColor = vec4(color, alpha);
}
`,

  flowRibbonVertex: `#version 300 es
precision highp float;
in vec3 a_pos;
in vec2 a_flow;
in float a_phase;
in float a_strength;
in float a_along;
in float a_hand;
uniform mat4 u_matrix;
uniform float u_waterMeters;
out vec2 v_flow;
out float v_phase;
out float v_strength;
out float v_along;
out float v_visibility;
void main() {
  v_flow = a_flow;
  v_phase = a_phase;
  v_strength = a_strength;
  v_along = a_along;
  float spillMeters = max(0.8, min(14.0, u_waterMeters * 0.10));
  v_visibility = a_hand >= 0.0 ? smoothstep(a_hand - 0.5, a_hand + spillMeters, u_waterMeters) : 0.0;
  gl_Position = u_matrix * vec4(a_pos, 1.0);
}
`,

  flowRibbonFragment: `#version 300 es
precision highp float;
uniform float u_time;
in vec2 v_flow;
in float v_phase;
in float v_strength;
in float v_along;
in float v_visibility;
out vec4 fragColor;
void main() {
  if (v_visibility <= 0.005) discard;
  float speed = 0.32 + v_strength * 0.58;
  float pulse = fract(v_along * 2.4 - u_time * speed + v_phase);
  float dash = smoothstep(0.02, 0.20, pulse) * (1.0 - smoothstep(0.46, 0.96, pulse));
  float body = smoothstep(0.0, 0.12, v_along) * (1.0 - smoothstep(0.88, 1.0, v_along));
  float glint = smoothstep(0.60, 1.0, dash) * (0.35 + v_strength * 0.65);
  vec3 base = mix(vec3(0.02, 0.42, 0.95), vec3(0.70, 0.96, 1.0), glint);
  float alpha = body * dash * (0.16 + v_strength * 0.48) * v_visibility;
  fragColor = vec4(base, alpha);
}
`
};

if (typeof window !== "undefined") {
  window.Terrain3dShaders = Terrain3dShaders;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dShaders };
}
