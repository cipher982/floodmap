/*
 * Real terrain 3D renderer for FloodMap.
 *
 * This milestone renders one real WebMercator terrain tile as a 3D mesh,
 * captures a matching vector basemap into a texture, and draws animated
 * HAND-seeded water above it. The next engine can replace the threshold water
 * surface with a stateful WebGPU solver without changing the data contract.
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
    this.captureEl = document.getElementById("basemap-capture");
    this.renderer = new ElevationRenderer();
    this.params = new URLSearchParams(window.location.search);
    this.zoom = Terrain3dMath.clamp(Number.parseInt(this.params.get("zoom") || "12", 10), 8, 14);
    this.lat = Number.parseFloat(this.params.get("lat") || "33.5186");
    this.lng = Number.parseFloat(this.params.get("lng") || "-86.8104");
    this.waterMeters = Number.parseFloat(this.params.get("water") || this.waterInput.value || "20");
    this.exaggeration = Number.parseFloat(this.params.get("exaggeration") || this.exaggerationInput.value || "2.2");
    this.meshSize = Terrain3dMath.clamp(Number.parseInt(this.params.get("mesh") || "128", 10), 48, 192);
    this.rotationX = -0.98;
    this.rotationZ = -0.42;
    this.distance = 3.2;
    this.dragging = false;
    this.lastPointer = null;
    this.frameCount = 0;
    this.startedAt = performance.now();
    this.stats = {
      ready: false,
      visualModel: "map-draped-terrain-hand-water-v1",
      tile: null,
      terrainLoaded: false,
      handLoaded: false,
      basemapCaptured: false,
      waterVisible: false,
      waterVertexRatio: 0,
      minElevationM: null,
      maxElevationM: null,
      handDatasetVersion: null,
      frameCount: 0,
      lastFrameMs: 0,
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

    this.tile = Terrain3dMath.lonLatToTile(this.lng, this.lat, this.zoom);
    this.stats.tile = this.tile;
    this.publish("Loading terrain and map texture");
    const basemap = new Terrain3dBasemapCapture({
      container: this.captureEl,
      tile: this.tile
    });
    const [terrainData, handData, handMetadata, mapCanvas] = await Promise.all([
      this.renderer.loadElevationTile(this.tile.z, this.tile.x, this.tile.y),
      this.renderer.loadTerrainTile("hand", this.tile.z, this.tile.x, this.tile.y),
      this.renderer.getTerrainMetadata("hand").catch(() => null),
      basemap.capture()
    ]);
    this.stats.errors.push(...basemap.errors);
    this.handMetadata = handMetadata;
    this.stats.handDatasetVersion = handMetadata?.dataset_version || null;
    this.stats.basemapCaptured = true;
    this.stats.terrainLoaded = !this.isAllNoData(terrainData);
    this.stats.handLoaded = !this.isAllNoData(handData);
    this.initGlResources(mapCanvas);
    this.buildMeshes(terrainData, handData);
    this.stats.ready = true;
    this.publish("Ready");
    requestAnimationFrame((time) => this.render(time));
  }

  installEvents() {
    this.waterInput.value = String(this.waterMeters);
    this.exaggerationInput.value = String(this.exaggeration);
    this.waterInput.addEventListener("input", () => {
      this.waterMeters = Number.parseFloat(this.waterInput.value);
      this.updateWaterMesh();
      this.updateControls();
    });
    this.exaggerationInput.addEventListener("input", () => {
      this.exaggeration = Number.parseFloat(this.exaggerationInput.value);
      this.updateTerrainGeometry();
      this.updateWaterMesh();
      this.updateControls();
    });
    this.canvas.addEventListener("pointerdown", (event) => {
      this.dragging = true;
      this.lastPointer = { x: event.clientX, y: event.clientY };
      this.canvas.setPointerCapture(event.pointerId);
    });
    this.canvas.addEventListener("pointermove", (event) => {
      if (!this.dragging || !this.lastPointer) return;
      const dx = event.clientX - this.lastPointer.x;
      const dy = event.clientY - this.lastPointer.y;
      this.rotationZ += dx * 0.006;
      this.rotationX = Terrain3dMath.clamp(this.rotationX + dy * 0.004, -1.32, -0.35);
      this.lastPointer = { x: event.clientX, y: event.clientY };
    });
    this.canvas.addEventListener("pointerup", (event) => {
      this.dragging = false;
      this.lastPointer = null;
      try {
        this.canvas.releasePointerCapture(event.pointerId);
      } catch {}
    });
    this.canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.distance = Terrain3dMath.clamp(this.distance + event.deltaY * 0.002, 1.7, 6.5);
    }, { passive: false });
  }

  updateControls() {
    this.waterReadout.textContent = `${this.waterMeters.toFixed(this.waterMeters >= 100 ? 0 : 1)}m`;
    this.exaggerationReadout.textContent = `${this.exaggeration.toFixed(1)}x`;
  }

  initGlResources(mapCanvas) {
    const gl = this.gl;
    this.terrainProgram = this.createProgram(
      Terrain3dShaders.terrainVertex,
      Terrain3dShaders.terrainFragment
    );
    this.waterProgram = this.createProgram(
      Terrain3dShaders.waterVertex,
      Terrain3dShaders.waterFragment
    );
    this.mapTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.mapTexture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, mapCanvas);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    this.terrainVao = gl.createVertexArray();
    this.terrainBuffer = gl.createBuffer();
    this.terrainIndexBuffer = gl.createBuffer();
    this.waterVao = gl.createVertexArray();
    this.waterBuffer = gl.createBuffer();
    this.waterIndexBuffer = gl.createBuffer();
    gl.clearColor(0.02, 0.035, 0.065, 1);
    gl.enable(gl.DEPTH_TEST);
  }

  buildMeshes(terrainData, handData) {
    this.terrainData = terrainData;
    this.handData = handData;
    this.updateTerrainGeometry();
    this.updateWaterMesh();
  }

  updateTerrainGeometry() {
    const mesh = Terrain3dMeshBuilder.buildTerrain({
      renderer: this.renderer,
      terrainData: this.terrainData,
      meshSize: this.meshSize,
      exaggeration: this.exaggeration
    });
    this.minElevationM = mesh.minElevationM;
    this.maxElevationM = mesh.maxElevationM;
    this.stats.minElevationM = Number(this.minElevationM.toFixed(2));
    this.stats.maxElevationM = Number(this.maxElevationM.toFixed(2));
    this.terrainVertices = mesh.vertices;
    this.terrainIndices = mesh.indices;
    this.uploadTerrain();
  }

  updateWaterMesh() {
    if (!this.terrainVertices || !this.handData) return;
    const mesh = Terrain3dMeshBuilder.buildWater({
      renderer: this.renderer,
      handData: this.handData,
      terrainVertices: this.terrainVertices,
      meshSize: this.meshSize,
      waterMeters: this.waterMeters
    });
    this.waterVertices = mesh.vertices;
    this.waterIndices = mesh.indices;
    this.stats.waterVisible = mesh.waterVisible;
    this.stats.waterVertexRatio = mesh.waterVertexRatio;
    this.uploadWater();
    this.publish(this.stats.ready ? "Ready" : "Building water");
  }

  isAllNoData(values) {
    for (const value of values) {
      if (value !== this.renderer.NODATA_VALUE) return false;
    }
    return true;
  }

  uploadTerrain() {
    const gl = this.gl;
    gl.bindVertexArray(this.terrainVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.terrainBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, this.terrainVertices, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.terrainIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.terrainIndices, gl.STATIC_DRAW);
    this.configureTerrainAttributes();
    gl.bindVertexArray(null);
  }

  uploadWater() {
    const gl = this.gl;
    gl.bindVertexArray(this.waterVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.waterBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, this.waterVertices, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.waterIndexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.waterIndices, gl.DYNAMIC_DRAW);
    this.configureWaterAttributes();
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
    const stride = 6 * 4;
    const pos = gl.getAttribLocation(this.waterProgram, "a_pos");
    const uv = gl.getAttribLocation(this.waterProgram, "a_uv");
    const depth = gl.getAttribLocation(this.waterProgram, "a_depth");
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(uv);
    gl.vertexAttribPointer(uv, 2, gl.FLOAT, false, stride, 3 * 4);
    gl.enableVertexAttribArray(depth);
    gl.vertexAttribPointer(depth, 1, gl.FLOAT, false, stride, 5 * 4);
  }

  render(time) {
    const gl = this.gl;
    const start = performance.now();
    this.resize();
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const matrix = this.viewProjectionMatrix();

    gl.useProgram(this.terrainProgram);
    gl.bindVertexArray(this.terrainVao);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.mapTexture);
    gl.uniform1i(gl.getUniformLocation(this.terrainProgram, "u_map"), 0);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.terrainProgram, "u_matrix"), false, matrix);
    gl.uniform3f(gl.getUniformLocation(this.terrainProgram, "u_light"), -0.38, 0.82, 0.42);
    gl.drawElements(gl.TRIANGLES, this.terrainIndices.length, gl.UNSIGNED_INT, 0);

    if (this.waterIndices?.length) {
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.useProgram(this.waterProgram);
      gl.bindVertexArray(this.waterVao);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.waterProgram, "u_matrix"), false, matrix);
      gl.uniform1f(gl.getUniformLocation(this.waterProgram, "u_time"), (time - this.startedAt) / 1000);
      gl.drawElements(gl.TRIANGLES, this.waterIndices.length, gl.UNSIGNED_INT, 0);
      gl.disable(gl.BLEND);
    }
    gl.bindVertexArray(null);
    this.frameCount += 1;
    this.stats.frameCount = this.frameCount;
    this.stats.lastFrameMs = Number((performance.now() - start).toFixed(3));
    if (this.frameCount % 20 === 0) this.publish("Ready");
    requestAnimationFrame((nextTime) => this.render(nextTime));
  }

  viewProjectionMatrix() {
    const aspect = this.canvas.width / Math.max(1, this.canvas.height);
    const proj = Mat4.perspective(Math.PI / 4.5, aspect, 0.05, 50);
    let view = Mat4.identity();
    view = Mat4.multiply(view, Mat4.translate(0, -0.10, -this.distance));
    view = Mat4.multiply(view, Mat4.rotateX(this.rotationX));
    view = Mat4.multiply(view, Mat4.rotateY(0.0));
    view = Mat4.multiply(view, Mat4.rotateZ(this.rotationZ));
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
