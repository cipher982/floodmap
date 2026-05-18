import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const { Terrain3dMath, Mat4 } = require("./terrain-3d-math.js");
const { Terrain3dWorld } = require("./terrain-3d-world.js");
const { Terrain3dFloodPlayer } = require("./terrain-3d-flood-player.js");
const { Terrain3dMeshBuilder } = require("./terrain-3d-mesh.js");
const { Terrain3dShaders } = require("./terrain-3d-shaders.js");

test("terrain 3D tile bounds contain the requested point", () => {
  const lat = 33.5186;
  const lng = -86.8104;
  const tile = Terrain3dMath.lonLatToTile(lng, lat, 12);
  const [west, south, east, north] = Terrain3dMath.tileBounds(tile.x, tile.y, tile.z);

  assert.equal(tile.z, 12);
  assert.ok(tile.x >= 0);
  assert.ok(tile.y >= 0);
  assert.ok(west <= lng);
  assert.ok(east >= lng);
  assert.ok(south <= lat);
  assert.ok(north >= lat);
});

test("matrix multiply preserves identity transforms", () => {
  const translated = Mat4.translate(1, 2, 3);
  const multiplied = Mat4.multiply(Mat4.identity(), translated);

  assert.deepEqual(Array.from(multiplied), Array.from(translated));
});

test("terrain camera clamps pitch to a non-inverting orbit", () => {
  assert.equal(Terrain3dMath.clampTerrainPitch(-4), -1.35);
  assert.equal(Terrain3dMath.clampTerrainPitch(1), -0.28);
  assert.equal(Terrain3dMath.clampTerrainPitch(-1), -1);
});

test("terrain camera clamps yaw so the map cannot be spun upside down", () => {
  assert.equal(Terrain3dMath.clampTerrainYaw(-4), -0.65);
  assert.equal(Terrain3dMath.clampTerrainYaw(4), 0.65);
  assert.equal(Terrain3dMath.clampTerrainYaw(0.2), 0.2);
});

test("terrain camera keeps a world-up view while orbiting", () => {
  const view = Mat4.orbitView({
    pitch: -1.05,
    yaw: 0,
    distance: 5.4,
    targetY: -0.12
  });
  const target = multiplyVec4(view, [0, -0.12, 0, 1]);
  const up = multiplyVec4(view, [0, 0.88, 0, 1]);
  const north = multiplyVec4(view, [0, -0.12, 1, 1]);

  assert.ok(target[2] < 0);
  assert.ok(up[1] > target[1]);
  assert.ok(north[1] > target[1]);
});

test("shader bundle exposes terrain and water programs", () => {
  assert.match(Terrain3dShaders.terrainVertex, /#version 300 es/);
  assert.match(Terrain3dShaders.terrainFragment, /sampler2D u_map/);
  assert.match(Terrain3dShaders.waterVertex, /a_hand/);
  assert.match(Terrain3dShaders.waterVertex, /u_waterMeters/);
  assert.match(Terrain3dShaders.waterVertex, /a_flow/);
  assert.match(Terrain3dShaders.waterFragment, /wave/);
  assert.match(Terrain3dShaders.waterFragment, /v_flow/);
  assert.match(Terrain3dShaders.flowVertex, /gl_PointSize/);
  assert.match(Terrain3dShaders.flowFragment, /gl_PointCoord/);
  assert.match(Terrain3dShaders.flowRibbonVertex, /a_along/);
  assert.match(Terrain3dShaders.flowRibbonVertex, /u_waterMeters/);
  assert.match(Terrain3dShaders.flowRibbonVertex, /a_hand/);
  assert.match(Terrain3dShaders.flowRibbonFragment, /v_along/);
});

test("terrain world planner builds a centered tile grid", () => {
  const centerTile = { z: 12, x: 1060, y: 1642 };
  const world = Terrain3dWorld.buildGrid({ centerTile, radius: 1, tileScale: 1.38 });

  assert.equal(world.tiles.length, 9);
  assert.deepEqual(world.centerTile, centerTile);
  assert.equal(world.tiles[0].dx, -1);
  assert.equal(world.tiles[0].dy, -1);
  assert.equal(world.tiles[4].originX, 0);
  assert.ok(Math.abs(world.tiles[4].originZ) < 0.000001);
  assert.equal(Terrain3dWorld.tileKey(centerTile), "12/1060/1642");
});

test("terrain mesh keeps north at the top texture row", () => {
  const renderer = { decodeElevation: (value) => value };
  const terrainData = new Uint16Array(256 * 256);
  terrainData.fill(100);
  const mesh = Terrain3dMeshBuilder.buildTerrain({
    renderer,
    terrainData,
    meshSize: 2,
    exaggeration: 1,
    tileScale: 2
  });

  assert.equal(mesh.vertices[4], 0);
  assert.equal(mesh.vertices[20], 1);
  assert.ok(mesh.vertices[2] > 0);
  assert.ok(mesh.vertices[18] < 0);
});

test("terrain flood player animates water level through a smooth loop", () => {
  const values = [];
  let currentValue = 0;
  const player = new Terrain3dFloodPlayer({
    getValue: () => currentValue,
    setValue: (value) => {
      currentValue = value;
      values.push(value);
    },
    min: 0,
    max: 100,
    periodMs: 1000,
    minIntervalMs: 0
  });

  assert.equal(player.toggle(0), true);
  assert.equal(player.tick(0), true);
  assert.equal(player.tick(390), true);
  assert.equal(player.tick(780), true);
  assert.equal(player.tick(1000), true);
  assert.ok(values[0] <= 1);
  assert.ok(values[1] > values[0]);
  assert.ok(values[2] > 95);
  assert.ok(values[3] <= 1);

  assert.equal(player.toggle(1100), false);
  assert.equal(player.tick(1200), false);
});

test("terrain flood player starts playback from the current value", () => {
  const values = [];
  const player = new Terrain3dFloodPlayer({
    getValue: () => 50,
    setValue: (value) => values.push(value),
    min: 0,
    max: 100,
    periodMs: 1000,
    minIntervalMs: 0
  });

  player.play(2000);
  assert.equal(player.tick(2000), true);
  assert.ok(Math.abs(values[0] - 50) < 1);
  assert.ok(Terrain3dFloodPlayer.inverseSmoothstep(0.5) > 0.49);
});

test("terrain mesh builder returns stable grid geometry", () => {
  const renderer = { decodeElevation: (value) => value };
  const terrainData = new Uint16Array(256 * 256);
  terrainData.fill(100);
  terrainData[0] = 90;
  terrainData[1] = 110;
  const mesh = Terrain3dMeshBuilder.buildTerrain({
    renderer,
    terrainData,
    meshSize: 8,
    exaggeration: 1
  });

  assert.equal(mesh.vertices.length, 8 * 8 * 8);
  assert.equal(mesh.indices.length, 7 * 7 * 6);
  assert.equal(mesh.minElevationM, 90);
  assert.equal(mesh.maxElevationM, 110);
});

test("water mesh builder uses HAND as the initial wet threshold", () => {
  const renderer = { decodeHandHeight: (value) => (value === 65535 ? NaN : value / 10) };
  const handData = new Uint16Array(256 * 256);
  handData.fill(65535);
  handData[0] = 5;
  const terrainVertices = new Float32Array(4 * 4 * 8);
  for (let i = 0; i < 16; i += 1) {
    terrainVertices[i * 8] = i % 4;
    terrainVertices[i * 8 + 1] = 0.5;
    terrainVertices[i * 8 + 2] = Math.floor(i / 4);
  }

  const mesh = Terrain3dMeshBuilder.buildWater({
    renderer,
    handData,
    terrainVertices,
    meshSize: 4,
    waterMeters: 1
  });

  assert.equal(mesh.waterVisible, true);
  assert.equal(mesh.waterVertexRatio, 0.0625);
  assert.equal(mesh.vertices.length, 4 * 4 * 8);
  assert.ok(mesh.indices.length > 0);
});

test("water stats can update without rebuilding water geometry", () => {
  const renderer = { decodeHandHeight: (value) => (value === 65535 ? NaN : value / 10) };
  const handData = new Uint16Array(256 * 256);
  handData.fill(65535);
  handData[0] = 5;
  handData[255] = 20;

  const low = Terrain3dMeshBuilder.waterStats({
    renderer,
    handData,
    meshSize: 4,
    waterMeters: 1
  });
  const high = Terrain3dMeshBuilder.waterStats({
    renderer,
    handData,
    meshSize: 4,
    waterMeters: 3
  });

  assert.equal(low.waterVisible, true);
  assert.ok(high.waterVertexRatio > low.waterVertexRatio);
});

test("flow particle builder extracts moving drainage points", () => {
  const renderer = { decodeHandHeight: (value) => (value === 65535 ? NaN : value / 10) };
  const handData = new Uint16Array(256 * 256);
  handData.fill(120);
  for (let y = 0; y < 256; y += 1) {
    for (let x = 112; x <= 144; x += 1) {
      handData[y * 256 + x] = 2;
    }
  }
  const terrainVertices = new Float32Array(16 * 16 * 8);
  for (let i = 0; i < 16 * 16; i += 1) {
    terrainVertices[i * 8] = i % 16;
    terrainVertices[i * 8 + 1] = 0.2;
    terrainVertices[i * 8 + 2] = Math.floor(i / 16);
  }

  const particles = Terrain3dMeshBuilder.buildFlowParticles({
    renderer,
    handData,
    terrainVertices,
    meshSize: 16,
    waterMeters: 8
  });

  assert.ok(particles.particleCount > 0);
  assert.equal(particles.vertices.length, particles.particleCount * 7);
});

test("flow ribbon builder extracts directional drainage streaks", () => {
  const renderer = { decodeHandHeight: (value) => (value === 65535 ? NaN : value / 10) };
  const handData = new Uint16Array(256 * 256);
  handData.fill(120);
  for (let y = 0; y < 256; y += 1) {
    for (let x = 80; x <= 176; x += 1) {
      handData[y * 256 + x] = Math.abs(x - 128) / 10;
    }
  }
  const terrainVertices = new Float32Array(16 * 16 * 8);
  for (let i = 0; i < 16 * 16; i += 1) {
    terrainVertices[i * 8] = i % 16;
    terrainVertices[i * 8 + 1] = 0.2;
    terrainVertices[i * 8 + 2] = Math.floor(i / 16);
  }

  const ribbons = Terrain3dMeshBuilder.buildFlowRibbons({
    renderer,
    handData,
    terrainVertices,
    meshSize: 16,
    waterMeters: 14
  });

  assert.ok(ribbons.ribbonCount > 0);
  assert.equal(ribbons.vertexCount, ribbons.ribbonCount * 6);
  assert.equal(ribbons.vertices.length, ribbons.vertexCount * 9);
  assert.equal(ribbons.simulationModel, "cpu-virtual-pipes-hand64");
  assert.equal(ribbons.simulationCells, 64 * 64);
});

function multiplyVec4(matrix, vector) {
  const out = [];
  for (let row = 0; row < 4; row += 1) {
    out[row] =
      matrix[0 * 4 + row] * vector[0] +
      matrix[1 * 4 + row] * vector[1] +
      matrix[2 * 4 + row] * vector[2] +
      matrix[3 * 4 + row] * vector[3];
  }
  return out;
}
