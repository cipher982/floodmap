import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const { Terrain3dMath, Mat4 } = require("./terrain-3d-math.js");
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

test("shader bundle exposes terrain and water programs", () => {
  assert.match(Terrain3dShaders.terrainVertex, /#version 300 es/);
  assert.match(Terrain3dShaders.terrainFragment, /sampler2D u_map/);
  assert.match(Terrain3dShaders.waterVertex, /a_depth/);
  assert.match(Terrain3dShaders.waterFragment, /wave/);
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
