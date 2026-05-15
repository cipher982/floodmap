import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const FloodmapHandGpuLayer = require("./hand-gpu-layer.js");

test("HAND GPU layer maps XYZ tiles to normalized mercator bounds", () => {
  const layer = new FloodmapHandGpuLayer({ client: null, renderer: null });

  assert.deepEqual(layer.tileBounds({ z: 2, x: 1, y: 2 }), {
    x0: 0.25,
    y0: 0.5,
    x1: 0.5,
    y1: 0.75
  });
});

test("HAND GPU layer wraps horizontal tile coordinates", () => {
  const layer = new FloodmapHandGpuLayer({ client: null, renderer: null });

  assert.deepEqual(layer.tileBounds({ z: 3, x: 9, y: 1 }), {
    x0: 0.125,
    y0: 0.125,
    x1: 0.25,
    y1: 0.25
  });
});

test("HAND GPU tile upload forces raw row order and restores unpack state", () => {
  const gl = createUploadGlStub();
  const layer = new FloodmapHandGpuLayer({ client: null, renderer: null });
  layer.gl = gl;

  const tile = {
    data: new Uint16Array(256 * 256),
    texture: null,
    state: "loaded"
  };

  layer.uploadTile(tile);

  assert.equal(gl.texImageState.flipY, false);
  assert.equal(gl.texImageState.premultiplyAlpha, false);
  assert.equal(gl.getParameter(gl.UNPACK_FLIP_Y_WEBGL), true);
  assert.equal(gl.getParameter(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL), true);
  assert.equal(tile.state, "ready");
  assert.ok(tile.texture);
});

test("HAND GPU eviction drops stale tile entries", () => {
  const deleted = [];
  const layer = new FloodmapHandGpuLayer({ client: null, renderer: null, maxTextures: 1 });
  layer.gl = {
    deleteTexture(texture) {
      deleted.push(texture);
    }
  };
  layer.tiles.set("old", { key: "old", texture: { id: "old" }, lastUsed: 1 });
  layer.tiles.set("new", { key: "new", texture: { id: "new" }, lastUsed: 2 });

  layer.evictTextures();

  assert.equal(layer.tiles.has("old"), false);
  assert.equal(layer.tiles.has("new"), true);
  assert.deepEqual(deleted, [{ id: "old" }]);
});

test("HAND GPU aborted tile load removes pending tile without throwing", async () => {
  const layer = new FloodmapHandGpuLayer({
    client: null,
    renderer: {
      loadTerrainTile() {
        return Promise.reject(new DOMException("Aborted", "AbortError"));
      }
    }
  });

  const result = await layer.requestTile(12, 1061, 1642);

  assert.equal(result, null);
  assert.equal(layer.tiles.has("12/1061/1642"), false);
  assert.equal(layer.stats.tileLoadErrors, 0);
});

function createUploadGlStub() {
  const state = new Map();
  const gl = {
    ACTIVE_TEXTURE: "ACTIVE_TEXTURE",
    TEXTURE0: "TEXTURE0",
    TEXTURE_2D: "TEXTURE_2D",
    TEXTURE_BINDING_2D: "TEXTURE_BINDING_2D",
    UNPACK_ALIGNMENT: "UNPACK_ALIGNMENT",
    UNPACK_FLIP_Y_WEBGL: "UNPACK_FLIP_Y_WEBGL",
    UNPACK_PREMULTIPLY_ALPHA_WEBGL: "UNPACK_PREMULTIPLY_ALPHA_WEBGL",
    TEXTURE_MIN_FILTER: "TEXTURE_MIN_FILTER",
    TEXTURE_MAG_FILTER: "TEXTURE_MAG_FILTER",
    TEXTURE_WRAP_S: "TEXTURE_WRAP_S",
    TEXTURE_WRAP_T: "TEXTURE_WRAP_T",
    NEAREST: "NEAREST",
    CLAMP_TO_EDGE: "CLAMP_TO_EDGE",
    R16UI: "R16UI",
    RED_INTEGER: "RED_INTEGER",
    UNSIGNED_SHORT: "UNSIGNED_SHORT",
    texImageState: null,
    getParameter(name) {
      return state.get(name);
    },
    activeTexture(texture) {
      state.set(this.ACTIVE_TEXTURE, texture);
    },
    createTexture() {
      return { id: "created" };
    },
    bindTexture(target, texture) {
      assert.equal(target, this.TEXTURE_2D);
      state.set(this.TEXTURE_BINDING_2D, texture);
    },
    pixelStorei(name, value) {
      state.set(name, value);
    },
    texParameteri() {},
    texImage2D() {
      this.texImageState = {
        flipY: state.get(this.UNPACK_FLIP_Y_WEBGL),
        premultiplyAlpha: state.get(this.UNPACK_PREMULTIPLY_ALPHA_WEBGL)
      };
    }
  };
  state.set(gl.ACTIVE_TEXTURE, gl.TEXTURE0);
  state.set(gl.TEXTURE_BINDING_2D, { id: "previous" });
  state.set(gl.UNPACK_ALIGNMENT, 4);
  state.set(gl.UNPACK_FLIP_Y_WEBGL, true);
  state.set(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  return gl;
}
