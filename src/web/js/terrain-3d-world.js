/*
 * Tile-world planning helpers for the 3D FloodMap renderer.
 *
 * The renderer is intentionally not tied to one XYZ tile. A world plan is a
 * centered WebMercator tile grid, where every tile carries its local offset in
 * scene units. The drawing code can then load, cache, and render real terrain
 * tiles while keeping navigation math separate from WebGL details.
 */

const Terrain3dWorldMath = typeof Terrain3dMath !== "undefined"
  ? Terrain3dMath
  : require("./terrain-3d-math.js").Terrain3dMath;

class Terrain3dWorld {
  static tileKey(tile) {
    return `${tile.z}/${tile.x}/${tile.y}`;
  }

  static normalizeTile(tile) {
    const max = 2 ** tile.z;
    return {
      z: tile.z,
      x: ((tile.x % max) + max) % max,
      y: Terrain3dWorldMath.clamp(tile.y, 0, max - 1)
    };
  }

  static moveTile(tile, dx, dy) {
    return Terrain3dWorld.normalizeTile({
      z: tile.z,
      x: tile.x + dx,
      y: tile.y + dy
    });
  }

  static buildGrid({ centerTile, radius, tileScale }) {
    const normalizedCenter = Terrain3dWorld.normalizeTile(centerTile);
    const tiles = [];
    for (let dy = -radius; dy <= radius; dy += 1) {
      for (let dx = -radius; dx <= radius; dx += 1) {
        const tile = Terrain3dWorld.moveTile(normalizedCenter, dx, dy);
        tiles.push({
          ...tile,
          key: Terrain3dWorld.tileKey(tile),
          dx,
          dy,
          originX: dx * tileScale,
          originZ: dy * -tileScale,
          tileScale
        });
      }
    }
    return {
      centerTile: normalizedCenter,
      radius,
      tileScale,
      tiles
    };
  }
}

if (typeof window !== "undefined") {
  window.Terrain3dWorld = Terrain3dWorld;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dWorld };
}
