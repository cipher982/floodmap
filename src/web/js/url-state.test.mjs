import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  DEFAULT_VIEW_STATE,
  parseFloodmapUrlState,
  buildFloodmapShareUrl,
  stripFloodmapStateParams,
  isDefaultViewState,
} = require("./url-state.js");

test("parseFloodmapUrlState falls back to defaults without explicit state", () => {
  const state = parseFloodmapUrlState("https://drose.io/floodmap");

  assert.equal(state.lat, DEFAULT_VIEW_STATE.lat);
  assert.equal(state.lng, DEFAULT_VIEW_STATE.lng);
  assert.equal(state.zoom, DEFAULT_VIEW_STATE.zoom);
  assert.equal(state.view, DEFAULT_VIEW_STATE.view);
  assert.equal(state.water, DEFAULT_VIEW_STATE.water);
  assert.equal(state.hasExplicitState, false);
});

test("parseFloodmapUrlState normalizes and clamps invalid values", () => {
  const state = parseFloodmapUrlState(
    "https://drose.io/floodmap?lat=999&lng=-999&zoom=42&view=ocean&water=-2"
  );

  assert.ok(Math.abs(state.lat - 85.05113) < 0.00001);
  assert.equal(state.lng, -180);
  assert.equal(state.zoom, 11);
  assert.equal(state.view, DEFAULT_VIEW_STATE.view);
  assert.equal(state.water, DEFAULT_VIEW_STATE.water);
  assert.equal(state.hasExplicitState, true);
});

test("buildFloodmapShareUrl preserves unrelated params and formats state", () => {
  const url = buildFloodmapShareUrl("https://drose.io/floodmap?debug=1", {
    lat: 27.9449854,
    lng: -82.4583107,
    zoom: 8.456,
    view: "flood",
    water: 6.04,
  });

  const parsed = new URL(url);

  assert.equal(parsed.searchParams.get("debug"), "1");
  assert.equal(parsed.searchParams.get("lat"), "27.94499");
  assert.equal(parsed.searchParams.get("lng"), "-82.45831");
  assert.equal(parsed.searchParams.get("zoom"), "8.46");
  assert.equal(parsed.searchParams.get("view"), "flood");
  assert.equal(parsed.searchParams.get("water"), "6.0");
});

test("stripFloodmapStateParams removes only permalink keys", () => {
  const stripped = stripFloodmapStateParams(
    "https://drose.io/floodmap?debug=1&lat=27.95&lng=-82.46&zoom=8.00&view=elevation&water=1.0"
  );
  const parsed = new URL(stripped);

  assert.equal(parsed.searchParams.get("debug"), "1");
  assert.equal(parsed.searchParams.has("lat"), false);
  assert.equal(parsed.searchParams.has("lng"), false);
  assert.equal(parsed.searchParams.has("zoom"), false);
  assert.equal(parsed.searchParams.has("view"), false);
  assert.equal(parsed.searchParams.has("water"), false);
});

test("isDefaultViewState matches normalized defaults", () => {
  assert.equal(
    isDefaultViewState({
      lat: DEFAULT_VIEW_STATE.lat,
      lng: DEFAULT_VIEW_STATE.lng,
      zoom: DEFAULT_VIEW_STATE.zoom,
      view: DEFAULT_VIEW_STATE.view,
      water: DEFAULT_VIEW_STATE.water,
    }),
    true
  );

  assert.equal(
    isDefaultViewState({
      lat: DEFAULT_VIEW_STATE.lat,
      lng: DEFAULT_VIEW_STATE.lng,
      zoom: 9,
      view: DEFAULT_VIEW_STATE.view,
      water: DEFAULT_VIEW_STATE.water,
    }),
    false
  );
});
