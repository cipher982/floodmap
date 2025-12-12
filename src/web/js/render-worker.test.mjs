import test from "node:test";
import assert from "node:assert/strict";

function packRgbaToU32(r, g, b, a) {
  return ((a & 255) << 24) | ((b & 255) << 16) | ((g & 255) << 8) | (r & 255);
}

test("worker LUT packing matches byte view", () => {
  const pixelData = new Uint8ClampedArray(4);
  const pixelU32 = new Uint32Array(pixelData.buffer);
  const rgba = [1, 2, 3, 4];

  pixelU32[0] = packRgbaToU32(...rgba);

  assert.equal(pixelData[0], 1);
  assert.equal(pixelData[1], 2);
  assert.equal(pixelData[2], 3);
  assert.equal(pixelData[3], 4);
});
