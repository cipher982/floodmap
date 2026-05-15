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

test("HAND coloring uses a scaled ramp within the selected threshold", () => {
  const renderer = new ElevationRenderer();

  assert.deepEqual(renderer.calculateHandColor(Number.NaN, 2), renderer.colors.TRANSPARENT);
  assert.deepEqual(renderer.calculateHandColor(3, 2), renderer.colors.TRANSPARENT);

  const drainageFloor = renderer.calculateHandColor(0, 10);
  const lowTerrace = renderer.calculateHandColor(1, 10);
  const upperValley = renderer.calculateHandColor(8, 10);

  assert.deepEqual(drainageFloor, renderer.HAND_VIZ_STOPS[0].color);
  assert.equal(lowTerrace[3] > 0, true);
  assert.equal(upperValley[3] > 0, true);
  assert.notDeepEqual(lowTerrace, upperValley);
  assert.equal(upperValley[3] < drainageFloor[3], true);
});
