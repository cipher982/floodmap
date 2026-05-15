/**
 * WebGL2 HAND terrain renderer for instant slider updates.
 *
 * The layer keeps raw uint16 HAND tiles resident as GPU textures. Slider changes
 * update a threshold uniform instead of rebuilding raster tiles.
 */

class FloodmapHandGpuLayer {
    constructor({ client, renderer, maxTextures = 128 }) {
        this.id = 'hand-gpu-layer';
        this.type = 'custom';
        this.renderingMode = '2d';

        this.client = client;
        this.renderer = renderer;
        this.maxTextures = maxTextures;
        this.tileSize = 256;
        this.nodataValue = 65535;

        this.map = null;
        this.gl = null;
        this.program = null;
        this.vertexBuffer = null;
        this.vertexArray = null;
        this.tiles = new Map();
        this.active = false;
        this.supported = false;
        this.fallbackReason = '';
        this.thresholdDm = 10;
        this.showNoData = false;
        this.sequence = 0;

        this.attribs = {};
        this.uniforms = {};
        this.stats = {
            supported: false,
            fallbackReason: '',
            tileTextureCount: 0,
            textureUploads: 0,
            tileRequests: 0,
            tileLoadErrors: 0,
            drawCalls: 0,
            renderCount: 0,
            lastRenderMs: 0
        };
    }

    setActive(active) {
        const nextActive = !!active;
        if (this.active === nextActive) return false;
        this.active = nextActive;
        if (this.map && this.active) this.map.triggerRepaint();
        return true;
    }

    setThresholdMeters(thresholdM) {
        const threshold = Number.isFinite(thresholdM) ? Math.max(0, thresholdM) : 1.0;
        const nextThresholdDm = Math.round(threshold * 10);
        if (this.thresholdDm === nextThresholdDm) return false;
        this.thresholdDm = nextThresholdDm;
        if (this.map && this.active) this.map.triggerRepaint();
        return true;
    }

    setShowNoData(showNoData) {
        const nextShowNoData = !!showNoData;
        if (this.showNoData === nextShowNoData) return false;
        this.showNoData = nextShowNoData;
        if (this.map && this.active) this.map.triggerRepaint();
        return true;
    }

    getStats() {
        return {
            ...this.stats,
            supported: this.supported,
            fallbackReason: this.fallbackReason,
            tileTextureCount: Array.from(this.tiles.values()).filter((tile) => tile.texture).length,
            trackedTiles: this.tiles.size,
            active: this.active,
            showNoData: this.showNoData
        };
    }

    onAdd(map, gl) {
        this.map = map;
        this.gl = gl;

        try {
            if (typeof WebGL2RenderingContext !== 'undefined' && !(gl instanceof WebGL2RenderingContext)) {
                throw new Error('WebGL2 context is required for HAND integer textures');
            }
            if (!gl.R16UI || !gl.RED_INTEGER || !gl.UNSIGNED_SHORT) {
                throw new Error('WebGL2 integer texture formats are unavailable');
            }
            if (typeof gl.createVertexArray !== 'function') {
                throw new Error('WebGL2 vertex arrays are unavailable');
            }

            this.program = this.createProgram(gl);
            this.vertexBuffer = gl.createBuffer();
            this.vertexArray = gl.createVertexArray();
            this.attribs.aPos = gl.getAttribLocation(this.program, 'a_pos');
            this.attribs.aUv = gl.getAttribLocation(this.program, 'a_uv');
            this.uniforms.uMatrix = gl.getUniformLocation(this.program, 'u_matrix');
            this.uniforms.uHand = gl.getUniformLocation(this.program, 'u_hand');
            this.uniforms.uTileBounds = gl.getUniformLocation(this.program, 'u_tileBounds');
            this.uniforms.uThresholdDm = gl.getUniformLocation(this.program, 'u_thresholdDm');
            this.uniforms.uShowNoData = gl.getUniformLocation(this.program, 'u_showNoData');
            this.configureGeometry(gl);
            this.supported = true;
            this.fallbackReason = '';
            this.stats.supported = true;
            this.stats.fallbackReason = '';
            this.uploadLoadedTiles();
            this.map.triggerRepaint();
        } catch (error) {
            this.supported = false;
            this.fallbackReason = error?.message || 'HAND GPU layer initialization failed';
            this.stats.supported = false;
            this.stats.fallbackReason = this.fallbackReason;
            if (this.client && typeof this.client.disableHandGpu === 'function') {
                this.client.disableHandGpu(this.fallbackReason);
            }
        }
    }

    onRemove() {
        if (this.gl) {
            for (const tile of this.tiles.values()) {
                if (tile.texture) this.gl.deleteTexture(tile.texture);
            }
            if (this.vertexArray && this.gl.deleteVertexArray) this.gl.deleteVertexArray(this.vertexArray);
            if (this.vertexBuffer) this.gl.deleteBuffer(this.vertexBuffer);
            if (this.program) this.gl.deleteProgram(this.program);
        }
        this.tiles.clear();
        this.map = null;
        this.gl = null;
        this.program = null;
        this.vertexBuffer = null;
        this.vertexArray = null;
        this.supported = false;
    }

    requestTile(z, x, y, signal = null) {
        const key = this.tileKey(z, x, y);
        let tile = this.tiles.get(key);
        if (tile) {
            tile.lastUsed = ++this.sequence;
            if (tile.state === 'evicted' && !tile.promise) {
                return this.loadTile(tile, signal);
            }
            return tile.promise || tile;
        }

        tile = {
            key,
            z,
            x,
            y,
            state: 'loading',
            data: null,
            texture: null,
            lastUsed: ++this.sequence,
            promise: null
        };
        this.tiles.set(key, tile);
        this.stats.tileRequests += 1;

        return this.loadTile(tile, signal);
    }

    loadTile(tile, signal = null) {
        tile.state = 'loading';
        tile.promise = this.renderer.loadTerrainTile('hand', tile.z, tile.x, tile.y, signal)
            .then((terrainData) => {
                tile.data = terrainData;
                tile.state = 'loaded';
                tile.promise = null;
                if (this.gl && this.supported) {
                    this.uploadTile(tile);
                }
                if (this.map && this.active) this.map.triggerRepaint();
                return tile;
            })
            .catch((error) => {
                if (error?.name === 'AbortError') {
                    this.tiles.delete(tile.key);
                    return null;
                }
                tile.state = 'error';
                tile.promise = null;
                this.stats.tileLoadErrors += 1;
                return tile;
            });

        return tile.promise;
    }

    uploadLoadedTiles() {
        if (!this.gl || !this.supported) return;
        for (const tile of this.tiles.values()) {
            if (tile.state === 'loaded' && tile.data) {
                this.uploadTile(tile);
            }
        }
    }

    uploadTile(tile) {
        if (!this.gl || !tile || !tile.data || tile.texture) return;
        const gl = this.gl;
        const previousActiveTexture = gl.getParameter(gl.ACTIVE_TEXTURE);
        gl.activeTexture(gl.TEXTURE0);
        const previousTexture = gl.getParameter(gl.TEXTURE_BINDING_2D);
        const previousUnpackAlignment = gl.getParameter(gl.UNPACK_ALIGNMENT);
        const previousFlipY = gl.getParameter(gl.UNPACK_FLIP_Y_WEBGL);
        const previousPremultiplyAlpha = gl.getParameter(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL);

        const texture = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texImage2D(
            gl.TEXTURE_2D,
            0,
            gl.R16UI,
            this.tileSize,
            this.tileSize,
            0,
            gl.RED_INTEGER,
            gl.UNSIGNED_SHORT,
            tile.data
        );

        tile.texture = texture;
        tile.data = null;
        tile.state = 'ready';
        this.stats.textureUploads += 1;
        this.stats.tileTextureCount += 1;

        gl.pixelStorei(gl.UNPACK_ALIGNMENT, previousUnpackAlignment);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, previousFlipY);
        gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, previousPremultiplyAlpha);
        gl.bindTexture(gl.TEXTURE_2D, previousTexture);
        gl.activeTexture(previousActiveTexture);
        this.evictTextures();
    }

    evictTextures() {
        const texturedTiles = Array.from(this.tiles.values())
            .filter((tile) => tile.texture)
            .sort((a, b) => a.lastUsed - b.lastUsed);
        while (texturedTiles.length > this.maxTextures) {
            const tile = texturedTiles.shift();
            if (!tile?.texture || !this.gl) continue;
            this.gl.deleteTexture(tile.texture);
            this.tiles.delete(tile.key);
            this.stats.tileTextureCount = Math.max(0, this.stats.tileTextureCount - 1);
        }
    }

    render(gl, matrixOrArgs) {
        if (!this.active || !this.supported || !this.program) return;
        const matrix = this.resolveMatrix(matrixOrArgs);
        if (!matrix) return;
        this.syncVisibleSourceTiles();
        if (this.tiles.size === 0) return;

        const start = performance.now();
        const state = this.saveState(gl);

        gl.useProgram(this.program);
        gl.bindVertexArray(this.vertexArray);
        gl.uniformMatrix4fv(this.uniforms.uMatrix, false, matrix);
        gl.uniform1ui(this.uniforms.uThresholdDm, this.thresholdDm);
        gl.uniform1i(this.uniforms.uShowNoData, this.showNoData ? 1 : 0);
        gl.uniform1i(this.uniforms.uHand, 0);

        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        gl.disable(gl.DEPTH_TEST);
        gl.disable(gl.STENCIL_TEST);
        gl.activeTexture(gl.TEXTURE0);

        let drawCalls = 0;
        for (const tile of this.tiles.values()) {
            if (!tile.texture) continue;
            const bounds = this.tileBounds(tile);
            gl.bindTexture(gl.TEXTURE_2D, tile.texture);
            gl.uniform4f(this.uniforms.uTileBounds, bounds.x0, bounds.y0, bounds.x1, bounds.y1);
            gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
            drawCalls += 1;
        }

        this.restoreState(gl, state);
        this.stats.drawCalls += drawCalls;
        this.stats.renderCount += 1;
        this.stats.lastRenderMs = performance.now() - start;
    }

    syncVisibleSourceTiles() {
        const sourceTiles = this.map?.style?.sourceCaches?.['elevation-tiles']?._tiles;
        if (!sourceTiles) return;
        for (const mapTile of Object.values(sourceTiles)) {
            const canonical = mapTile?.tileID?.canonical;
            if (!canonical) continue;
            const { z, x, y } = canonical;
            if (!Number.isInteger(z) || !Number.isInteger(x) || !Number.isInteger(y)) continue;
            void this.requestTile(z, x, y);
        }
    }

    resolveMatrix(matrixOrArgs) {
        if (matrixOrArgs?.defaultProjectionData?.mainMatrix) {
            return matrixOrArgs.defaultProjectionData.mainMatrix;
        }
        if (matrixOrArgs?.defaultProjectionData?.projectionMatrix) {
            return matrixOrArgs.defaultProjectionData.projectionMatrix;
        }
        if (matrixOrArgs?.modelViewProjectionMatrix) {
            return matrixOrArgs.modelViewProjectionMatrix;
        }
        if (matrixOrArgs?.projectionMatrix) {
            return matrixOrArgs.projectionMatrix;
        }
        if (matrixOrArgs?.mainMatrix) {
            return matrixOrArgs.mainMatrix;
        }
        return matrixOrArgs;
    }

    configureGeometry(gl) {
        const state = this.saveState(gl);
        gl.bindVertexArray(this.vertexArray);
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
            0, 0, 0, 0,
            1, 0, 1, 0,
            0, 1, 0, 1,
            1, 1, 1, 1
        ]), gl.STATIC_DRAW);
        this.bindGeometry(gl);
        this.restoreState(gl, state);
    }

    bindGeometry(gl) {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vertexBuffer);
        gl.enableVertexAttribArray(this.attribs.aPos);
        gl.enableVertexAttribArray(this.attribs.aUv);
        gl.vertexAttribPointer(this.attribs.aPos, 2, gl.FLOAT, false, 16, 0);
        gl.vertexAttribPointer(this.attribs.aUv, 2, gl.FLOAT, false, 16, 8);
    }

    tileBounds(tile) {
        if (tile.bounds) return tile.bounds;
        const scale = 2 ** tile.z;
        const wrappedX = ((tile.x % scale) + scale) % scale;
        const x0 = wrappedX / scale;
        const x1 = (wrappedX + 1) / scale;
        const y0 = tile.y / scale;
        const y1 = (tile.y + 1) / scale;
        tile.bounds = { x0, y0, x1, y1 };
        return tile.bounds;
    }

    saveState(gl) {
        const activeTexture = gl.getParameter(gl.ACTIVE_TEXTURE);
        gl.activeTexture(gl.TEXTURE0);
        const texture0 = gl.getParameter(gl.TEXTURE_BINDING_2D);
        gl.activeTexture(activeTexture);
        return {
            program: gl.getParameter(gl.CURRENT_PROGRAM),
            arrayBuffer: gl.getParameter(gl.ARRAY_BUFFER_BINDING),
            elementArrayBuffer: gl.getParameter(gl.ELEMENT_ARRAY_BUFFER_BINDING),
            texture0,
            activeTexture,
            blend: gl.isEnabled(gl.BLEND),
            depthTest: gl.isEnabled(gl.DEPTH_TEST),
            stencilTest: gl.isEnabled(gl.STENCIL_TEST),
            cullFace: gl.isEnabled(gl.CULL_FACE),
            blendSrcRgb: gl.getParameter(gl.BLEND_SRC_RGB),
            blendDstRgb: gl.getParameter(gl.BLEND_DST_RGB),
            blendSrcAlpha: gl.getParameter(gl.BLEND_SRC_ALPHA),
            blendDstAlpha: gl.getParameter(gl.BLEND_DST_ALPHA),
            vertexArray: typeof gl.getParameter === 'function' && gl.VERTEX_ARRAY_BINDING
                ? gl.getParameter(gl.VERTEX_ARRAY_BINDING)
                : null
        };
    }

    restoreState(gl, state) {
        if (gl.bindVertexArray) gl.bindVertexArray(state.vertexArray);
        if (!state.vertexArray) {
            gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, state.elementArrayBuffer);
        }
        gl.useProgram(state.program);
        gl.bindBuffer(gl.ARRAY_BUFFER, state.arrayBuffer);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, state.texture0);
        gl.activeTexture(state.activeTexture);
        this.restoreCapability(gl, gl.BLEND, state.blend);
        this.restoreCapability(gl, gl.DEPTH_TEST, state.depthTest);
        this.restoreCapability(gl, gl.STENCIL_TEST, state.stencilTest);
        this.restoreCapability(gl, gl.CULL_FACE, state.cullFace);
        gl.blendFuncSeparate(
            state.blendSrcRgb,
            state.blendDstRgb,
            state.blendSrcAlpha,
            state.blendDstAlpha
        );
    }

    restoreCapability(gl, capability, enabled) {
        if (enabled) gl.enable(capability);
        else gl.disable(capability);
    }

    createProgram(gl) {
            const vertexShader = this.compileShader(gl, gl.VERTEX_SHADER, `#version 300 es
            precision highp float;
            in vec2 a_pos;
            in vec2 a_uv;
            uniform mat4 u_matrix;
            uniform vec4 u_tileBounds;
            out vec2 v_uv;
            void main() {
                v_uv = a_uv;
                vec2 mercator = mix(u_tileBounds.xy, u_tileBounds.zw, a_pos);
                gl_Position = u_matrix * vec4(mercator, 0.0, 1.0);
            }
        `);
        const fragmentShader = this.compileShader(gl, gl.FRAGMENT_SHADER, `#version 300 es
            precision highp float;
            precision highp int;
            precision highp usampler2D;
            uniform highp usampler2D u_hand;
            uniform uint u_thresholdDm;
            uniform bool u_showNoData;
            in vec2 v_uv;
            out vec4 fragColor;

            float handAsinh(float value) {
                return log(value + sqrt(value * value + 1.0));
            }

            vec4 mixStop(vec4 a, vec4 b, float t) {
                return mix(a, b, clamp(t, 0.0, 1.0));
            }

            vec4 ramp(float t) {
                vec4 c0 = vec4(18.0 / 255.0, 97.0 / 255.0, 160.0 / 255.0, 220.0 / 255.0);
                vec4 c1 = vec4(45.0 / 255.0, 165.0 / 255.0, 205.0 / 255.0, 205.0 / 255.0);
                vec4 c2 = vec4(98.0 / 255.0, 190.0 / 255.0, 170.0 / 255.0, 175.0 / 255.0);
                vec4 c3 = vec4(190.0 / 255.0, 204.0 / 255.0, 132.0 / 255.0, 125.0 / 255.0);
                vec4 c4 = vec4(205.0 / 255.0, 170.0 / 255.0, 110.0 / 255.0, 70.0 / 255.0);
                if (t <= 0.18) return mixStop(c0, c1, t / 0.18);
                if (t <= 0.38) return mixStop(c1, c2, (t - 0.18) / 0.20);
                if (t <= 0.65) return mixStop(c2, c3, (t - 0.38) / 0.27);
                return mixStop(c3, c4, (t - 0.65) / 0.35);
            }

            void main() {
                uint raw = texture(u_hand, v_uv).r;
                if (raw == 65535u) {
                    if (u_showNoData) {
                        fragColor = vec4(0.74, 0.0, 1.0, 0.42);
                        return;
                    }
                    discard;
                }

                if (raw > u_thresholdDm) discard;

                float heightDm = float(raw);
                float heightM = heightDm * 0.1;
                float thresholdM = max(0.1, float(u_thresholdDm) * 0.1);
                float compressed = handAsinh(max(0.0, heightM) / 1.5)
                    / max(0.000001, handAsinh(thresholdM / 1.5));
                fragColor = ramp(clamp(compressed, 0.0, 1.0));
            }
        `);

        const program = gl.createProgram();
        gl.attachShader(program, vertexShader);
        gl.attachShader(program, fragmentShader);
        gl.linkProgram(program);
        gl.deleteShader(vertexShader);
        gl.deleteShader(fragmentShader);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
            const info = gl.getProgramInfoLog(program);
            gl.deleteProgram(program);
            throw new Error(`HAND GPU shader link failed: ${info}`);
        }
        return program;
    }

    compileShader(gl, type, source) {
        const shader = gl.createShader(type);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
            const info = gl.getShaderInfoLog(shader);
            gl.deleteShader(shader);
            throw new Error(`HAND GPU shader compile failed: ${info}`);
        }
        return shader;
    }

    tileKey(z, x, y) {
        return `${z}/${x}/${y}`;
    }
}

if (typeof window !== 'undefined') {
    window.FloodmapHandGpuLayer = FloodmapHandGpuLayer;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = FloodmapHandGpuLayer;
}
