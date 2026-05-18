/*
 * Real terrain 3D renderer for FloodMap.
 *
 * This renderer is a multi-tile WebMercator scene: every visible tile gets real
 * elevation, HAND, and a captured vector basemap texture. Water is still seeded
 * from HAND thresholds, but its shader motion follows per-vertex HAND gradients
 * so the current visually runs through drainage corridors instead of shimmering
 * in place.
 */

class FloodTerrain3dApp {
  constructor() {
    this.canvas = document.getElementById("terrain-3d-canvas");
    this.statusEl = document.getElementById("terrain-status");
    this.statsEl = document.getElementById("terrain-stats");
    this.waterInput = document.getElementById("water-level");
    this.waterReadout = document.getElementById("water-readout");
    this.exaggerationInput = document.getElementById("exaggeration");
    this.exaggerationReadout = document.getElementById("exaggeration-readout");
    this.resetCameraButton = document.getElementById("reset-camera");
    this.playFloodButton = document.getElementById("play-flood");
    this.placeSearchForm = document.getElementById("terrain-place-search");
    this.placeSearchInput = document.getElementById("terrain-place-query");
    this.captureEl = document.getElementById("basemap-capture");
    this.renderer = new ElevationRenderer();
    this.params = new URLSearchParams(window.location.search);
    this.zoom = Terrain3dMath.clamp(Number.parseInt(this.params.get("zoom") || "12", 10), 8, 14);
    this.lat = Number.parseFloat(this.params.get("lat") || "33.5186");
    this.lng = Number.parseFloat(this.params.get("lng") || "-86.8104");
    this.waterMeters = Number.parseFloat(this.params.get("water") || this.waterInput.value || "22");
    this.exaggeration = Terrain3dMath.clamp(
      Number.parseFloat(this.params.get("exaggeration") || this.exaggerationInput.value || "2"),
      0.4,
      5
    );
    this.meshSize = Terrain3dMath.clamp(Number.parseInt(this.params.get("mesh") || "192", 10), 64, 224);
    this.worldRadius = Terrain3dMath.clamp(Number.parseInt(this.params.get("radius") || "1", 10), 0, 1);
    this.tileScale = 1.38;
    this.defaultCamera = { rotationX: -0.86, rotationZ: -0.34, distance: 6.2, panX: 0, panZ: 0 };
    this.rotationX = this.defaultCamera.rotationX;
    this.rotationZ = this.defaultCamera.rotationZ;
    this.distance = this.defaultCamera.distance;
    this.panX = this.defaultCamera.panX;
    this.panZ = this.defaultCamera.panZ;
    this.dragging = false;
    this.panning = false;
    this.lastPointer = null;
    this.frameCount = 0;
    this.navigationCount = 0;
    this.activeLoadId = 0;
    this.startedAt = performance.now();
    this.tiles = [];
    this.floodPlayer = new Terrain3dFloodPlayer({
      getValue: () => this.waterMeters,
      setValue: (value) => this.setWaterMeters(value)
    });
    this.tileCache = new Map();
    this.tileCacheClock = 0;
    this.maxTileCacheEntries = 45;
    this.targetTileCacheEntries = 36;
    this.stats = {
      ready: false,
      visualModel: "map-draped-terrain-hand-water-world-v2",
      centerTile: null,
      tile: null,
      worldRadius: this.worldRadius,
      tileCount: 0,
      tilesLoaded: 0,
      terrainLoaded: false,
      elevationSource: null,
      handLoaded: false,
      basemapCaptured: false,
      tileCacheSize: 0,
      tileCacheHits: 0,
      tileCacheMisses: 0,
      waterMeters: this.waterMeters,
      floodPlaybackActive: false,
      waterVisible: false,
      waterVertexRatio: 0,
      flowParticleCount: 0,
      meshSize: this.meshSize,
      minElevationM: null,
      maxElevationM: null,
      handDatasetVersion: null,
      placeLabel: null,
      navigationCount: 0,
      frameCount: 0,
      lastFrameMs: 0,
      warnings: [],
      errors: []
    };
  }

  async boot() {
    window.floodTerrain3d = this;
    this.updateControls();
    this.installEvents();
    this.gl = this.canvas.getContext("webgl2", {
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true
    });
    if (!this.gl) throw new Error("WebGL2 is required for terrain 3D");
    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.centerTile = Terrain3dMath.lonLatToTile(this.lng, this.lat, this.zoom);
    this.initGlResources();
    await this.loadWorld();
    requestAnimationFrame((time) => this.render(time));
  }

  async loadWorld() {
    const loadId = this.activeLoadId + 1;
    this.activeLoadId = loadId;
    this.stats.ready = false;
    this.stats.errors = [];
    this.stats.warnings = [];
    this.publish("Loading terrain world");
    const plan = Terrain3dWorld.buildGrid({
      centerTile: this.centerTile,
      radius: this.worldRadius,
      tileScale: this.tileScale
    });
    this.centerTile = plan.centerTile;
    this.stats.centerTile = plan.centerTile;
    this.stats.tile = plan.centerTile;
    this.stats.tileCount = plan.tiles.length;
    this.stats.tilesLoaded = 0;

    const handMetadata = await this.renderer.getTerrainMetadata("hand").catch(() => null);
    this.handMetadata = handMetadata;
    this.stats.handDatasetVersion = handMetadata?.dataset_version || null;

    const activeKeys = new Set(plan.tiles.map((tile) => tile.key));
    const loaded = await Promise.all(plan.tiles.map((tile) => this.loadTileData(tile)));
    const globalStats = this.globalElevationStats(loaded);
    const sceneTiles = [];
    for (const tile of loaded) {
      if (loadId !== this.activeLoadId) return;
      if (!tile.mapTexture) {
        const basemap = new Terrain3dBasemapCapture({
          container: this.captureEl,
          tile
        });
        try {
          const mapCanvas = await basemap.capture();
          tile.mapTexture = this.createTexture(mapCanvas);
          this.updateCachedMapTexture(tile);
        } catch (error) {
          this.stats.errors.push(`Basemap ${tile.key}: ${error?.message || String(error)}`);
        }
        this.stats.errors.push(...basemap.errors.map((message) => `Basemap ${tile.key}: ${message}`));
      }
      sceneTiles.push(this.createSceneTile(tile, globalStats));
      this.stats.tilesLoaded = sceneTiles.length;
      this.publish(`Loaded ${sceneTiles.length}/${plan.tiles.length} tiles`);
    }
    if (loadId !== this.activeLoadId) return;
    this.destroyTiles(this.tiles);
    this.tiles = sceneTiles;
    this.stats.minElevationM = Number(globalStats.minElevationM.toFixed(2));
    this.stats.maxElevationM = Number(globalStats.maxElevationM.toFixed(2));
    this.stats.elevationSource = loaded.every((tile) => tile.elevationSource === "terrain-v2-elevation")
      ? "terrain-v2-elevation"
      : "mixed-or-fallback";
    this.stats.basemapCaptured = sceneTiles.every((tile) => Boolean(tile.mapTexture));
    this.stats.terrainLoaded = sceneTiles.some((tile) => tile.terrainLoaded);
    this.stats.handLoaded = sceneTiles.some((tile) => tile.handLoaded);
    this.updateAllWaterMeshes();
    this.evictTileCache(activeKeys);
    this.stats.ready = true;
    this.publish("Ready");
  }

  async loadTileData(tile) {
    const cached = this.tileCache.get(tile.key);
    if (cached) {
      cached.lastUsed = ++this.tileCacheClock;
      this.stats.tileCacheHits += 1;
      this.stats.tileCacheSize = this.tileCache.size;
      return {
        ...tile,
        terrainData: cached.terrainData,
        elevationSource: cached.elevationSource,
        handData: cached.handData,
        terrainLoaded: cached.terrainLoaded,
        handLoaded: cached.handLoaded,
        mapTexture: cached.mapTexture
      };
    }
    this.stats.tileCacheMisses += 1;
    const [terrainResult, handData] = await Promise.all([
      this.loadElevationSurfaceTile(tile),
      this.renderer.loadTerrainTile("hand", tile.z, tile.x, tile.y)
    ]);
    const entry = {
      key: tile.key,
      terrainData: terrainResult.data,
      elevationSource: terrainResult.source,
      handData,
      terrainLoaded: !this.isAllNoData(terrainResult.data),
      handLoaded: !this.isAllNoData(handData),
      mapTexture: null,
      lastUsed: ++this.tileCacheClock
    };
    this.tileCache.set(tile.key, entry);
    this.stats.tileCacheSize = this.tileCache.size;
    return { ...tile, ...entry };
  }

  updateCachedMapTexture(tile) {
    const cached = this.tileCache.get(tile.key);
    if (!cached) return;
    cached.mapTexture = tile.mapTexture;
    cached.lastUsed = ++this.tileCacheClock;
  }

  evictTileCache(activeKeys) {
    const gl = this.gl;
    if (this.tileCache.size > this.maxTileCacheEntries) {
      const evictionCandidates = [...this.tileCache.entries()]
        .filter(([key]) => !activeKeys.has(key))
        .sort((a, b) => a[1].lastUsed - b[1].lastUsed);
      for (const [key, entry] of evictionCandidates) {
        if (this.tileCache.size <= this.targetTileCacheEntries) break;
        if (entry.mapTexture) gl.deleteTexture(entry.mapTexture);
        this.tileCache.delete(key);
      }
    }
    this.stats.tileCacheSize = this.tileCache.size;
  }

  async loadElevationSurfaceTile(tile) {
    try {
      const metadata = await this.renderer.getTerrainMetadata("elevation");
      if (!metadata?.dataset_version) {
        throw new Error("Elevation terrain metadata has no dataset version");
      }
      const url = new URL(
        window.floodmapApiUrl(
          `/v2/terrain/elevation/${metadata.dataset_version}/${tile.z}/${tile.x}/${tile.y}.u16`
        ),
        window.location.origin
      );
      if (window.FLOODMAP_TILE_VERSION) {
        url.searchParams.set("v", window.FLOODMAP_TILE_VERSION);
      }
      const response = await fetch(url.toString());
      if (!response.ok) {
        throw new Error(`Elevation terrain tile failed: ${response.status}`);
      }
      return { data: new Uint16Array(await response.arrayBuffer()), source: "terrain-v2-elevation" };
    } catch (error) {
      this.stats.warnings.push(`Falling back to v1 elevation tiles for ${tile.key}: ${error?.message || String(error)}`);
      const data = await this.renderer.loadElevationTile(tile.z, tile.x, tile.y);
      return { data, source: "v1-elevation" };
    }
  }

  globalElevationStats(tiles) {
    let minElevationM = Infinity;
    let maxElevationM = -Infinity;
    for (const tile of tiles) {
      const stats = Terrain3dMeshBuilder.elevationStats(this.renderer, tile.terrainData);
      tile.localMinElevationM = stats.minElevationM;
      tile.localMaxElevationM = stats.maxElevationM;
      if (!tile.terrainLoaded) continue;
      minElevationM = Math.min(minElevationM, stats.minElevationM);
      maxElevationM = Math.max(maxElevationM, stats.maxElevationM);
    }
    if (!Number.isFinite(minElevationM) || !Number.isFinite(maxElevationM) || maxElevationM <= minElevationM) {
      minElevationM = 0;
      maxElevationM = 120;
    }
    return { minElevationM, maxElevationM };
  }

  installEvents() {
    this.waterInput.value = String(this.waterMeters);
    this.exaggerationInput.value = String(this.exaggeration);
    this.waterInput.addEventListener("input", () => {
      this.stopFloodPlayback();
      this.setWaterMeters(Number.parseFloat(this.waterInput.value));
    });
    this.exaggerationInput.addEventListener("input", () => {
      this.exaggeration = Terrain3dMath.clamp(Number.parseFloat(this.exaggerationInput.value), 0.4, 5);
      this.updateAllTerrainGeometry();
      this.updateAllWaterMeshes();
      this.updateControls();
    });
    this.canvas.addEventListener("pointerdown", (event) => {
      this.dragging = true;
      this.panning = event.shiftKey || event.button === 1 || event.button === 2;
      this.lastPointer = { x: event.clientX, y: event.clientY };
      this.canvas.setPointerCapture(event.pointerId);
    });
    this.canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    this.canvas.addEventListener("pointermove", (event) => {
      if (!this.dragging || !this.lastPointer) return;
      const dx = event.clientX - this.lastPointer.x;
      const dy = event.clientY - this.lastPointer.y;
      if (this.panning) {
        this.panX += dx * 0.006 * this.distance;
        this.panZ -= dy * 0.006 * this.distance;
      } else {
        this.rotationZ += dx * 0.006;
        this.rotationX = Terrain3dMath.clamp(this.rotationX + dy * 0.004, -1.32, -0.35);
      }
      this.lastPointer = { x: event.clientX, y: event.clientY };
    });
    this.canvas.addEventListener("pointerup", (event) => {
      this.dragging = false;
      this.panning = false;
      this.lastPointer = null;
      try {
        this.canvas.releasePointerCapture(event.pointerId);
      } catch {}
    });
    this.canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.distance = Terrain3dMath.clamp(this.distance + event.deltaY * 0.002, 2.2, 9.5);
    }, { passive: false });
    for (const button of document.querySelectorAll("[data-water-preset]")) {
      button.addEventListener("click", () => {
        this.stopFloodPlayback();
        this.setWaterMeters(Number.parseFloat(button.dataset.waterPreset || "20"));
      });
    }
    for (const button of document.querySelectorAll("[data-pan-tile]")) {
      button.addEventListener("click", () => this.moveWorld(button.dataset.panTile));
    }
    window.addEventListener("keydown", (event) => this.handleKey(event));
    this.placeSearchForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      this.searchAndMoveToPlace();
    });
    this.resetCameraButton?.addEventListener("click", () => this.resetCamera());
    this.playFloodButton?.addEventListener("click", () => {
      this.floodPlayer.toggle(performance.now());
      this.updateControls();
    });
  }

  handleKey(event) {
    if (event.defaultPrevented) return;
    const key = event.key.toLowerCase();
    if (key === "w" || key === "arrowup") this.moveWorld("north");
    if (key === "s" || key === "arrowdown") this.moveWorld("south");
    if (key === "a" || key === "arrowleft") this.moveWorld("west");
    if (key === "d" || key === "arrowright") this.moveWorld("east");
  }

  async moveWorld(direction) {
    const deltas = {
      north: [0, -1],
      south: [0, 1],
      west: [-1, 0],
      east: [1, 0]
    };
    const delta = deltas[direction];
    if (!delta || !this.centerTile) return;
    this.navigationCount += 1;
    this.stats.navigationCount = this.navigationCount;
    this.centerTile = Terrain3dWorld.moveTile(this.centerTile, delta[0], delta[1]);
    this.panX = 0;
    this.panZ = 0;
    await this.loadWorld();
  }

  async searchAndMoveToPlace() {
    const query = this.placeSearchInput?.value?.trim();
    if (!query) return;
    this.publish("Searching");
    const url = new URL(window.floodmapApiUrl("/places/search"), window.location.origin);
    url.searchParams.set("q", query);
    url.searchParams.set("limit", "1");
    const response = await fetch(url.toString(), { headers: { "Accept": "application/json" } });
    if (!response.ok) {
      this.stats.errors.push(`Place search failed: ${response.status}`);
      this.publish("Search failed");
      return;
    }
    const payload = await response.json();
    const result = payload?.results?.[0];
    const lat = Number(result?.latitude);
    const lng = Number(result?.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      this.stats.errors.push(`No place result for ${query}`);
      this.publish("No match");
      return;
    }
    this.lat = lat;
    this.lng = lng;
    this.centerTile = Terrain3dMath.lonLatToTile(this.lng, this.lat, this.zoom);
    this.navigationCount += 1;
    this.stats.navigationCount = this.navigationCount;
    this.stats.placeLabel = result.name || result.label || query;
    this.replaceUrlState();
    this.resetCamera();
    await this.loadWorld();
  }

  replaceUrlState() {
    const url = new URL(window.location.href);
    url.searchParams.set("lat", this.lat.toFixed(5));
    url.searchParams.set("lng", this.lng.toFixed(5));
    url.searchParams.set("zoom", String(this.zoom));
    url.searchParams.set("water", String(this.waterMeters));
    url.searchParams.set("exaggeration", String(this.exaggeration));
    window.history.replaceState(window.history.state, "", url);
  }

  resetCamera() {
    this.rotationX = this.defaultCamera.rotationX;
    this.rotationZ = this.defaultCamera.rotationZ;
    this.distance = this.defaultCamera.distance;
    this.panX = this.defaultCamera.panX;
    this.panZ = this.defaultCamera.panZ;
  }

  updateControls() {
    this.waterReadout.textContent = `${this.waterMeters.toFixed(this.waterMeters >= 100 ? 0 : 1)}m`;
    this.exaggerationReadout.textContent = `${this.exaggeration.toFixed(1)}x`;
    this.stats.waterMeters = this.waterMeters;
    this.stats.floodPlaybackActive = this.floodPlayer.playing;
    if (this.playFloodButton) {
      this.playFloodButton.textContent = this.floodPlayer.playing ? "Pause" : "Play flood";
      this.playFloodButton.classList.toggle("is-active", this.floodPlayer.playing);
    }
  }

  setWaterMeters(value) {
    this.waterMeters = Terrain3dMath.clamp(Number(value), 0, Number(this.waterInput.max || 1000));
    this.waterInput.value = String(this.waterMeters);
    this.updateAllWaterMeshes();
    this.updateControls();
  }

  stopFloodPlayback() {
    this.floodPlayer.stop();
    this.updateControls();
  }

  initGlResources() {
    const gl = this.gl;
    this.terrainProgram = this.createProgram(
      Terrain3dShaders.terrainVertex,
      Terrain3dShaders.terrainFragment
    );
    this.waterProgram = this.createProgram(
      Terrain3dShaders.waterVertex,
      Terrain3dShaders.waterFragment
    );
    this.flowProgram = this.createProgram(
      Terrain3dShaders.flowVertex,
      Terrain3dShaders.flowFragment
    );
    gl.clearColor(0.015, 0.025, 0.045, 1);
    gl.enable(gl.DEPTH_TEST);
  }

  createTexture(mapCanvas) {
    const gl = this.gl;
    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, mapCanvas);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    return texture;
  }

  createSceneTile(tile, globalStats) {
    const sceneTile = {
      ...tile,
      terrainVao: this.gl.createVertexArray(),
      terrainBuffer: this.gl.createBuffer(),
      terrainIndexBuffer: this.gl.createBuffer(),
      waterVao: this.gl.createVertexArray(),
      waterBuffer: this.gl.createBuffer(),
      waterIndexBuffer: this.gl.createBuffer(),
      flowVao: this.gl.createVertexArray(),
      flowBuffer: this.gl.createBuffer(),
      terrainVertices: null,
      terrainIndices: null,
      waterVertices: null,
      waterIndices: null,
      waterVertexRatio: 0,
      flowVertices: null,
      flowParticleCount: 0
    };
    this.updateTerrainGeometry(sceneTile, globalStats);
    return sceneTile;
  }

  updateAllTerrainGeometry() {
    const globalStats = {
      minElevationM: this.stats.minElevationM,
      maxElevationM: this.stats.maxElevationM
    };
    for (const tile of this.tiles) this.updateTerrainGeometry(tile, globalStats);
  }

  updateTerrainGeometry(tile, globalStats) {
    const mesh = Terrain3dMeshBuilder.buildTerrain({
      renderer: this.renderer,
      terrainData: tile.terrainData,
      meshSize: this.meshSize,
      exaggeration: this.exaggeration,
      originX: tile.originX,
      originZ: tile.originZ,
      tileScale: tile.tileScale,
      minElevationM: globalStats.minElevationM,
      maxElevationM: globalStats.maxElevationM
    });
    tile.terrainVertices = mesh.vertices;
    tile.terrainIndices = mesh.indices;
    this.uploadTerrain(tile);
  }

  updateAllWaterMeshes() {
    let visible = false;
    let ratioSum = 0;
    let flowParticleCount = 0;
    for (const tile of this.tiles) {
      this.updateWaterMesh(tile);
      visible = visible || Boolean(tile.waterIndices?.length);
      ratioSum += tile.waterVertexRatio || 0;
      flowParticleCount += tile.flowParticleCount || 0;
    }
    this.stats.waterVisible = visible;
    this.stats.waterVertexRatio = this.tiles.length
      ? Number((ratioSum / this.tiles.length).toFixed(4))
      : 0;
    this.stats.flowParticleCount = flowParticleCount;
    this.publish(this.stats.ready ? "Ready" : "Building water");
  }

  updateWaterMesh(tile) {
    if (!tile.terrainVertices || !tile.handData) return;
    const mesh = Terrain3dMeshBuilder.buildWater({
      renderer: this.renderer,
      handData: tile.handData,
      terrainVertices: tile.terrainVertices,
      meshSize: this.meshSize,
      waterMeters: this.waterMeters
    });
    tile.waterVertices = mesh.vertices;
    tile.waterIndices = mesh.indices;
    tile.waterVertexRatio = mesh.waterVertexRatio;
    this.uploadWater(tile);
    const flow = Terrain3dMeshBuilder.buildFlowParticles({
      renderer: this.renderer,
      handData: tile.handData,
      terrainVertices: tile.terrainVertices,
      meshSize: this.meshSize,
      waterMeters: this.waterMeters
    });
    tile.flowVertices = flow.vertices;
    tile.flowParticleCount = flow.particleCount;
    this.uploadFlow(tile);
  }

  isAllNoData(values) {
    for (const value of values) {
      if (value !== this.renderer.NODATA_VALUE) return false;
    }
    return true;
  }

  uploadTerrain(tile) {
    const gl = this.gl;
    gl.bindVertexArray(tile.terrainVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, tile.terrainBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, tile.terrainVertices, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, tile.terrainIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, tile.terrainIndices, gl.STATIC_DRAW);
    this.configureTerrainAttributes();
    gl.bindVertexArray(null);
  }

  uploadWater(tile) {
    const gl = this.gl;
    gl.bindVertexArray(tile.waterVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, tile.waterBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, tile.waterVertices, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, tile.waterIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, tile.waterIndices, gl.DYNAMIC_DRAW);
    this.configureWaterAttributes();
    gl.bindVertexArray(null);
  }

  uploadFlow(tile) {
    const gl = this.gl;
    gl.bindVertexArray(tile.flowVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, tile.flowBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, tile.flowVertices, gl.DYNAMIC_DRAW);
    this.configureFlowAttributes();
    gl.bindVertexArray(null);
  }

  configureTerrainAttributes() {
    const gl = this.gl;
    const stride = 8 * 4;
    const pos = gl.getAttribLocation(this.terrainProgram, "a_pos");
    const uv = gl.getAttribLocation(this.terrainProgram, "a_uv");
    const normal = gl.getAttribLocation(this.terrainProgram, "a_normal");
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(uv);
    gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, stride, 3 * 4);
    gl.enableVertexAttribArray(normal);
    gl.vertexAttribPointer(normal, 3, gl.FLOAT, false, stride, 5 * 4);
  }

  configureWaterAttributes() {
    const gl = this.gl;
    const stride = 8 * 4;
    const pos = gl.getAttribLocation(this.waterProgram, "a_pos");
    const uv = gl.getAttribLocation(this.waterProgram, "a_uv");
    const depth = gl.getAttribLocation(this.waterProgram, "a_depth");
    const flow = gl.getAttribLocation(this.waterProgram, "a_flow");
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(uv);
    gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, stride, 3 * 4);
    gl.enableVertexAttribArray(depth);
    gl.vertexAttribPointer(depth, 1, gl.FLOAT, false, stride, 5 * 4);
    gl.enableVertexAttribArray(flow);
    gl.vertexAttribPointer(flow, 2, gl.FLOAT, false, stride, 6 * 4);
  }

  configureFlowAttributes() {
    const gl = this.gl;
    const stride = 7 * 4;
    const pos = gl.getAttribLocation(this.flowProgram, "a_pos");
    const flow = gl.getAttribLocation(this.flowProgram, "a_flow");
    const phase = gl.getAttribLocation(this.flowProgram, "a_phase");
    const strength = gl.getAttribLocation(this.flowProgram, "a_strength");
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(flow);
    gl.vertexAttribPointer(flow, 2, gl.FLOAT, false, stride, 3 * 4);
    gl.enableVertexAttribArray(phase);
    gl.vertexAttribPointer(phase, 1, gl.FLOAT, false, stride, 5 * 4);
    gl.enableVertexAttribArray(strength);
    gl.vertexAttribPointer(strength, 1, gl.FLOAT, false, stride, 6 * 4);
  }

  render(time) {
    const gl = this.gl;
    const start = performance.now();
    this.floodPlayer.tick(time);
    this.resize();
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const matrix = this.viewProjectionMatrix();

    for (const tile of this.tiles) {
      gl.useProgram(this.terrainProgram);
      gl.bindVertexArray(tile.terrainVao);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, tile.mapTexture);
      gl.uniform1i(gl.getUniformLocation(this.terrainProgram, "u_map"), 0);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.terrainProgram, "u_matrix"), false, matrix);
      gl.uniform3f(gl.getUniformLocation(this.terrainProgram, "u_light"), -0.34, 0.86, 0.36);
      gl.uniform3f(gl.getUniformLocation(this.terrainProgram, "u_fogColor"), 0.015, 0.025, 0.045);
      gl.drawElements(gl.TRIANGLES, tile.terrainIndices.length, gl.UNSIGNED_INT, 0);
    }

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    for (const tile of this.tiles) {
      if (!tile.waterIndices?.length) continue;
      gl.useProgram(this.waterProgram);
      gl.bindVertexArray(tile.waterVao);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.waterProgram, "u_matrix"), false, matrix);
      gl.uniform1f(gl.getUniformLocation(this.waterProgram, "u_time"), (time - this.startedAt) / 1000);
      gl.drawElements(gl.TRIANGLES, tile.waterIndices.length, gl.UNSIGNED_INT, 0);
    }
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    for (const tile of this.tiles) {
      if (!tile.flowParticleCount) continue;
      gl.useProgram(this.flowProgram);
      gl.bindVertexArray(tile.flowVao);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.flowProgram, "u_matrix"), false, matrix);
      gl.uniform1f(gl.getUniformLocation(this.flowProgram, "u_time"), (time - this.startedAt) / 1000);
      gl.drawArrays(gl.POINTS, 0, tile.flowParticleCount);
    }
    gl.disable(gl.BLEND);
    gl.bindVertexArray(null);
    this.frameCount += 1;
    this.stats.frameCount = this.frameCount;
    this.stats.lastFrameMs = Number((performance.now() - start).toFixed(3));
    if (this.frameCount % 20 === 0) this.publish("Ready");
    requestAnimationFrame((nextTime) => this.render(nextTime));
  }

  viewProjectionMatrix() {
    const aspect = this.canvas.width / Math.max(1, this.canvas.height);
    const proj = Mat4.perspective(Math.PI / 4.5, aspect, 0.05, 80);
    let view = Mat4.identity();
    view = Mat4.multiply(view, Mat4.translate(this.panX, -0.12, -this.distance));
    view = Mat4.multiply(view, Mat4.rotateX(this.rotationX));
    view = Mat4.multiply(view, Mat4.rotateY(0.0));
    view = Mat4.multiply(view, Mat4.rotateZ(this.rotationZ));
    view = Mat4.multiply(view, Mat4.translate(0, 0, this.panZ));
    return Mat4.multiply(proj, view);
  }

  resize() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * dpr));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  destroyTiles(tiles) {
    const gl = this.gl;
    for (const tile of tiles || []) {
      if (tile.terrainVao) gl.deleteVertexArray(tile.terrainVao);
      if (tile.waterVao) gl.deleteVertexArray(tile.waterVao);
      if (tile.terrainBuffer) gl.deleteBuffer(tile.terrainBuffer);
      if (tile.terrainIndexBuffer) gl.deleteBuffer(tile.terrainIndexBuffer);
      if (tile.waterBuffer) gl.deleteBuffer(tile.waterBuffer);
      if (tile.waterIndexBuffer) gl.deleteBuffer(tile.waterIndexBuffer);
      if (tile.flowVao) gl.deleteVertexArray(tile.flowVao);
      if (tile.flowBuffer) gl.deleteBuffer(tile.flowBuffer);
    }
  }

  createProgram(vertexSource, fragmentSource) {
    const gl = this.gl;
    const vs = this.compileShader(gl.VERTEX_SHADER, vertexSource);
    const fs = this.compileShader(gl.FRAGMENT_SHADER, fragmentSource);
    const program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      const info = gl.getProgramInfoLog(program);
      gl.deleteProgram(program);
      throw new Error(`3D shader link failed: ${info}`);
    }
    return program;
  }

  compileShader(type, source) {
    const gl = this.gl;
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const info = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error(`3D shader compile failed: ${info}`);
    }
    return shader;
  }

  publish(status) {
    this.statusEl.textContent = status;
    this.statsEl.textContent = JSON.stringify(this.stats, null, 2);
  }
}

if (typeof window !== "undefined") {
  window.FloodTerrain3dApp = FloodTerrain3dApp;
  window.addEventListener("DOMContentLoaded", () => {
    const app = new FloodTerrain3dApp();
    app.boot().catch((error) => {
      app.stats.errors.push(error?.message || String(error));
      app.publish("3D scene failed");
      throw error;
    });
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FloodTerrain3dApp };
}
