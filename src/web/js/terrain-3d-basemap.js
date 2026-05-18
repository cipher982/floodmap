/*
 * Captures a matching MapLibre vector tile view into a canvas texture for the
 * 3D terrain mesh.
 */

class Terrain3dBasemapCapture {
  constructor({ container, tile }) {
    this.container = container;
    this.tile = tile;
    this.errors = [];
  }

  async capture() {
    const bounds = Terrain3dMath.tileBounds(this.tile.x, this.tile.y, this.tile.z);
    const map = new maplibregl.Map({
      container: this.container,
      preserveDrawingBuffer: true,
      interactive: false,
      attributionControl: false,
      style: this.style(),
      bounds: [[bounds[0], bounds[1]], [bounds[2], bounds[3]]],
      fitBoundsOptions: { padding: 0, duration: 0 },
      fadeDuration: 0
    });
    await new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error("Timed out rendering basemap texture")), 15000);
      map.once("idle", () => {
        window.clearTimeout(timeout);
        if (this.errors.length > 0) {
          reject(new Error(`Basemap texture rendered with errors: ${this.errors.join("; ")}`));
          return;
        }
        resolve();
      });
      map.once("error", (event) => {
        this.errors.push(event?.error?.message || "MapLibre basemap error");
      });
    });
    const sourceCanvas = map.getCanvas();
    const copy = document.createElement("canvas");
    copy.width = sourceCanvas.width;
    copy.height = sourceCanvas.height;
    const ctx = copy.getContext("2d");
    ctx.drawImage(sourceCanvas, 0, 0);
    map.remove();
    return copy;
  }

  style() {
    return {
      version: 8,
      sources: {
        "vector-tiles": {
          type: "vector",
          tiles: [window.floodmapApiUrl("/v1/tiles/vector/usa/{z}/{x}/{y}.pbf")],
          maxzoom: 11
        }
      },
      layers: [
        { id: "background", type: "background", paint: { "background-color": "#f2f0e9" } },
        {
          id: "landcover-wood",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "landcover",
          filter: ["==", ["get", "class"], "wood"],
          paint: { "fill-color": "rgba(155, 194, 149, 0.58)" }
        },
        {
          id: "landuse",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "landuse",
          paint: { "fill-color": "rgba(214, 211, 202, 0.28)" }
        },
        {
          id: "park",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "park",
          paint: { "fill-color": "rgba(158, 204, 150, 0.42)" }
        },
        {
          id: "water",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "water",
          paint: { "fill-color": "rgba(71, 143, 190, 0.78)" }
        },
        {
          id: "waterway",
          type: "line",
          source: "vector-tiles",
          "source-layer": "waterway",
          paint: { "line-color": "rgba(38, 126, 181, 0.88)", "line-width": 1.4 }
        },
        {
          id: "roads",
          type: "line",
          source: "vector-tiles",
          "source-layer": "transportation",
          paint: {
            "line-color": [
              "match",
              ["get", "class"],
              "motorway", "#6b7280",
              "trunk", "#777f89",
              "primary", "#8a929d",
              "secondary", "#a6adb6",
              "#c2c7cf"
            ],
            "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.6, 12, 2.2]
          }
        }
      ]
    };
  }
}

if (typeof window !== "undefined") {
  window.Terrain3dBasemapCapture = Terrain3dBasemapCapture;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dBasemapCapture };
}
