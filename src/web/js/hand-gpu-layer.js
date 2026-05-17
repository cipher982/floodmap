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
        this.animationFrame = null;
        this.animationStartedAt = 0;
        this.forceNextRender = true;

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
            lastRenderMs: 0,
            visualModel: 'terrain-gradient-current-v1'
        };
    }

    setActive(active) {
        const nextActive = !!active;
        if (this.active === nextActive) return false;
        this.active = nextActive;
        if (this.active) {
            this.forceNextRender = true;
            this.startAnimation();
            if (this.map) this.map.triggerRepaint();
        } else {
            this.stopAnimation();
        }
        return true;
    }

    setThresholdMeters(thresholdM) {
        const threshold = Number.isFinite(thresholdM) ? Math.max(0, thresholdM) : 1.0;
        const nextThresholdDm = Math.round(threshold * 10);
        if (this.thresholdDm === nextThresholdDm) return false;
        this.thresholdDm = nextThresholdDm;
        this.forceNextRender = true;
        if (this.map && this.active) this.map.triggerRepaint();
        return true;
    }

    setShowNoData(showNoData) {
        const nextShowNoData = !!showNoData;
        if (this.showNoData === nextShowNoData) return false;
        this.showNoData = nextShowNoData;
        this.forceNextRender = true;
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
            this.uniforms.uTime = gl.getUniformLocation(this.program, 'u_time');
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
        this.stopAnimation();
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
        this.forceNextRender = true;
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
        this.forceNextRender = false;
        const state = this.saveState(gl);

        gl.useProgram(this.program);
        gl.bindVertexArray(this.vertexArray);
        gl.uniformMatrix4fv(this.uniforms.uMatrix, false, matrix);
        gl.uniform1ui(this.uniforms.uThresholdDm, this.thresholdDm);
        gl.uniform1i(this.uniforms.uShowNoData, this.showNoData ? 1 : 0);
        gl.uniform1f(this.uniforms.uTime, this.currentTimeSeconds());
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

    startAnimation() {
        if (this.animationFrame || !this.map) return;
        this.animationStartedAt = performance.now();
        const tick = () => {
            this.animationFrame = null;
            if (!this.active || !this.map) return;
            if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
                this.animationFrame = window.setTimeout(tick, 250);
                return;
            }
            this.map.triggerRepaint();
            this.animationFrame = window.setTimeout(tick, 50);
        };
        this.animationFrame = window.setTimeout(tick, 0);
    }

    stopAnimation() {
        if (!this.animationFrame) return;
        if (typeof window !== 'undefined') {
            window.cancelAnimationFrame(this.animationFrame);
            window.clearTimeout(this.animationFrame);
        }
        this.animationFrame = null;
    }

    currentTimeSeconds() {
        if (!this.animationStartedAt) return 0;
        return (performance.now() - this.animationStartedAt) / 1000;
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
            out vec2 v_world;
            void main() {
                v_uv = a_uv;
                vec2 mercator = mix(u_tileBounds.xy, u_tileBounds.zw, a_pos);
                v_world = mercator;
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
            uniform float u_time;
            in vec2 v_uv;
            in vec2 v_world;
            out vec4 fragColor;

            float terrainDm(vec2 uv, float fallback) {
                uint raw = texture(u_hand, clamp(uv, vec2(0.0), vec2(1.0))).r;
                return raw == 65535u ? fallback : float(raw);
            }

            float waveNoise(vec2 world, float time) {
                float a = sin(world.x * 980.0 + world.y * 520.0 + time * 1.4);
                float b = sin(world.x * 2110.0 - world.y * 1360.0 - time * 1.9);
                float c = sin((world.x + world.y) * 4200.0 + time * 2.8);
                return (a + 0.55 * b + 0.28 * c) / 1.83;
            }

            vec4 mixStop(vec4 a, vec4 b, float t) {
                return mix(a, b, clamp(t, 0.0, 1.0));
            }

            vec4 waterRamp(float depthT, float shimmer) {
                vec4 shallow = vec4(80.0 / 255.0, 190.0 / 255.0, 240.0 / 255.0, 0.45);
                vec4 mid = vec4(22.0 / 255.0, 124.0 / 255.0, 215.0 / 255.0, 0.64);
                vec4 deep = vec4(4.0 / 255.0, 48.0 / 255.0, 128.0 / 255.0, 0.82);
                vec4 color = depthT < 0.55
                    ? mixStop(shallow, mid, depthT / 0.55)
                    : mixStop(mid, deep, (depthT - 0.55) / 0.45);
                color.rgb += shimmer * vec3(0.055, 0.095, 0.11);
                color.a = clamp(color.a + shimmer * 0.06, 0.32, 0.88);
                return color;
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

                float rawDm = float(raw);
                vec2 texel = vec2(1.0 / 256.0);
                float left = terrainDm(v_uv - vec2(texel.x, 0.0), rawDm);
                float right = terrainDm(v_uv + vec2(texel.x, 0.0), rawDm);
                float up = terrainDm(v_uv - vec2(0.0, texel.y), rawDm);
                float down = terrainDm(v_uv + vec2(0.0, texel.y), rawDm);
                vec2 gradient = vec2(right - left, down - up);
                float gradientStrength = clamp(length(gradient) / 12.0, 0.0, 1.0);
                vec2 current = length(gradient) > 0.001
                    ? normalize(-gradient)
                    : normalize(vec2(0.62, 0.78));

                float thresholdDm = max(1.0, float(u_thresholdDm));
                float thresholdM = max(0.1, float(u_thresholdDm) * 0.1);
                float apparentDepthM = max(0.0, (thresholdDm - rawDm) * 0.1);
                float depthT = 1.0 - exp(-apparentDepthM / max(0.8, thresholdM * 0.08));
                float shimmer = waveNoise(v_world, u_time);
                vec4 water = waterRamp(clamp(depthT, 0.0, 1.0), shimmer);

                float flowCoord = dot(v_world * vec2(14000.0, 9000.0), current);
                float crossCoord = dot(v_world * vec2(9000.0, 14000.0), vec2(-current.y, current.x));
                float currentBand = smoothstep(0.68, 1.0, sin(flowCoord - u_time * (2.0 + gradientStrength * 4.0)) * 0.5 + 0.5);
                float fastBand = smoothstep(0.74, 1.0, sin(flowCoord * 2.4 - u_time * (4.5 + gradientStrength * 5.5)) * 0.5 + 0.5);
                float ripple = smoothstep(0.45, 1.0, sin(crossCoord + u_time * 1.6) * 0.5 + 0.5);
                float broken = smoothstep(-0.2, 0.8, waveNoise(v_world * 1.8 + current * 0.01, u_time * 0.35));
                float currentLight = (currentBand * 0.58 + fastBand * 0.42)
                    * mix(0.24, 0.9, gradientStrength)
                    * (0.35 + 0.65 * ripple)
                    * (0.55 + 0.45 * broken);
                vec3 currentColor = vec3(0.58, 0.93, 1.0);
                water.rgb = mix(water.rgb, currentColor, clamp(currentLight * (0.38 + depthT * 0.32), 0.0, 0.62));
                water.a = clamp(water.a + currentLight * 0.18, 0.34, 0.92);

                float foamWidthDm = clamp(6.0 + thresholdDm * 0.012, 5.0, 120.0);
                float foamBand = 1.0 - smoothstep(0.0, foamWidthDm, abs(thresholdDm - rawDm));
                float foamPulse = 0.5 + 0.5 * sin(u_time * 5.2 + v_world.x * 6200.0 - v_world.y * 4100.0);
                vec4 foam = vec4(0.88, 0.98, 1.0, 0.72 + foamPulse * 0.14);
                fragColor = mix(water, foam, clamp(foamBand * (0.75 + foamPulse * 0.25), 0.0, 1.0));
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
