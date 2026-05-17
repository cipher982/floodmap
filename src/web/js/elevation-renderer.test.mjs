import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ElevationRenderer = require("./elevation-renderer.js");

test("HAND tiles decode uint16 decimeters separately from elevation", () => {
  const renderer = new ElevationRenderer();

  assert.equal(renderer.decodeHandHeight(0), 0);
  assert.equal(renderer.decodeHandHeight(17), 1.7);
  assert.equal(Number.isNaN(renderer.decodeHandHeight(renderer.NODATA_VALUE)), true);
});

test("HAND coloring uses apparent-depth blues within the selected threshold", () => {
  const renderer = new ElevationRenderer();

  assert.deepEqual(renderer.calculateHandColor(Number.NaN, 2), renderer.colors.TRANSPARENT);
  assert.deepEqual(renderer.calculateHandColor(3, 2), renderer.colors.TRANSPARENT);

  const floodEdge = renderer.calculateHandColor(10, 10);
  const shallowWater = renderer.calculateHandColor(9.8, 10);
  const deepWater = renderer.calculateHandColor(0, 10);

  assert.deepEqual(floodEdge, renderer.HAND_VIZ_STOPS[0].color);
  assert.equal(shallowWater[3] > 0, true);
  assert.equal(deepWater[3] > shallowWater[3], true);
  assert.equal(deepWater[2] < shallowWater[2], true);
});

test("HAND nodata debug color is opt-in", () => {
  const renderer = new ElevationRenderer();

  assert.deepEqual(
    renderer.calculateTileColor(renderer.NODATA_VALUE, "hand", 1000),
    renderer.colors.TRANSPARENT
  );
  assert.deepEqual(
    renderer.calculateTileColor(renderer.NODATA_VALUE, "hand", 1000, true),
    renderer.HAND_NODATA_RGBA
  );
});
