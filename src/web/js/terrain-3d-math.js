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
