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
      glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      sources: {
        "vector-tiles": {
          type: "vector",
          tiles: [window.floodmapApiUrl("/v1/tiles/vector/usa/{z}/{x}/{y}.pbf")],
          maxzoom: 11
        }
      },
      layers: [
        { id: "background", type: "background", paint: { "background-color": "#eef2e8" } },
        {
          id: "landcover-wood",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "landcover",
          filter: ["==", ["get", "class"], "wood"],
          paint: { "fill-color": "rgba(113, 165, 112, 0.66)" }
        },
        {
          id: "landuse",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "landuse",
          paint: { "fill-color": "rgba(205, 203, 194, 0.32)" }
        },
        {
          id: "park",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "park",
          paint: { "fill-color": "rgba(130, 194, 128, 0.48)" }
        },
        {
          id: "water",
          type: "fill",
          source: "vector-tiles",
          "source-layer": "water",
          paint: { "fill-color": "rgba(42, 137, 202, 0.88)" }
        },
        {
          id: "waterway",
          type: "line",
          source: "vector-tiles",
          "source-layer": "waterway",
          paint: { "line-color": "rgba(26, 118, 190, 0.95)", "line-width": 2.2 }
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
              "motorway", "#4b5563",
              "trunk", "#5f6875",
              "primary", "#747d8a",
              "secondary", "#9099a6",
              "#adb4be"
            ],
            "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.9, 12, 3.0]
          }
        },
        {
          id: "waterway-labels",
          type: "symbol",
          source: "vector-tiles",
          "source-layer": "waterway",
          minzoom: 10,
          filter: ["has", "name"],
          layout: {
            "symbol-placement": "line",
            "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
            "text-font": ["Noto Sans Regular"],
            "text-size": 15,
            "text-letter-spacing": 0,
            "text-rotation-alignment": "map"
          },
          paint: {
            "text-color": "#0369a1",
            "text-halo-color": "rgba(255, 255, 255, 0.96)",
            "text-halo-width": 2.0
          }
        },
        {
          id: "road-labels",
          type: "symbol",
          source: "vector-tiles",
          "source-layer": "transportation_name",
          minzoom: 10,
          filter: ["any", ["has", "name"], ["has", "ref"]],
          layout: {
            "symbol-placement": "line",
            "text-field": ["coalesce", ["get", "name:en"], ["get", "name"], ["get", "ref"]],
            "text-font": ["Noto Sans Regular"],
            "text-size": ["match", ["get", "class"], ["motorway", "trunk"], 14, ["primary", "secondary"], 12, 10],
            "text-letter-spacing": 0,
            "text-rotation-alignment": "map"
          },
          paint: {
            "text-color": "#1f2937",
            "text-halo-color": "rgba(255, 255, 255, 0.96)",
            "text-halo-width": 2.0
          }
        },
        {
          id: "place-labels",
          type: "symbol",
          source: "vector-tiles",
          "source-layer": "place",
          filter: [
            "match",
            ["get", "class"],
            ["city", "town", "village", "suburb", "neighbourhood"],
            true,
            false
          ],
          layout: {
            "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]],
            "text-font": ["Noto Sans Bold"],
            "text-size": ["match", ["get", "class"], "city", 22, "town", 18, "village", 15, "suburb", 13, 12],
            "text-letter-spacing": 0,
            "text-transform": ["match", ["get", "class"], ["city", "town"], "uppercase", "none"]
          },
          paint: {
            "text-color": "#111827",
            "text-halo-color": "rgba(255, 255, 255, 0.98)",
            "text-halo-width": 2.4
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
