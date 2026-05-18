/*
 * Small math helpers shared by the 3D terrain app and tests.
 */

const Terrain3dMath = {
  lonLatToTile(lon, lat, zoom) {
    const clippedLat = Math.max(-85.05112878, Math.min(85.05112878, lat));
    const scale = 2 ** zoom;
    const xFloat = ((lon + 180) / 360) * scale;
    const latRad = clippedLat * Math.PI / 180;
    const yFloat = (1 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2 * scale;
    return {
      z: zoom,
      x: Math.floor(xFloat),
      y: Math.floor(yFloat)
    };
  },

  tileToLonLat(x, y, zoom) {
    const scale = 2 ** zoom;
    const lon = x / scale * 360 - 180;
    const n = Math.PI - 2 * Math.PI * y / scale;
    const lat = 180 / Math.PI * Math.atan(Math.sinh(n));
    return [lon, lat];
  },

  tileBounds(x, y, zoom) {
    const nw = Terrain3dMath.tileToLonLat(x, y, zoom);
    const se = Terrain3dMath.tileToLonLat(x + 1, y + 1, zoom);
    return [nw[0], se[1], se[0], nw[1]];
  },

  clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  },

  clampTerrainPitch(value) {
    return Terrain3dMath.clamp(value, -1.35, -0.28);
  },

  clampTerrainYaw(value) {
    return Terrain3dMath.clamp(value, -0.65, 0.65);
  }
};

const Mat4 = {
  identity() {
    return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  },

  perspective(fovy, aspect, near, far) {
    const f = 1.0 / Math.tan(fovy / 2);
    const nf = 1 / (near - far);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, (2 * far * near) * nf, 0
    ]);
  },

  translate(x, y, z) {
    return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
  },

  rotateX(rad) {
    const c = Math.cos(rad);
    const s = Math.sin(rad);
    return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]);
  },

  rotateY(rad) {
    const c = Math.cos(rad);
    const s = Math.sin(rad);
    return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]);
  },

  rotateZ(rad) {
    const c = Math.cos(rad);
    const s = Math.sin(rad);
    return new Float32Array([c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  },

  lookAt(eye, target, up) {
    const z = Mat4.normalize([
      eye[0] - target[0],
      eye[1] - target[1],
      eye[2] - target[2]
    ]);
    const x = Mat4.normalize(Mat4.cross(up, z));
    const y = Mat4.cross(z, x);
    return new Float32Array([
      x[0], y[0], z[0], 0,
      x[1], y[1], z[1], 0,
      x[2], y[2], z[2], 0,
      -Mat4.dot(x, eye), -Mat4.dot(y, eye), -Mat4.dot(z, eye), 1
    ]);
  },

  orbitView({ pitch, yaw, distance, targetX = 0, targetY = 0, targetZ = 0 }) {
    const clampedPitch = Terrain3dMath.clampTerrainPitch(pitch);
    const clampedYaw = Terrain3dMath.clampTerrainYaw(yaw);
    const horizontalDistance = Math.cos(-clampedPitch) * distance;
    const eye = [
      targetX + Math.sin(clampedYaw) * horizontalDistance,
      targetY + Math.sin(-clampedPitch) * distance,
      targetZ - Math.cos(clampedYaw) * horizontalDistance
    ];
    return Mat4.lookAt(eye, [targetX, targetY, targetZ], [0, 1, 0]);
  },

  cross(a, b) {
    return [
      a[1] * b[2] - a[2] * b[1],
      a[2] * b[0] - a[0] * b[2],
      a[0] * b[1] - a[1] * b[0]
    ];
  },

  dot(a, b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  },

  normalize(v) {
    const length = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / length, v[1] / length, v[2] / length];
  },

  multiply(a, b) {
    const out = new Float32Array(16);
    for (let row = 0; row < 4; row += 1) {
      for (let col = 0; col < 4; col += 1) {
        out[col * 4 + row] =
          a[0 * 4 + row] * b[col * 4 + 0] +
          a[1 * 4 + row] * b[col * 4 + 1] +
          a[2 * 4 + row] * b[col * 4 + 2] +
          a[3 * 4 + row] * b[col * 4 + 3];
      }
    }
    return out;
  }
};

if (typeof window !== "undefined") {
  window.Terrain3dMath = Terrain3dMath;
  window.Mat4 = Mat4;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dMath, Mat4 };
}
