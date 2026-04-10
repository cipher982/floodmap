import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  calculateDistanceKm,
  getViewportPrefetchTiles,
  buildProgressiveJumpPlan,
} = require("./jump-planner.js");

test("calculateDistanceKm is near zero for the same point", () => {
  const distance = calculateDistanceKm(
    { lat: 40.7128, lng: -74.006 },
    { lat: 40.7128, lng: -74.006 },
  );

  assert.ok(distance < 0.001);
});

test("buildProgressiveJumpPlan enables staging for cross-country jumps", () => {
  const plan = buildProgressiveJumpPlan({
    currentCenter: { lat: 40.7128, lng: -74.006 },
    currentZoom: 10.1,
    targetCenter: { lat: 47.6062, lng: -122.3321 },
    targetZoom: 10.2,
    viewportWidth: 924,
    viewportHeight: 586,
  });

  assert.equal(plan.useProgressive, true);
  assert.equal(plan.stageZoom, 7);
  assert.equal(plan.requiresFinalRefine, true);
  assert.ok(plan.distanceKm > 3000);
  assert.ok(plan.prefetchTiles.length > 0);
  assert.ok(plan.prefetchTiles.every((tile) => tile.z === 7));
});

test("buildProgressiveJumpPlan skips staging for nearby city changes", () => {
  const plan = buildProgressiveJumpPlan({
    currentCenter: { lat: 27.9506, lng: -82.4572 },
    currentZoom: 10.4,
    targetCenter: { lat: 28.5383, lng: -81.3792 },
    targetZoom: 10.5,
    viewportWidth: 924,
    viewportHeight: 586,
  });

  assert.equal(plan.useProgressive, false);
  assert.equal(plan.prefetchTiles.length, 0);
});

test("getViewportPrefetchTiles returns center-first tiles within the viewport cover", () => {
  const tiles = getViewportPrefetchTiles({
    center: { lat: 32.3668, lng: -86.3 },
    zoom: 6,
    viewportWidth: 924,
    viewportHeight: 586,
  });

  assert.ok(tiles.length >= 6);
  assert.ok(tiles.length <= 24);
  assert.deepEqual(tiles[0], { z: 6, x: 17, y: 26 });
  assert.ok(
    tiles.every(
      (tile) =>
        Number.isInteger(tile.z)
        && Number.isInteger(tile.x)
        && Number.isInteger(tile.y),
    ),
  );
});
