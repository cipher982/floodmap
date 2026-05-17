/*
 * CPU mesh builders for the first 3D milestone. This is intentionally isolated
 * so the next water engine can replace it with a GPU simulation surface.
 */

class Terrain3dMeshBuilder {
  static buildTerrain({ renderer, terrainData, meshSize, exaggeration }) {
    const { minElevationM, maxElevationM } = Terrain3dMeshBuilder.elevationStats(
      renderer,
      terrainData
    );
    const n = meshSize;
    const vertices = new Float32Array(n * n * 8);
    const heights = new Float32Array(n * n);
    const elevationRange = Math.max(8, maxElevationM - minElevationM);
    for (let y = 0; y < n; y += 1) {
      for (let x = 0; x < n; x += 1) {
        const srcX = Math.min(255, Math.round(x / (n - 1) * 255));
        const srcY = Math.min(255, Math.round(y / (n - 1) * 255));
        const elevation = Terrain3dMeshBuilder.sampleElevation(
          renderer,
          terrainData,
          srcX,
          srcY,
          minElevationM
        );
        const height = ((elevation - minElevationM) / elevationRange - 0.42) * 0.72 * exaggeration;
        heights[y * n + x] = height;
      }
    }
    for (let y = 0; y < n; y += 1) {
      for (let x = 0; x < n; x += 1) {
        const i = y * n + x;
        const left = heights[y * n + Math.max(0, x - 1)];
        const right = heights[y * n + Math.min(n - 1, x + 1)];
        const up = heights[Math.max(0, y - 1) * n + x];
        const down = heights[Math.min(n - 1, y + 1) * n + x];
        const normal = Terrain3dMeshBuilder.normalize([left - right, 2.0 / n, up - down]);
        const o = i * 8;
        vertices[o] = (x / (n - 1) - 0.5) * 2.4;
        vertices[o + 1] = heights[i];
        vertices[o + 2] = (y / (n - 1) - 0.5) * -2.4;
        vertices[o + 3] = x / (n - 1);
        vertices[o + 4] = y / (n - 1);
        vertices[o + 5] = normal[0];
        vertices[o + 6] = normal[1];
        vertices[o + 7] = normal[2];
      }
    }
    return {
      vertices,
      indices: Terrain3dMeshBuilder.gridIndices(n),
      minElevationM,
      maxElevationM
    };
  }

  static buildWater({ renderer, handData, terrainVertices, meshSize, waterMeters }) {
    const n = meshSize;
    const vertices = new Float32Array(n * n * 6);
    const wet = new Uint8Array(n * n);
    let wetVertices = 0;
    for (let y = 0; y < n; y += 1) {
      for (let x = 0; x < n; x += 1) {
        const i = y * n + x;
        const srcX = Math.min(255, Math.round(x / (n - 1) * 255));
        const srcY = Math.min(255, Math.round(y / (n - 1) * 255));
        const hand = renderer.decodeHandHeight(handData[srcY * 256 + srcX]);
        const terrainO = i * 8;
        const depth = Number.isFinite(hand) ? Math.max(0, waterMeters - hand) : 0;
        const depthT = Math.min(1, depth / Math.max(1, waterMeters * 0.18));
        const isWet = depth > 0;
        if (isWet) wetVertices += 1;
        wet[i] = isWet ? 1 : 0;
        const o = i * 6;
        vertices[o] = terrainVertices[terrainO];
        vertices[o + 1] = terrainVertices[terrainO + 1] + 0.025 + depthT * 0.08;
        vertices[o + 2] = terrainVertices[terrainO + 2];
        vertices[o + 3] = x / (n - 1);
        vertices[o + 4] = y / (n - 1);
        vertices[o + 5] = depthT;
      }
    }
    const indices = [];
    for (let y = 0; y < n - 1; y += 1) {
      for (let x = 0; x < n - 1; x += 1) {
        const a = y * n + x;
        const b = a + 1;
        const c = a + n;
        const d = c + 1;
        if (wet[a] || wet[b] || wet[c] || wet[d]) {
          indices.push(a, c, b, b, c, d);
        }
      }
    }
    return {
      vertices,
      indices: new Uint32Array(indices),
      waterVisible: indices.length > 0,
      waterVertexRatio: Number((wetVertices / (n * n)).toFixed(4))
    };
  }

  static elevationStats(renderer, terrainData) {
    let min = Infinity;
    let max = -Infinity;
    for (const raw of terrainData) {
      const elevation = renderer.decodeElevation(raw);
      if (!Number.isFinite(elevation) || elevation < -1000) continue;
      min = Math.min(min, elevation);
      max = Math.max(max, elevation);
    }
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
      min = 0;
      max = 120;
    }
    return { minElevationM: min, maxElevationM: max };
  }

  static sampleElevation(renderer, terrainData, x, y, fallback) {
    const raw = terrainData[y * 256 + x];
    const elevation = renderer.decodeElevation(raw);
    if (!Number.isFinite(elevation) || elevation < -1000) return fallback;
    return elevation;
  }

  static gridIndices(n) {
    const indices = new Uint32Array((n - 1) * (n - 1) * 6);
    let o = 0;
    for (let y = 0; y < n - 1; y += 1) {
      for (let x = 0; x < n - 1; x += 1) {
        const a = y * n + x;
        const b = a + 1;
        const c = a + n;
        const d = c + 1;
        indices[o++] = a;
        indices[o++] = c;
        indices[o++] = b;
        indices[o++] = b;
        indices[o++] = c;
        indices[o++] = d;
      }
    }
    return indices;
  }

  static normalize(v) {
    const len = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / len, v[1] / len, v[2] / len];
  }
}

if (typeof window !== "undefined") {
  window.Terrain3dMeshBuilder = Terrain3dMeshBuilder;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dMeshBuilder };
}
