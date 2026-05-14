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

test("HAND coloring hides values above threshold and colors low drainage heights", () => {
  const renderer = new ElevationRenderer();

  assert.deepEqual(renderer.calculateHandColor(Number.NaN, 2), renderer.colors.TRANSPARENT);
  assert.deepEqual(renderer.calculateHandColor(3, 2), renderer.colors.TRANSPARENT);
  assert.deepEqual(renderer.calculateHandColor(0.4, 2), renderer.colors.FLOODED);
  assert.equal(renderer.calculateHandColor(1.2, 2)[3] > 0, true);
  assert.equal(renderer.calculateHandColor(4, 5)[3] > 0, true);
});
