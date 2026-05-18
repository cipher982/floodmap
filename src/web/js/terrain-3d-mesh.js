/*
 * CPU mesh builders for the 3D terrain scene. Terrain geometry is static until
 * the camera tile or exaggeration changes. Water geometry is built as a HAND
 * surface once; the active flood level is a shader uniform.
 */

const Terrain3dFlowSimCpu = typeof FloodSimCpu !== "undefined"
  ? FloodSimCpu
  : (() => {
      try {
        return require("./flood-sim-core.js").FloodSimCpu;
      } catch {
        return null;
      }
    })();

class Terrain3dMeshBuilder {
  static buildTerrain({
    renderer,
    terrainData,
    meshSize,
    exaggeration,
    originX = 0,
    originZ = 0,
    tileScale = 2.4,
    minElevationM: providedMinElevationM = null,
    maxElevationM: providedMaxElevationM = null
  }) {
    const localStats = Terrain3dMeshBuilder.elevationStats(
      renderer,
      terrainData
    );
    const minElevationM = Number.isFinite(providedMinElevationM)
      ? providedMinElevationM
      : localStats.minElevationM;
    const maxElevationM = Number.isFinite(providedMaxElevationM)
      ? providedMaxElevationM
      : localStats.maxElevationM;
    const n = meshSize;
    const vertices = new Float32Array(n * n * 8);
    const heights = new Float32Array(n * n);
    const elevationRange = Math.max(8, maxElevationM - minElevationM);
    for (let y = 0; y < n; y += 1) {
      for (let x = 0; x < n; x += 1) {
        const srcX = x / (n - 1) * 255;
        const srcY = y / (n - 1) * 255;
        const elevation = Terrain3dMeshBuilder.sampleElevation(
          renderer,
          terrainData,
          srcX,
          srcY,
          minElevationM
        );
        const height = Terrain3dMeshBuilder.reliefHeight(
          elevation,
          minElevationM,
          elevationRange,
          exaggeration
        );
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
        const normal = Terrain3dMeshBuilder.normalize([left - right, 2.8 / n, up - down]);
        const o = i * 8;
        vertices[o] = originX + (x / (n - 1) - 0.5) * tileScale;
        vertices[o + 1] = heights[i];
        vertices[o + 2] = originZ + (y / (n - 1) - 0.5) * -tileScale;
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

  static buildWater({ renderer, handData, terrainVertices, meshSize, waterMeters, maxWaterMeters = 1000 }) {
    const n = meshSize;
    const vertices = new Float32Array(n * n * 8);
    const finite = new Uint8Array(n * n);
    let wetVertices = 0;
    const spillMeters = Math.max(0.6, Math.min(12, maxWaterMeters * 0.015));
    for (let y = 0; y < n; y += 1) {
      for (let x = 0; x < n; x += 1) {
        const i = y * n + x;
        const srcX = x / (n - 1) * 255;
        const srcY = y / (n - 1) * 255;
        const hand = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, srcY);
        const handLeft = Terrain3dMeshBuilder.sampleHand(renderer, handData, Math.max(0, srcX - 1.5), srcY);
        const handRight = Terrain3dMeshBuilder.sampleHand(renderer, handData, Math.min(255, srcX + 1.5), srcY);
        const handUp = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, Math.max(0, srcY - 1.5));
        const handDown = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, Math.min(255, srcY + 1.5));
        const flow = Terrain3dMeshBuilder.flowDirection(handLeft, handRight, handUp, handDown);
        const terrainO = i * 8;
        const isFiniteHand = Number.isFinite(hand);
        const depth = isFiniteHand ? Math.max(0, waterMeters - hand) : 0;
        const isWet = depth > 0;
        if (isWet) wetVertices += 1;
        finite[i] = isFiniteHand && hand <= maxWaterMeters + spillMeters ? 1 : 0;
        const o = i * 8;
        vertices[o] = terrainVertices[terrainO];
        vertices[o + 1] = terrainVertices[terrainO + 1];
        vertices[o + 2] = terrainVertices[terrainO + 2];
        vertices[o + 3] = x / (n - 1);
        vertices[o + 4] = y / (n - 1);
        vertices[o + 5] = isFiniteHand ? hand : -1;
        vertices[o + 6] = flow[0];
        vertices[o + 7] = flow[1];
      }
    }
    const indices = [];
    for (let y = 0; y < n - 1; y += 1) {
      for (let x = 0; x < n - 1; x += 1) {
        const a = y * n + x;
        const b = a + 1;
        const c = a + n;
        const d = c + 1;
        if (finite[a] || finite[b] || finite[c] || finite[d]) {
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

  static waterStats({ renderer, handData, meshSize, waterMeters }) {
    const n = meshSize;
    let wetVertices = 0;
    for (let y = 0; y < n; y += 1) {
      for (let x = 0; x < n; x += 1) {
        const srcX = x / (n - 1) * 255;
        const srcY = y / (n - 1) * 255;
        const hand = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, srcY);
        if (Number.isFinite(hand) && hand < waterMeters) wetVertices += 1;
      }
    }
    const waterVertexRatio = Number((wetVertices / (n * n)).toFixed(4));
    return {
      waterVisible: wetVertices > 0,
      waterVertexRatio
    };
  }

  static buildFlowParticles({ renderer, handData, terrainVertices, meshSize, waterMeters }) {
    const vertices = [];
    const step = Math.max(3, Math.floor(meshSize / 48));
    const channelMeters = Math.max(2.5, Math.min(12, waterMeters * 0.22));
    for (let y = 1; y < meshSize - 1; y += step) {
      for (let x = 1; x < meshSize - 1; x += step) {
        const srcX = x / (meshSize - 1) * 255;
        const srcY = y / (meshSize - 1) * 255;
        const hand = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, srcY);
        if (!Number.isFinite(hand) || hand > channelMeters) continue;
        const handLeft = Terrain3dMeshBuilder.sampleHand(renderer, handData, Math.max(0, srcX - 2), srcY);
        const handRight = Terrain3dMeshBuilder.sampleHand(renderer, handData, Math.min(255, srcX + 2), srcY);
        const handUp = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, Math.max(0, srcY - 2));
        const handDown = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, Math.min(255, srcY + 2));
        const flow = Terrain3dMeshBuilder.flowDirection(handLeft, handRight, handUp, handDown);
        const terrainO = (y * meshSize + x) * 8;
        const strength = Math.max(0.12, (1 - hand / channelMeters) ** 1.7);
        const phase = Terrain3dMeshBuilder.hash2(x, y);
        vertices.push(
          terrainVertices[terrainO],
          terrainVertices[terrainO + 1] + 0.055 + strength * 0.025,
          terrainVertices[terrainO + 2],
          flow[0],
          flow[1],
          phase,
          strength
        );
      }
    }
    return {
      vertices: new Float32Array(vertices),
      particleCount: vertices.length / 7
    };
  }

  static buildFlowRibbons({ renderer, handData, terrainVertices, meshSize, waterMeters }) {
    const vertices = [];
    const step = Math.max(6, Math.floor(meshSize / 30));
    const flowSeedMeters = Math.max(waterMeters, 36);
    const channelMeters = Math.max(3.5, Math.min(18, flowSeedMeters * 0.30));
    const maxSegments = Math.max(6, Math.min(14, Math.round(5 + flowSeedMeters / 12)));
    const pathStep = Math.max(2.8, meshSize / 52);
    const simulation = Terrain3dMeshBuilder.simulateHandFlow({
      renderer,
      handData,
      waterMeters: flowSeedMeters,
      channelMeters
    });
    for (let y = 2; y < meshSize - 2; y += step) {
      for (let x = 2; x < meshSize - 2; x += step) {
        const seed = Terrain3dMeshBuilder.flowSampleAt({
          renderer,
          handData,
          simulation,
          meshSize,
          x,
          y,
          channelMeters
        });
        if (!seed) continue;
        const phase = Terrain3dMeshBuilder.hash2(x + 41, y + 17);
        let px = x + (phase - 0.5) * step * 0.38;
        let py = y + (Terrain3dMeshBuilder.hash2(x + 9, y + 83) - 0.5) * step * 0.38;
        for (let segment = 0; segment < maxSegments; segment += 1) {
          const sample = Terrain3dMeshBuilder.flowSampleAt({
            renderer,
            handData,
            simulation,
            meshSize,
            x: px,
            y: py,
            channelMeters
          });
          if (!sample) break;
          const nextX = px + sample.flow[0] * pathStep;
          const nextY = py + sample.flow[1] * pathStep;
          if (
            nextX < 1 ||
            nextX > meshSize - 2 ||
            nextY < 1 ||
            nextY > meshSize - 2
          ) {
            break;
          }
          Terrain3dMeshBuilder.pushFlowSegment({
            vertices,
            terrainVertices,
            meshSize,
            x0: px,
            y0: py,
            x1: nextX,
            y1: nextY,
            flow: sample.flow,
            hand: sample.hand,
            strength: sample.strength,
            phase,
            along0: segment / maxSegments,
            along1: (segment + 1) / maxSegments
          });
          px = nextX;
          py = nextY;
        }
      }
    }
    return {
      vertices: new Float32Array(vertices),
      ribbonCount: vertices.length / (9 * 6),
      vertexCount: vertices.length / 9,
      simulationModel: simulation ? "cpu-virtual-pipes-hand64" : "hand-gradient-fallback",
      simulationCells: simulation ? simulation.width * simulation.height : 0
    };
  }

  static flowSampleAt({ renderer, handData, simulation, meshSize, x, y, channelMeters }) {
    const srcX = x / (meshSize - 1) * 255;
    const srcY = y / (meshSize - 1) * 255;
    const hand = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, srcY);
    if (!Number.isFinite(hand) || hand > channelMeters) return null;
    const handLeft = Terrain3dMeshBuilder.sampleHand(renderer, handData, Math.max(0, srcX - 2), srcY);
    const handRight = Terrain3dMeshBuilder.sampleHand(renderer, handData, Math.min(255, srcX + 2), srcY);
    const handUp = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, Math.max(0, srcY - 2));
    const handDown = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, Math.min(255, srcY + 2));
    const gradientFlow = Terrain3dMeshBuilder.flowDirection(handLeft, handRight, handUp, handDown);
    const simulatedFlow = Terrain3dMeshBuilder.sampleSimulatedFlow(
      simulation,
      x / (meshSize - 1),
      y / (meshSize - 1)
    );
    const flow = simulatedFlow.speed > 0.0004
      ? [simulatedFlow.x, simulatedFlow.y]
      : gradientFlow;
    const terrainStrength = (1 - hand / channelMeters) ** 1.45;
    const simStrength = Math.min(1, simulatedFlow.speed * 16);
    const strength = Math.max(0.10, terrainStrength * 0.70 + simStrength * 0.55);
    return { flow, hand, strength };
  }

  static pushFlowSegment({
    vertices,
    terrainVertices,
    meshSize,
    x0,
    y0,
    x1,
    y1,
    flow,
    hand,
    strength,
    phase,
    along0,
    along1
  }) {
    const start = Terrain3dMeshBuilder.sampleTerrainPosition(terrainVertices, meshSize, x0, y0);
    const end = Terrain3dMeshBuilder.sampleTerrainPosition(terrainVertices, meshSize, x1, y1);
    const dx = end[0] - start[0];
    const dz = end[2] - start[2];
    const len = Math.hypot(dx, dz) || 1;
    const ax = -dz / len;
    const az = dx / len;
    const width = 0.012 + strength * 0.026;
    const lift = 0.075 + strength * 0.030;
    const p0 = [start[0] - ax * width, start[1] + lift, start[2] - az * width, along0];
    const p1 = [end[0] - ax * width, end[1] + lift, end[2] - az * width, along1];
    const p2 = [start[0] + ax * width, start[1] + lift, start[2] + az * width, along0];
    const p3 = [end[0] + ax * width, end[1] + lift, end[2] + az * width, along1];
    for (const point of [p0, p1, p2, p2, p1, p3]) {
      vertices.push(
        point[0],
        point[1],
        point[2],
        flow[0],
        flow[1],
        phase,
        strength,
        point[3],
        hand
      );
    }
  }

  static simulateHandFlow({ renderer, handData, waterMeters, channelMeters }) {
    if (!Terrain3dFlowSimCpu || !Number.isFinite(waterMeters) || waterMeters <= 0) return null;
    const width = 64;
    const height = 64;
    const bed = new Float32Array(width * height);
    const water = new Float32Array(width * height);
    const fallbackBed = channelMeters * 2.5;
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const srcX = x / (width - 1) * 255;
        const srcY = y / (height - 1) * 255;
        const hand = Terrain3dMeshBuilder.sampleHand(renderer, handData, srcX, srcY);
        const i = y * width + x;
        bed[i] = Number.isFinite(hand) ? Math.min(fallbackBed, Math.max(0, hand)) : fallbackBed;
        if (Number.isFinite(hand) && hand <= channelMeters) {
          water[i] = Math.max(0, waterMeters - hand) * 0.030;
        }
      }
    }
    const sim = new Terrain3dFlowSimCpu({ width, height, bed, water, cellSize: 1 });
    sim.run(10, {
      dt: 0.22,
      conductance: 0.22,
      friction: 0.88,
      rainRate: waterMeters > 8 ? 0.004 : 0.0015
    });
    return sim;
  }

  static sampleSimulatedFlow(simulation, u, v) {
    if (!simulation) return { x: 0, y: 0, speed: 0 };
    const x = Math.max(0, Math.min(simulation.width - 1, Math.round(u * (simulation.width - 1))));
    const y = Math.max(0, Math.min(simulation.height - 1, Math.round(v * (simulation.height - 1))));
    const i = y * simulation.width + x;
    const vx = simulation.velocityX[i] || 0;
    const vy = simulation.velocityY[i] || 0;
    const speed = Math.hypot(vx, vy);
    if (!Number.isFinite(speed) || speed < 0.000001) return { x: 0, y: 0, speed: 0 };
    return { x: vx / speed, y: vy / speed, speed };
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
    const elevation = Terrain3dMeshBuilder.bilinearSample(terrainData, x, y, (value) =>
      renderer.decodeElevation(value)
    );
    if (!Number.isFinite(elevation) || elevation < -1000) return fallback;
    return elevation;
  }

  static sampleHand(renderer, handData, x, y) {
    return Terrain3dMeshBuilder.bilinearSample(handData, x, y, (value) =>
      renderer.decodeHandHeight(value)
    );
  }

  static sampleTerrainPosition(terrainVertices, meshSize, x, y) {
    const x0 = Math.max(0, Math.min(meshSize - 1, Math.floor(x)));
    const y0 = Math.max(0, Math.min(meshSize - 1, Math.floor(y)));
    const x1 = Math.min(meshSize - 1, x0 + 1);
    const y1 = Math.min(meshSize - 1, y0 + 1);
    const tx = x - x0;
    const ty = y - y0;
    const sample = (sx, sy) => {
      const o = (sy * meshSize + sx) * 8;
      return [terrainVertices[o], terrainVertices[o + 1], terrainVertices[o + 2]];
    };
    const a = sample(x0, y0);
    const b = sample(x1, y0);
    const c = sample(x0, y1);
    const d = sample(x1, y1);
    const top = [
      a[0] * (1 - tx) + b[0] * tx,
      a[1] * (1 - tx) + b[1] * tx,
      a[2] * (1 - tx) + b[2] * tx
    ];
    const bottom = [
      c[0] * (1 - tx) + d[0] * tx,
      c[1] * (1 - tx) + d[1] * tx,
      c[2] * (1 - tx) + d[2] * tx
    ];
    return [
      top[0] * (1 - ty) + bottom[0] * ty,
      top[1] * (1 - ty) + bottom[1] * ty,
      top[2] * (1 - ty) + bottom[2] * ty
    ];
  }

  static bilinearSample(values, x, y, decode) {
    const x0 = Math.max(0, Math.min(255, Math.floor(x)));
    const y0 = Math.max(0, Math.min(255, Math.floor(y)));
    const x1 = Math.min(255, x0 + 1);
    const y1 = Math.min(255, y0 + 1);
    const tx = x - x0;
    const ty = y - y0;
    const samples = [
      [decode(values[y0 * 256 + x0]), (1 - tx) * (1 - ty)],
      [decode(values[y0 * 256 + x1]), tx * (1 - ty)],
      [decode(values[y1 * 256 + x0]), (1 - tx) * ty],
      [decode(values[y1 * 256 + x1]), tx * ty]
    ];
    let sum = 0;
    let weight = 0;
    for (const [value, w] of samples) {
      if (Number.isFinite(value)) {
        sum += value * w;
        weight += w;
      }
    }
    return weight > 0 ? sum / weight : NaN;
  }

  static reliefHeight(elevation, minElevationM, elevationRange, exaggeration) {
    const t = Terrain3dMeshBuilder.smoothstep(
      0,
      1,
      (elevation - minElevationM) / elevationRange
    );
    return (t - 0.42) * 0.58 * exaggeration;
  }

  static smoothstep(edge0, edge1, x) {
    const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
    return t * t * (3 - 2 * t);
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

  static flowDirection(left, right, up, down) {
    const dx = Terrain3dMeshBuilder.safeDelta(left, right);
    const dy = Terrain3dMeshBuilder.safeDelta(up, down);
    const x = -dx;
    const y = -dy;
    const len = Math.hypot(x, y);
    if (!Number.isFinite(len) || len < 0.0001) return [0.72, 0.36];
    return [x / len, y / len];
  }

  static safeDelta(a, b) {
    if (!Number.isFinite(a) || !Number.isFinite(b)) return 0;
    return b - a;
  }

  static hash2(x, y) {
    const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
    return s - Math.floor(s);
  }
}

if (typeof window !== "undefined") {
  window.Terrain3dMeshBuilder = Terrain3dMeshBuilder;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dMeshBuilder };
}
