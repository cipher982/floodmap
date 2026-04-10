/**
 * Client-side flood rendering with proper MapLibre integration
 * Uses custom protocol handler to intercept tile requests
 */

function requireFloodmapGlobal(globalName, expectedType = null) {
    const value = typeof window !== 'undefined' ? window[globalName] : null;
    if (value == null) {
        throw new Error(`${globalName} is required before loading Floodmap client scripts.`);
    }
    if (expectedType && typeof value !== expectedType) {
        throw new Error(`${globalName} must be a ${expectedType}.`);
    }
    return value;
}

function requireFloodmapUrlHelper(helperName) {
    return requireFloodmapGlobal(helperName, 'function');
}

function getFloodmapRouteContext() {
    if (typeof window === 'undefined') {
        return {};
    }

    const routeContext = window.FLOODMAP_ROUTE_CONTEXT;
    return routeContext && typeof routeContext === 'object' ? routeContext : {};
}

class FloodMapClient {
    constructor() {
        this.map = null;
        this.shareStatusResetTimer = null;
        this.pendingPermalinkFrame = null;
        this.routeContext = getFloodmapRouteContext();
        this.defaultViewState = this.routeContext.defaultViewState
            || requireFloodmapGlobal('FloodmapUrlState').DEFAULT_VIEW_STATE;
        this.initialViewState = requireFloodmapGlobal('FloodmapUrlState')
            .parseFloodmapUrlState(window.location.href, this.defaultViewState);
        this.currentWaterLevel = this.initialViewState.water;
        this.viewMode = this.initialViewState.view;
        this.jumpPlanner = requireFloodmapGlobal('FloodmapJumpPlanner');
        this.elevationRenderer = new ElevationRenderer();
        this.modelNoteState = { nearWater: false, coastal: false };
        this.locationSearchAbortController = null;
        this.locationSearchDebounceTimer = null;
        this.searchResults = [];
        this.searchResultsSignature = '';
        this.activeSearchResultIndex = -1;
        this.searchPrefetchSequence = 0;
        this.searchPrefetchDebounceTimer = null;
        this.lastSearchPrefetchKey = '';
        this.lastSearchPrefetchPlan = null;
        this.transitionOverlayHideTimer = null;
        this.progressiveJumpSequence = 0;
        this.lastProgressiveJumpPlan = null;
        this.suppressViewportSync = false;

        // Initialize WebWorker for rendering if available
        this.initWorker();

        // Debug / telemetry counters (gated by DEBUG_TILES)
        this.tileDebug = {
            abortedProtocol: 0,
            abortedFetches: 0,
            abortedWorkerJobs: 0,
            workerLutRebuilds: 0
        };

        // Always use client-side rendering for flood tiles
        this.setupCustomProtocol();
        console.log('🚀 Client-side rendering initialized');

        this.init();
    }

    initWorker() {
        // Check if WebWorker is supported
        if (typeof Worker !== 'undefined') {
            try {
                // Cache-bust worker URL alongside other static assets
                const workerUrl = requireFloodmapUrlHelper('floodmapAssetUrl')('/js/render-worker.js');
                this.renderWorker = new Worker(workerUrl);
                this.workerReady = false;
                this.pendingWorkerJobs = new Map();
                this.workerJobId = 0;

                this.renderWorker.onmessage = (e) => {
                    const { type, imageData, error, jobId, pngBuffer, lutRebuilds } = e.data;

                    if (type === 'ready') {
                        this.workerReady = true;
                        console.log('✅ WebWorker ready for tile rendering');
                        try {
                            // Sync debug flag into worker (used for stats messages).
                            this.renderWorker.postMessage({
                                type: 'set-debug',
                                data: { debug: !!window.DEBUG_TILES }
                            });
                        } catch {}
                    } else if (type === 'unsupported') {
                        console.warn('WebWorker rendering unsupported:', error || 'unknown');
                        this.workerReady = false;
                        try { this.renderWorker.terminate(); } catch {}
                    } else if (type === 'stats') {
                        if (typeof lutRebuilds === 'number') this.tileDebug.workerLutRebuilds = lutRebuilds;
                    } else if (type === 'complete' && jobId !== undefined) {
                        const job = this.pendingWorkerJobs.get(jobId);
                        if (job) {
                            if (job.signal?.aborted) {
                                if (window.DEBUG_TILES) this.tileDebug.abortedWorkerJobs++;
                                // Best-effort cancellation: reject with AbortError (no hangs)
                                job.finishReject(new DOMException('Aborted', 'AbortError'));
                                return;
                            }
                            job.finishResolve(pngBuffer ? { pngBuffer } : imageData);
                        }
                    } else if (type === 'error' && jobId !== undefined) {
                        const job = this.pendingWorkerJobs.get(jobId);
                        if (job) {
                            if (job.signal?.aborted) {
                                if (window.DEBUG_TILES) this.tileDebug.abortedWorkerJobs++;
                                job.finishReject(new DOMException('Aborted', 'AbortError'));
                                return;
                            }
                            job.finishReject(new Error(error));
                        }
                    }
                };

                this.renderWorker.onerror = (error) => {
                    console.error('WebWorker error:', error);
                    this.workerReady = false;
                    // Reject all pending jobs to avoid leaks/hangs
                    for (const [, job] of Array.from(this.pendingWorkerJobs.entries())) {
                        job.finishReject(new Error('WebWorker error'));
                    }
                };

            } catch (error) {
                console.warn('Failed to initialize WebWorker, falling back to main thread:', error);
                this.renderWorker = null;
                this.workerReady = false;
            }
        } else {
            console.log('WebWorker not supported, using main thread rendering');
            this.renderWorker = null;
            this.workerReady = false;
        }
    }


    setupCustomProtocol() {
        const self = this;

        // Register a custom protocol with MapLibre (4.7.1+ Promise-based API)
        maplibregl.addProtocol('client', async (params, abortController) => {
            try {
                const signal = abortController?.signal;

                // Parse the request URL
                // Format: client://flood/{z}/{x}/{y}
                const url = params.url.replace('client://', '');
                const parts = url.split('/');

                if ((parts[0] === 'flood' || parts[0] === 'elevation') && parts.length >= 4) {
                    const mode = parts[0];
                    const z = parseInt(parts[1]);
                    const x = parseInt(parts[2]);
                    const y = parseInt(parts[3].split('?')[0]);

                    // Generate tile (logging in production can be removed)

                    // Generate tile based on mode
                    const blob = await self.generateTile(z, x, y, mode, self.currentWaterLevel, signal);

                    const arrayBuffer = await blob.arrayBuffer();
                    return { data: arrayBuffer };
                } else {
                    throw new Error(`Invalid client protocol URL: ${params.url}`);
                }
            } catch (error) {
                if (error?.name === 'AbortError') {
                    if (window.DEBUG_TILES) self.tileDebug.abortedProtocol++;
                    throw error;
                }
                console.error(`Failed to generate tile from ${params.url}:`, error);
                throw error;
            }
        });

        console.log('✅ Client protocol registered successfully');
    }

    async generateTile(z, x, y, mode, waterLevel = null, signal = null) {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

        // Load elevation data
        let elevationData;
        try {
            elevationData = await this.elevationRenderer.loadElevationTile(z, x, y, signal);
        } catch (error) {
            if (error?.name === 'AbortError') {
                if (window.DEBUG_TILES) this.tileDebug.abortedFetches++;
            }
            throw error;
        }

        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

        // Debug logging (development mode only)
        if (window.DEBUG_TILES && Math.random() < 0.05) { // 5% of tiles when debugging enabled
            console.log(`🔍 Debug tile ${z}/${x}/${y}:`, {
                dataLength: elevationData.length,
                first10Values: Array.from(elevationData.slice(0, 10)),
                centerValue: elevationData[128 * 256 + 128],
                decodedCenter: this.elevationRenderer.decodeElevation(elevationData[128 * 256 + 128])
            });
        }

        // Try WebWorker rendering if available
        if (this.workerReady) {
            try {
                const result = await this.renderTileInWorker(elevationData, mode, waterLevel, signal);
                if (result?.pngBuffer) {
                    return new Blob([result.pngBuffer], { type: 'image/png' });
                }
                return this.imageDataToBlob(result, 256, 256);
            } catch (error) {
                if (error?.name === 'AbortError') throw error;
                console.warn('Worker rendering failed, falling back to main thread:', error);
                // Fall through to main thread rendering
            }
        }

        // Main thread rendering (fallback or when worker not available)
        return this.renderTileMainThread(z, x, y, elevationData, mode, waterLevel, signal);
    }

    async renderTileInWorker(elevationData, mode, waterLevel, signal = null) {
        return new Promise((resolve, reject) => {
            const jobId = this.workerJobId++;

            let settled = false;
            const finish = (fn) => {
                if (settled) return;
                settled = true;
                const job = this.pendingWorkerJobs.get(jobId);
                if (job?.abortHandler && job?.signal) {
                    try { job.signal.removeEventListener('abort', job.abortHandler); } catch {}
                }
                this.pendingWorkerJobs.delete(jobId);
                fn();
            };

            const job = {
                jobId,
                signal,
                abortHandler: null,
                finishResolve: (value) => finish(() => resolve(value)),
                finishReject: (err) => finish(() => reject(err)),
            };

            // Allow the promise to reject immediately on abort, otherwise MapLibre
            // can hang waiting on a tile promise that will never settle.
            if (signal) {
                job.abortHandler = () => {
                    if (window.DEBUG_TILES) this.tileDebug.abortedWorkerJobs++;
                    // Best-effort: tell worker to stop early (reduces wasted CPU).
                    try {
                        this.renderWorker.postMessage({ type: 'cancel', jobId });
                    } catch {}
                    job.finishReject(new DOMException('Aborted', 'AbortError'));
                };
                try { signal.addEventListener('abort', job.abortHandler, { once: true }); } catch {}
            }

            this.pendingWorkerJobs.set(jobId, job);

            if (signal?.aborted) {
                if (job.abortHandler) job.abortHandler();
                else job.finishReject(new DOMException('Aborted', 'AbortError'));
                return;
            }

            // Copy only the relevant region (handles non-zero byteOffset safely).
            // Note: We cannot transfer the original cached buffer because it would
            // detach and corrupt the elevationCache entry.
            const buffer = elevationData.buffer.slice(
                elevationData.byteOffset,
                elevationData.byteOffset + elevationData.byteLength
            );
            this.renderWorker.postMessage({
                type: 'render',
                jobId,
                data: {
                    elevationData: buffer,
                    mode,
                    waterLevel,
                    width: 256,
                    height: 256
                }
            }, [buffer]);
        });
    }

    async renderTileMainThread(z, x, y, elevationData, mode, waterLevel, signal = null) {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

        // Create canvas
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 256;
        const ctx = canvas.getContext('2d', { alpha: true });

        // Create image data
        const imageData = ctx.createImageData(256, 256);
        const data = imageData.data;

        // Fast-path: if the entire tile is NODATA, fill with a consistent water/ocean color
        if (this.elevationRenderer.isAllNoData(elevationData)) {
            const fillColor = (mode === 'flood')
                ? this.elevationRenderer.colors.FLOODED
                : this.elevationRenderer.OCEAN_RGBA;
            this.elevationRenderer.fillImageData(imageData, fillColor);
            ctx.putImageData(imageData, 0, 0);
            return new Promise((resolve, reject) => {
                if (signal?.aborted) {
                    reject(new DOMException('Aborted', 'AbortError'));
                    return;
                }
                canvas.toBlob(blob => {
                    if (signal?.aborted) {
                        reject(new DOMException('Aborted', 'AbortError'));
                        return;
                    }
                    blob ? resolve(blob) : reject(new Error(`Failed to create ${mode} tile`));
                }, 'image/png');
            });
        }

        // Process each pixel - simple 1:1 mapping
        let debugColorSample = null;
        for (let i = 0; i < elevationData.length; i++) {
            const elevation = this.elevationRenderer.decodeElevation(elevationData[i]);
            const color = mode === 'elevation'
                ? this.elevationRenderer.calculateElevationColor(elevation)
                : this.elevationRenderer.calculateFloodColor(elevation, waterLevel);

            // Debug: sample first non-transparent color
            if (!debugColorSample && color[3] > 0) {
                debugColorSample = {
                    raw: elevationData[i],
                    elevation,
                    color,
                    mode
                };
            }

            const offset = i * 4;
            data[offset] = color[0];
            data[offset + 1] = color[1];
            data[offset + 2] = color[2];
            data[offset + 3] = color[3];
        }

        // Log debug info (development mode only)
        if (window.DEBUG_TILES && debugColorSample && Math.random() < 0.05) {
            console.log(`🎨 Color sample for tile ${z}/${x}/${y}:`, debugColorSample);
        }

        ctx.putImageData(imageData, 0, 0);

        // Convert to blob
        return new Promise((resolve, reject) => {
            if (signal?.aborted) {
                reject(new DOMException('Aborted', 'AbortError'));
                return;
            }
            canvas.toBlob(blob => {
                if (signal?.aborted) {
                    reject(new DOMException('Aborted', 'AbortError'));
                    return;
                }
                blob ? resolve(blob) : reject(new Error(`Failed to create ${mode} tile`));
            }, 'image/png');
        });
    }

    imageDataToBlob(imageDataBuffer, width, height) {
        // Create canvas and put the ImageData from worker
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');

        const imageData = new ImageData(new Uint8ClampedArray(imageDataBuffer), width, height);
        ctx.putImageData(imageData, 0, 0);

        return new Promise((resolve, reject) => {
            canvas.toBlob(blob => {
                blob ? resolve(blob) : reject(new Error('Failed to create tile blob'));
            }, 'image/png');
        });
    }

    init() {
        this.initializeMap();
        this.setupEventListeners();
    }

    async initializeMap() {
        const config = {
            zoom: 8,
            minZoom: 0,
            maxZoom: 11  // Capped to match precompressed tile availability
        };

        // Determine tile URL based on mode
        const tileUrl = this.getTileUrl();

        this.map = new maplibregl.Map({
            container: 'map',
            style: {
                version: 8,
                sources: {
                    'elevation-tiles': {
                        type: 'raster',
                        tiles: [tileUrl],
                        tileSize: 256,
                        scheme: 'xyz',
                        // Critical: prevent MapLibre from requesting overscaled tiles
                        // beyond our precompressed pyramid (tiles stop at z=11).
                        maxzoom: config.maxZoom
                    },
                    'vector-tiles': {
                        type: 'vector',
                        tiles: [
                            requireFloodmapUrlHelper('floodmapApiUrl')('/v1/tiles/vector/usa/{z}/{x}/{y}.pbf')
                        ],
                        maxzoom: config.maxZoom
                    }
                },
                layers: [
                    {
                        id: 'background',
                        type: 'background',
                        paint: { 'background-color': '#f8f9fa' }
                    },
                    {
                        id: 'elevation',
                        type: 'raster',
                        source: 'elevation-tiles',
                        paint: { 'raster-opacity': 1.0 }
                    },
                    // Water mask: render water polygons above the raster to avoid
                    // discontinuities where DEM has NODATA/artefacts over lakes/ocean.
                    {
                        id: 'water',
                        type: 'fill',
                        source: 'vector-tiles',
                        'source-layer': 'water',
                        // Avoid low-zoom coastline simplification artifacts by NOT
                        // drawing ocean/sea polygons here; ocean is already handled
                        // by raster NODATA. We still keep a hidden ocean hit layer
                        // for click/UX context.
                        filter: [
                            'all',
                            ['!=', ['get', 'class'], 'ocean'],
                            ['!=', ['get', 'class'], 'sea'],
                        ],
                        paint: { 'fill-color': 'rgba(70, 130, 180, 0.85)' }
                    },
                    {
                        id: 'water-ocean-hit',
                        type: 'fill',
                        source: 'vector-tiles',
                        'source-layer': 'water',
                        filter: [
                            'any',
                            ['==', ['get', 'class'], 'ocean'],
                            ['==', ['get', 'class'], 'sea'],
                        ],
                        // Invisible-but-queryable layer for detecting coastal context
                        // without visually drawing simplified ocean polygons.
                        paint: { 'fill-color': 'rgba(70, 130, 180, 0.01)' }
                    },
                    {
                        id: 'waterway',
                        type: 'line',
                        source: 'vector-tiles',
                        'source-layer': 'waterway',
                        paint: { 'line-color': 'rgba(70, 130, 180, 0.85)', 'line-width': 1 }
                    },
                    {
                        id: 'roads',
                        type: 'line',
                        source: 'vector-tiles',
                        'source-layer': 'transportation',
                        paint: { 'line-color': '#6b7280', 'line-width': 1 }
                    }
                ]
            },
            center: [this.initialViewState.lng, this.initialViewState.lat],
            zoom: this.initialViewState.zoom,
            minZoom: config.minZoom,
            maxZoom: config.maxZoom
        });

        // Defensive: ensure runtime maxZoom cannot drift beyond intended cap.
        // This avoids "one extra zoom" blank/empty tiles if MapLibre defaults or
        // style source metadata ever overrides config.
        this.map.setMaxZoom(config.maxZoom);
        this.map.on('zoomend', () => {
            const maxZ = this.map.getMaxZoom();
            if (this.map.getZoom() > maxZ) {
                this.map.setZoom(maxZ);
            }
        });

        this.map.addControl(new maplibregl.NavigationControl(), 'top-right');

        const zoomDebug = document.getElementById('zoom-debug');
        const updateZoomDebug = () => {
            if (!zoomDebug) return;
            zoomDebug.textContent = `Zoom: ${this.map.getZoom().toFixed(3)} (max ${this.map.getMaxZoom()})`;
        };
        updateZoomDebug();
        this.map.on('zoom', updateZoomDebug);

        this.map.on('click', (e) => {
            this.assessLocationRisk(e.lngLat.lat, e.lngLat.lng, e.lngLat);
        });

        // Track viewport when user stops panning/zooming
        this.map.on('moveend', () => {
            if (this.suppressViewportSync) return;
            this.schedulePermalinkUpdate();
            this.trackViewportView();
        });

        // Track initial viewport on load
        this.map.on('load', () => {
            if (this.initialViewState.hasExplicitState) {
                this.syncPermalinkWithMap();
            }
            this.trackViewportView();
        });
    }

    getTileUrl() {
        if (this.viewMode === 'elevation') {
            // Client-side elevation rendering (no server requests)
            return 'client://elevation/{z}/{x}/{y}';
        } else {
            // Client-side flood rendering
            // Include clustered water level in URL to bust MapLibre's tile cache on level change
            const clusteredWL = Math.round(this.currentWaterLevel * 10) / 10;
            return `client://flood/{z}/{x}/{y}?wl=${clusteredWL}`;
        }
    }

    setupEventListeners() {
        const locationSearchForm = document.getElementById('location-search-form');
        const locationSearchInput = document.getElementById('location-search');
        if (locationSearchForm && locationSearchInput) {
            locationSearchForm.addEventListener('submit', (e) => {
                e.preventDefault();
                void this.handleLocationSearch(locationSearchInput.value);
            });
            locationSearchInput.addEventListener('input', () => {
                this.setActiveSearchResultIndex(-1, { scrollIntoView: false });
                this.scheduleLocationTypeahead(locationSearchInput.value);
            });
            locationSearchInput.addEventListener('keydown', (e) => {
                const hasResults = this.searchResults.length > 0;
                if ((e.key === 'ArrowDown' || e.key === 'Down') && hasResults) {
                    e.preventDefault();
                    this.moveActiveSearchResult(1);
                    return;
                }
                if ((e.key === 'ArrowUp' || e.key === 'Up') && hasResults) {
                    e.preventDefault();
                    this.moveActiveSearchResult(-1);
                    return;
                }
                if (e.key === 'Enter' && this.activeSearchResultIndex >= 0) {
                    const activeResult = this.searchResults[this.activeSearchResultIndex];
                    if (activeResult) {
                        e.preventDefault();
                        this.selectSearchResult(activeResult);
                    }
                    return;
                }
                if (e.key === 'Escape' && hasResults) {
                    e.preventDefault();
                    this.dismissSearchResults({ clearStatus: true });
                }
            });
        }

        // View mode radio buttons
        const viewModeRadios = document.querySelectorAll('input[name="view-mode"]');
        this.syncViewModeControls();
        viewModeRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                this.viewMode = e.target.value;
                this.updateViewMode();
                this.updateModelNote(this.modelNoteState);
                this.schedulePermalinkUpdate();
            });
        });

        // Water level slider
        const waterLevelSlider = document.getElementById('water-level');
        const waterLevelDisplay = document.getElementById('water-level-display');
        const waterLevelVibe = document.getElementById('water-level-vibe');

        if (waterLevelSlider && waterLevelDisplay && waterLevelVibe) {
            waterLevelSlider.addEventListener('input', (e) => {
                const sliderValue = parseFloat(e.target.value);
                const oldWaterLevel = this.currentWaterLevel;
                this.currentWaterLevel = this.sliderToWaterLevel(sliderValue);

                waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
                this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);
                this.updateActivePresetChip();

                // Only update if water level actually changed
                if (oldWaterLevel !== this.currentWaterLevel) {
                    this.updateFloodLayer();
                    this.schedulePermalinkUpdate();
                }
            });
        }
        this.syncWaterLevelControls();

        // Water level preset chips
        const presetChips = document.querySelectorAll('.preset-chip');
        presetChips.forEach(chip => {
            chip.addEventListener('click', (e) => {
                const targetLevel = parseFloat(e.target.dataset.level);

                // Update slider position
                const sliderValue = this.waterLevelToSlider(targetLevel);
                waterLevelSlider.value = sliderValue;

                // Update water level
                const oldWaterLevel = this.currentWaterLevel;
                this.currentWaterLevel = targetLevel;

                this.syncWaterLevelControls();

                // Trigger flood layer update if level changed
                if (oldWaterLevel !== this.currentWaterLevel) {
                    this.updateFloodLayer();
                    this.schedulePermalinkUpdate();
                }
            });
        });

        const shareButton = document.getElementById('share-view-button');
        if (shareButton) {
            shareButton.addEventListener('click', () => {
                void this.copyShareLink();
            });
        }

        // Find location button
        document.getElementById('find-location').addEventListener('click', () => {
            this.findUserLocation();
        });

        window.addEventListener('popstate', () => {
            this.applyPermalinkStateFromCurrentUrl();
        });

        // Status display can be added for debugging if needed

        // Wait for map to be loaded before initial update
        if (this.map && this.map.loaded()) {
            this.updateViewMode();
        } else {
            this.map.on('load', () => {
                this.updateViewMode();
            });
        }
    }

    syncViewModeControls() {
        document.querySelectorAll('input[name="view-mode"]').forEach((radio) => {
            radio.checked = radio.value === this.viewMode;
        });
    }

    syncWaterLevelControls() {
        const waterLevelSlider = document.getElementById('water-level');
        const waterLevelDisplay = document.getElementById('water-level-display');
        const waterLevelVibe = document.getElementById('water-level-vibe');

        if (waterLevelSlider) {
            waterLevelSlider.value = String(this.waterLevelToSlider(this.currentWaterLevel));
        }
        if (waterLevelDisplay) {
            waterLevelDisplay.textContent = `${this.currentWaterLevel}m`;
        }
        if (waterLevelVibe) {
            this.updateWaterLevelVibe(this.currentWaterLevel, waterLevelVibe);
        }

        this.updateActivePresetChip();
    }

    updateActivePresetChip() {
        document.querySelectorAll('.preset-chip').forEach((chip) => {
            const level = Number.parseFloat(chip.dataset.level);
            const isActive = Number.isFinite(level) && Math.abs(level - this.currentWaterLevel) < 0.05;
            chip.classList.toggle('active', isActive);
        });
    }


    updateViewMode() {
        const waterLevelControls = document.getElementById('water-level-controls');
        const floodLegend = document.getElementById('flood-legend');
        const elevationLegend = document.getElementById('elevation-legend');

        this.updateModelNote(this.modelNoteState);

        if (this.viewMode === 'elevation') {
            waterLevelControls.style.opacity = '0';
            waterLevelControls.style.transform = 'translateY(-10px)';
            setTimeout(() => {
                waterLevelControls.style.display = 'none';
            }, 200);

            // Show elevation legend, hide flood legend
            if (floodLegend) floodLegend.style.display = 'none';
            if (elevationLegend) elevationLegend.style.display = 'flex';
        } else {
            waterLevelControls.style.display = 'block';
            setTimeout(() => {
                waterLevelControls.style.opacity = '1';
                waterLevelControls.style.transform = 'translateY(0)';
            }, 10);

            // Show flood legend, hide elevation legend
            if (elevationLegend) elevationLegend.style.display = 'none';
            if (floodLegend) floodLegend.style.display = 'flex';
        }

        this.updateFloodLayer();
    }

    updateFloodLayer() {
        if (!this.map || !this.map.loaded()) {
            return;
        }

        const source = this.map.getSource('elevation-tiles');
        if (!source) return;

        if (this.viewMode === 'flood') {
            // Clear the renderer cache to force re-render with new water level
            if (this.elevationRenderer) {
                this.elevationRenderer.clearRenderedCache();
            }

            // Use getTileUrl() to include water level in URL, busting MapLibre's cache
            source.setTiles([this.getTileUrl()]);
        } else {
            source.setTiles([this.getTileUrl()]);
        }
    }

    sliderToWaterLevel(sliderValue) {
        const waterLevel = 0.1 * Math.pow(10, sliderValue / 25);
        return Math.round(waterLevel * 10) / 10;
    }

    waterLevelToSlider(waterLevel) {
        // Inverse of sliderToWaterLevel
        // waterLevel = 0.1 * 10^(slider/25)
        // waterLevel / 0.1 = 10^(slider/25)
        // log10(waterLevel / 0.1) = slider/25
        // slider = 25 * log10(waterLevel / 0.1)
        return 25 * Math.log10(waterLevel / 0.1);
    }

    getCurrentViewState() {
        const center = this.map ? this.map.getCenter() : {
            lat: this.initialViewState.lat,
            lng: this.initialViewState.lng
        };
        const zoom = this.map ? this.map.getZoom() : this.initialViewState.zoom;

        return {
            lat: center.lat,
            lng: center.lng,
            zoom,
            view: this.viewMode,
            water: this.currentWaterLevel
        };
    }

    buildShareUrl({ includeDefaults = true } = {}) {
        const urlState = requireFloodmapGlobal('FloodmapUrlState');
        const currentViewState = this.getCurrentViewState();

        if (!includeDefaults && urlState.isDefaultViewState(currentViewState, this.defaultViewState)) {
            return urlState.stripFloodmapStateParams(window.location.href);
        }

        return urlState.buildFloodmapShareUrl(
            window.location.href,
            currentViewState,
            this.defaultViewState
        );
    }

    schedulePermalinkUpdate() {
        if (this.pendingPermalinkFrame) return;

        this.pendingPermalinkFrame = window.requestAnimationFrame(() => {
            this.pendingPermalinkFrame = null;
            this.syncPermalinkWithMap();
        });
    }

    syncPermalinkWithMap() {
        const nextUrl = this.buildShareUrl({ includeDefaults: false });
        if (nextUrl === window.location.href) return;
        window.history.replaceState(window.history.state, '', nextUrl);
    }

    applyPermalinkStateFromCurrentUrl() {
        const urlState = requireFloodmapGlobal('FloodmapUrlState');
        const nextState = urlState.parseFloodmapUrlState(
            window.location.href,
            this.defaultViewState
        );

        this.initialViewState = nextState;
        this.currentWaterLevel = nextState.water;
        this.viewMode = nextState.view;
        this.syncViewModeControls();
        this.syncWaterLevelControls();
        this.updateViewMode();

        if (this.map) {
            this.map.jumpTo({
                center: [nextState.lng, nextState.lat],
                zoom: nextState.zoom
            });
        }
    }

    async copyShareLink() {
        const shareUrl = this.buildShareUrl({ includeDefaults: true });

        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(shareUrl);
            } else {
                this.copyTextFallback(shareUrl);
            }
            this.updateShareStatus('Share link copied.', 'success');
        } catch (error) {
            console.warn('Share link copy failed:', error);
            this.updateShareStatus(
                'Copy failed. Use the address bar URL instead.',
                'error'
            );
        }
    }

    copyTextFallback(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'absolute';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);

        const copied = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (!copied) {
            throw new Error('document.execCommand(copy) returned false');
        }
    }

    updateShareStatus(message = '', state = '') {
        const status = document.getElementById('share-view-status');
        if (!status) return;

        status.textContent = message;
        status.className = 'share-status';
        if (state) {
            status.classList.add(`is-${state}`);
        }

        if (this.shareStatusResetTimer) {
            window.clearTimeout(this.shareStatusResetTimer);
            this.shareStatusResetTimer = null;
        }

        if (message) {
            this.shareStatusResetTimer = window.setTimeout(() => {
                status.textContent = '';
                status.className = 'share-status';
                this.shareStatusResetTimer = null;
            }, 3200);
        }
    }

    getTileCoordinates(lat, lng, zoom) {
        // Convert lat/lng to tile coordinates using Web Mercator projection
        const n = Math.pow(2, zoom);
        const x = Math.floor(n * ((lng + 180) / 360));
        const latRad = lat * Math.PI / 180;
        const y = Math.floor(n * (1 - (Math.log(Math.tan(latRad) + (1 / Math.cos(latRad))) / Math.PI)) / 2);
        return { x, y };
    }

    getMapViewportSize() {
        const container = this.map?.getContainer?.();
        return {
            width: Math.max(256, container?.clientWidth || 0),
            height: Math.max(256, container?.clientHeight || 0)
        };
    }

    captureMapFrameDataUrl() {
        const canvas = this.map?.getCanvas?.();
        if (!canvas) return '';

        try {
            const dataUrl = canvas.toDataURL('image/png');
            return typeof dataUrl === 'string' && dataUrl.startsWith('data:image/')
                ? dataUrl
                : '';
        } catch (error) {
            console.warn('Map frame capture failed:', error);
            return '';
        }
    }

    showMapTransitionOverlay() {
        const overlay = document.getElementById('map-transition-overlay');
        const image = document.getElementById('map-transition-overlay-image');
        if (!overlay || !image) return;

        if (this.transitionOverlayHideTimer) {
            window.clearTimeout(this.transitionOverlayHideTimer);
            this.transitionOverlayHideTimer = null;
        }

        const snapshotUrl = this.captureMapFrameDataUrl();
        if (snapshotUrl) {
            image.src = snapshotUrl;
        } else {
            image.removeAttribute('src');
        }

        overlay.hidden = false;
        overlay.dataset.state = 'active';
        overlay.classList.remove('is-exiting');
        overlay.classList.add('is-active');
    }

    refreshMapTransitionOverlayFrame() {
        const overlay = document.getElementById('map-transition-overlay');
        const image = document.getElementById('map-transition-overlay-image');
        if (!overlay || !image || overlay.hidden) return false;

        const snapshotUrl = this.captureMapFrameDataUrl();
        if (!snapshotUrl) return false;

        image.src = snapshotUrl;
        overlay.dataset.state = 'active';
        overlay.classList.remove('is-exiting');
        overlay.classList.add('is-active');
        return true;
    }

    hideMapTransitionOverlay({ immediate = false } = {}) {
        const overlay = document.getElementById('map-transition-overlay');
        const image = document.getElementById('map-transition-overlay-image');
        if (!overlay) return;

        const finalize = () => {
            overlay.hidden = true;
            overlay.dataset.state = 'hidden';
            overlay.classList.remove('is-active', 'is-exiting');
            image?.removeAttribute('src');
            this.transitionOverlayHideTimer = null;
        };

        if (this.transitionOverlayHideTimer) {
            window.clearTimeout(this.transitionOverlayHideTimer);
            this.transitionOverlayHideTimer = null;
        }

        if (immediate || overlay.hidden) {
            finalize();
            return;
        }

        overlay.dataset.state = 'exiting';
        overlay.classList.remove('is-active');
        overlay.classList.add('is-exiting');
        this.transitionOverlayHideTimer = window.setTimeout(finalize, 220);
    }

    waitForMapIdle(timeoutMs = 1800) {
        return new Promise((resolve) => {
            if (!this.map) {
                resolve(false);
                return;
            }

            let settled = false;
            const finish = (didIdle) => {
                if (settled) return;
                settled = true;
                window.clearTimeout(timer);
                this.map.off('idle', onIdle);
                resolve(didIdle);
            };
            const onIdle = () => finish(true);
            const timer = window.setTimeout(() => finish(false), timeoutMs);

            this.map.on('idle', onIdle);
        });
    }

    async prefetchElevationTilesProgressively(
        tiles,
        { shouldContinue = null, concurrency = 4 } = {}
    ) {
        const queue = Array.isArray(tiles)
            ? tiles.filter((tile) => Number.isInteger(tile?.z) && Number.isInteger(tile?.x) && Number.isInteger(tile?.y))
            : [];
        if (!queue.length) return;

        let index = 0;
        const workerCount = Math.max(1, Math.min(concurrency, queue.length));
        const worker = async () => {
            while (index < queue.length) {
                if (typeof shouldContinue === 'function' && !shouldContinue()) return;
                const tile = queue[index];
                index += 1;
                try {
                    await this.elevationRenderer.loadElevationTile(tile.z, tile.x, tile.y);
                } catch (error) {
                    if (error?.name !== 'AbortError') {
                        console.warn('Destination tile prefetch failed:', error);
                    }
                }
            }
        };

        await Promise.all(Array.from({ length: workerCount }, () => worker()));
    }

    buildProgressiveJumpPlanForTarget(targetCamera) {
        if (!targetCamera || !this.map) {
            return {
                distanceKm: 0,
                zoomDelta: 0,
                useProgressive: false,
                stageZoom: 0,
                requiresFinalRefine: false,
                prefetchTiles: []
            };
        }

        const currentCenter = this.map.getCenter();
        const currentZoom = this.map.getZoom();
        const viewport = this.getMapViewportSize();

        return this.jumpPlanner.buildProgressiveJumpPlan({
            currentCenter: {
                lat: currentCenter.lat,
                lng: currentCenter.lng
            },
            currentZoom,
            targetCenter: targetCamera.center,
            targetZoom: targetCamera.zoom,
            viewportWidth: viewport.width,
            viewportHeight: viewport.height
        });
    }

    cancelSearchResultPrefetch({ clearPlan = true } = {}) {
        if (this.searchPrefetchDebounceTimer) {
            window.clearTimeout(this.searchPrefetchDebounceTimer);
            this.searchPrefetchDebounceTimer = null;
        }

        this.searchPrefetchSequence += 1;

        if (clearPlan) {
            this.lastSearchPrefetchKey = '';
            this.lastSearchPrefetchPlan = null;
        }
    }

    scheduleSearchResultPrefetch(result, { immediate = false } = {}) {
        if (!result || !this.map) return;

        const targetCamera = this.getSearchTargetCamera(
            result,
            this.getSearchBounds(result)
        );
        const plan = this.buildProgressiveJumpPlanForTarget(targetCamera);
        if (!plan.useProgressive || !plan.prefetchTiles.length) return;

        const prefetchTiles = plan.prefetchTiles.slice(0, 8);
        const prefetchKey = [
            result?.name || '',
            result?.label || '',
            targetCamera.kind,
            targetCamera.zoom.toFixed(2),
            prefetchTiles.map((tile) => `${tile.z}/${tile.x}/${tile.y}`).join(',')
        ].join('|');

        if (prefetchKey === this.lastSearchPrefetchKey) {
            return;
        }

        this.cancelSearchResultPrefetch({ clearPlan: false });
        const sequence = this.searchPrefetchSequence;
        this.lastSearchPrefetchKey = prefetchKey;
        this.lastSearchPrefetchPlan = {
            ...plan,
            targetKind: targetCamera.kind,
            targetZoom: targetCamera.zoom,
            targetCenter: targetCamera.center,
            prefetchTiles
        };

        const runPrefetch = () => {
            this.searchPrefetchDebounceTimer = null;
            void this.prefetchElevationTilesProgressively(
                prefetchTiles,
                {
                    shouldContinue: () => sequence === this.searchPrefetchSequence,
                    concurrency: 2
                }
            );
        };

        if (immediate) {
            runPrefetch();
            return;
        }

        this.searchPrefetchDebounceTimer = window.setTimeout(runPrefetch, 140);
    }

    getSearchTargetCamera(result, bounds = null) {
        const maxZoom = this.map?.getMaxZoom?.() ?? 11;
        if (bounds) {
            const fitBoundsOptions = {
                duration: 1100,
                padding: { top: 64, right: 64, bottom: 64, left: 64 },
                maxZoom
            };
            let center = {
                lat: (bounds.south + bounds.north) / 2,
                lng: (bounds.west + bounds.east) / 2
            };
            let zoom = Math.min(maxZoom, this.map?.getZoom?.() ?? 8);

            if (this.map && typeof this.map.cameraForBounds === 'function') {
                try {
                    const camera = this.map.cameraForBounds(
                        [
                            [bounds.west, bounds.south],
                            [bounds.east, bounds.north]
                        ],
                        {
                            padding: fitBoundsOptions.padding,
                            maxZoom
                        }
                    );

                    if (camera?.center) {
                        if (Array.isArray(camera.center) && camera.center.length >= 2) {
                            center = {
                                lng: Number(camera.center[0]),
                                lat: Number(camera.center[1])
                            };
                        } else if (
                            Number.isFinite(camera.center.lng)
                            && Number.isFinite(camera.center.lat)
                        ) {
                            center = {
                                lng: camera.center.lng,
                                lat: camera.center.lat
                            };
                        }
                    }
                    if (Number.isFinite(camera?.zoom)) {
                        zoom = camera.zoom;
                    }
                } catch (error) {
                    console.warn('cameraForBounds failed; falling back to center average:', error);
                }
            }

            return {
                kind: 'bounds',
                center,
                zoom: Math.min(maxZoom, zoom),
                bounds,
                fitBoundsOptions
            };
        }

        return {
            kind: 'point',
            center: {
                lng: result.longitude,
                lat: result.latitude
            },
            zoom: Math.min(maxZoom, 10.5),
            flyToOptions: {
                essential: true,
                duration: 1100
            }
        };
    }

    animateToSearchTarget(targetCamera, overrides = {}) {
        if (!this.map || !targetCamera) return;

        if (targetCamera.kind === 'bounds') {
            this.map.fitBounds(
                [
                    [targetCamera.bounds.west, targetCamera.bounds.south],
                    [targetCamera.bounds.east, targetCamera.bounds.north]
                ],
                {
                    ...targetCamera.fitBoundsOptions,
                    ...overrides
                }
            );
            return;
        }

        this.map.flyTo({
            center: [targetCamera.center.lng, targetCamera.center.lat],
            zoom: targetCamera.zoom,
            ...targetCamera.flyToOptions,
            ...overrides
        });
    }

    async transitionToSearchTarget(targetCamera) {
        if (!targetCamera || !this.map) return;

        const plan = this.buildProgressiveJumpPlanForTarget(targetCamera);

        this.lastProgressiveJumpPlan = {
            ...plan,
            targetKind: targetCamera.kind,
            targetZoom: targetCamera.zoom,
            targetCenter: targetCamera.center
        };

        const sequence = this.progressiveJumpSequence + 1;
        this.progressiveJumpSequence = sequence;

        if (!plan.useProgressive) {
            this.suppressViewportSync = false;
            this.hideMapTransitionOverlay({ immediate: true });
            this.animateToSearchTarget(targetCamera);
            return;
        }

        this.showMapTransitionOverlay();
        this.suppressViewportSync = true;

        const prefetchPromise = this.prefetchElevationTilesProgressively(
            plan.prefetchTiles,
            {
                shouldContinue: () => sequence === this.progressiveJumpSequence
            }
        );

        this.map.jumpTo({
            center: [targetCamera.center.lng, targetCamera.center.lat],
            zoom: plan.stageZoom,
            essential: true
        });

        await Promise.allSettled([
            prefetchPromise,
            this.waitForMapIdle(1800)
        ]);

        if (sequence !== this.progressiveJumpSequence) return;

        if (!plan.requiresFinalRefine && targetCamera.kind !== 'bounds') {
            this.hideMapTransitionOverlay();
            this.suppressViewportSync = false;
            this.schedulePermalinkUpdate();
            this.trackViewportView();
            return;
        }

        this.refreshMapTransitionOverlayFrame();
        this.animateToSearchTarget(targetCamera, { duration: 850 });

        await this.waitForMapIdle(2400);
        if (sequence !== this.progressiveJumpSequence) return;

        this.hideMapTransitionOverlay();
        this.suppressViewportSync = false;
        this.schedulePermalinkUpdate();
        this.trackViewportView();
    }

    cancelLocationTypeahead() {
        if (this.locationSearchDebounceTimer) {
            window.clearTimeout(this.locationSearchDebounceTimer);
            this.locationSearchDebounceTimer = null;
        }
    }

    abortLocationSearch({ resetLoading = false } = {}) {
        if (this.locationSearchAbortController) {
            this.locationSearchAbortController.abort();
            this.locationSearchAbortController = null;
        }
        if (resetLoading) {
            this.setSearchLoading(false);
        }
    }

    scheduleLocationTypeahead(query) {
        const normalizedQuery = String(query || '').trim();
        this.cancelLocationTypeahead();

        if (!normalizedQuery || normalizedQuery.length < 2) {
            this.abortLocationSearch({ resetLoading: true });
            this.cancelSearchResultPrefetch();
            this.clearSearchResults();
            this.updateSearchStatus('', '');
            return;
        }

        this.locationSearchDebounceTimer = window.setTimeout(() => {
            this.locationSearchDebounceTimer = null;
            void this.fetchLocationMatches(normalizedQuery, { mode: 'typeahead' });
        }, 220);
    }

    async handleLocationSearch(query) {
        this.cancelLocationTypeahead();
        await this.fetchLocationMatches(query, { mode: 'submit' });
    }

    async fetchLocationMatches(query, { mode = 'submit' } = {}) {
        const normalizedQuery = String(query || '').trim();
        const isTypeahead = mode === 'typeahead';
        if (!normalizedQuery) {
            this.clearSearchResults();
            this.updateSearchStatus('Enter a US ZIP code or city.', 'error');
            return;
        }

        if (normalizedQuery.length < 2) {
            if (!isTypeahead) {
                this.clearSearchResults();
                this.updateSearchStatus('Enter at least 2 characters.', 'error');
            }
            return;
        }

        this.abortLocationSearch();

        const controller = new AbortController();
        this.locationSearchAbortController = controller;
        this.setSearchLoading(true, { disableButton: !isTypeahead });
        if (!isTypeahead) {
            this.clearSearchResults();
            this.updateSearchStatus(`Searching for "${normalizedQuery}"...`, 'loading');
        } else {
            this.updateSearchStatus('', '');
        }

        try {
            const searchUrl = new URL(
                requireFloodmapUrlHelper('floodmapApiUrl')('/places/search'),
                window.location.origin
            );
            searchUrl.searchParams.set('q', normalizedQuery);

            const response = await fetch(searchUrl.toString(), { signal: controller.signal });

            let payload = null;
            try {
                payload = await response.json();
            } catch {
                payload = null;
            }

            if (!response.ok) {
                throw new Error(payload?.detail || 'Location search failed');
            }

            const results = Array.isArray(payload?.results) ? payload.results : [];
            if (!results.length) {
                this.cancelSearchResultPrefetch();
                this.clearSearchResults();
                if (isTypeahead) {
                    this.updateSearchStatus('', '');
                } else {
                    this.updateSearchStatus(`No US matches found for "${normalizedQuery}".`, 'error');
                }
                return;
            }

            if (!isTypeahead && results.length === 1) {
                this.selectSearchResult(results[0]);
                return;
            }

            this.renderSearchResults(results);
            if (isTypeahead) {
                this.updateSearchStatus('', '');
            } else {
                this.updateSearchStatus(`Choose a match for "${normalizedQuery}".`, 'success');
            }
        } catch (error) {
            if (error?.name === 'AbortError') {
                return;
            }

            console.error('Location search error:', error);
            this.updateSearchStatus(error?.message || 'Location search failed.', 'error');
        } finally {
            if (this.locationSearchAbortController === controller) {
                this.locationSearchAbortController = null;
                this.setSearchLoading(false, { disableButton: !isTypeahead });
            }
        }
    }

    createSearchResultsSignature(results) {
        if (!Array.isArray(results) || !results.length) {
            return '';
        }

        return results.map((result) => {
            const name = result?.name || '';
            const label = result?.label || '';
            const latitude = Number.isFinite(result?.latitude) ? result.latitude.toFixed(5) : '';
            const longitude = Number.isFinite(result?.longitude) ? result.longitude.toFixed(5) : '';
            return `${name}|${label}|${latitude}|${longitude}`;
        }).join('||');
    }

    renderSearchResults(results) {
        const container = document.getElementById('location-search-results');
        if (!container) return;

        const normalizedResults = Array.isArray(results) ? results : [];
        const nextSignature = this.createSearchResultsSignature(normalizedResults);
        this.searchResults = normalizedResults;
        this.activeSearchResultIndex = -1;

        if (
            this.searchResultsSignature === nextSignature
            && container.childElementCount === normalizedResults.length
        ) {
            this.syncSearchResultsA11y();
            this.scheduleSearchResultPrefetch(normalizedResults[0]);
            return;
        }

        const fragment = document.createDocumentFragment();
        normalizedResults.forEach((result, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'search-result';
            button.id = `location-search-result-${index}`;
            button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', 'false');
            button.tabIndex = -1;

            const name = document.createElement('span');
            name.className = 'search-result__name';
            name.textContent = result.name || result.label || 'Unknown location';

            const meta = document.createElement('span');
            meta.className = 'search-result__meta';
            meta.textContent = result.label || 'Unnamed place';

            button.appendChild(name);
            button.appendChild(meta);
            button.addEventListener('click', () => {
                this.selectSearchResult(result);
            });
            button.addEventListener('mouseenter', () => {
                this.setActiveSearchResultIndex(index, { scrollIntoView: false });
            });

            fragment.appendChild(button);
        });
        container.replaceChildren(fragment);
        this.searchResultsSignature = nextSignature;
        this.syncSearchResultsA11y();
        this.scheduleSearchResultPrefetch(normalizedResults[0]);
    }

    clearSearchResults() {
        const container = document.getElementById('location-search-results');
        if (container && container.childElementCount) {
            container.replaceChildren();
        }
        this.cancelSearchResultPrefetch();
        this.searchResults = [];
        this.searchResultsSignature = '';
        this.activeSearchResultIndex = -1;
        this.syncSearchResultsA11y();
    }

    dismissSearchResults({ clearStatus = false } = {}) {
        this.cancelLocationTypeahead();
        this.abortLocationSearch({ resetLoading: true });
        this.clearSearchResults();
        if (clearStatus) {
            this.updateSearchStatus('', '');
        }
    }

    syncSearchResultsA11y() {
        const input = document.getElementById('location-search');
        const container = document.getElementById('location-search-results');
        if (!input || !container) return;

        const hasResults = this.searchResults.length > 0;
        input.setAttribute('aria-expanded', hasResults ? 'true' : 'false');

        const options = Array.from(container.querySelectorAll('.search-result'));
        options.forEach((option, index) => {
            const isActive = index === this.activeSearchResultIndex;
            option.classList.toggle('is-active', isActive);
            option.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });

        if (this.activeSearchResultIndex >= 0 && this.activeSearchResultIndex < options.length) {
            input.setAttribute('aria-activedescendant', options[this.activeSearchResultIndex].id);
        } else {
            input.removeAttribute('aria-activedescendant');
        }
    }

    setActiveSearchResultIndex(index, { scrollIntoView = true } = {}) {
        if (!this.searchResults.length) {
            this.activeSearchResultIndex = -1;
            this.syncSearchResultsA11y();
            return;
        }

        if (!Number.isInteger(index) || index < 0 || index >= this.searchResults.length) {
            this.activeSearchResultIndex = -1;
            this.syncSearchResultsA11y();
            return;
        }

        this.activeSearchResultIndex = index;
        this.syncSearchResultsA11y();
        this.scheduleSearchResultPrefetch(this.searchResults[index], { immediate: true });

        if (!scrollIntoView) return;
        const activeOption = document.getElementById(`location-search-result-${index}`);
        activeOption?.scrollIntoView?.({ block: 'nearest' });
    }

    moveActiveSearchResult(direction) {
        if (!this.searchResults.length) return;

        const lastIndex = this.searchResults.length - 1;
        if (this.activeSearchResultIndex === -1) {
            this.setActiveSearchResultIndex(direction > 0 ? 0 : lastIndex);
            return;
        }

        const nextIndex = Math.min(
            lastIndex,
            Math.max(0, this.activeSearchResultIndex + direction)
        );
        this.setActiveSearchResultIndex(nextIndex);
    }

    updateSearchStatus(message = '', state = '') {
        const status = document.getElementById('location-search-status');
        if (!status) return;

        const nextMessage = message || '';
        const nextClassName = state ? `search-status is-${state}` : 'search-status';
        if (status.textContent === nextMessage && status.className === nextClassName) {
            return;
        }

        status.textContent = nextMessage;
        status.className = nextClassName;
    }

    setSearchLoading(isLoading, { disableButton = true } = {}) {
        const button = document.getElementById('location-search-button');
        if (!button) return;

        const nextDisabled = Boolean(disableButton && isLoading);
        const nextText = nextDisabled ? '...' : 'Go';
        if (button.disabled !== nextDisabled) {
            button.disabled = nextDisabled;
        }
        if (button.textContent !== nextText) {
            button.textContent = nextText;
        }
    }

    selectSearchResult(result) {
        if (!result || !this.map) return;
        this.cancelLocationTypeahead();
        this.abortLocationSearch({ resetLoading: true });
        this.cancelSearchResultPrefetch();
        this.setActiveSearchResultIndex(-1, { scrollIntoView: false });

        const searchInput = document.getElementById('location-search');
        if (searchInput && result.name) {
            searchInput.value = result.name;
        }

        this.clearSearchResults();
        this.updateSearchStatus(
            `Showing ${result.name || result.label}. Click the map for a precise flood-risk sample.`,
            'success'
        );
        this.updateRiskPanelForSearch(result);
        this.updateLocationInfoForSearch(result);
        this.showSearchMarker(result);

        const bounds = this.getSearchBounds(result);
        const targetCamera = this.getSearchTargetCamera(result, bounds);
        void this.transitionToSearchTarget(targetCamera);
    }

    getSearchBounds(result) {
        const bounds = result?.bounds;
        if (!bounds) return null;

        const south = Number(bounds.south);
        const north = Number(bounds.north);
        const west = Number(bounds.west);
        const east = Number(bounds.east);

        if (![south, north, west, east].every(Number.isFinite)) {
            return null;
        }

        return { south, north, west, east };
    }

    updateRiskPanelForSearch(result) {
        const riskDetails = document.getElementById('risk-details');
        if (!riskDetails) return;

        const name = this.escapeHtml(result.name || result.label || 'Selected location');
        const label = this.escapeHtml(result.label || result.name || 'Selected location');

        riskDetails.innerHTML = `
            <div class="risk-summary risk-search">
                <strong>Showing: ${name}</strong>
            </div>
            <p><strong>Location:</strong> ${label}</p>
            <p><strong>Next step:</strong> Click any point on the map to sample elevation and flood risk there.</p>
        `;
    }

    updateLocationInfoForSearch(result) {
        const locationInfo = document.getElementById('location-info');
        if (!locationInfo) return;

        locationInfo.textContent = `🔎 ${result.name || result.label} • ${Number(result.latitude).toFixed(4)}°, ${Number(result.longitude).toFixed(4)}°`;
    }

    showSearchMarker(result) {
        this.clearMapMarkers();

        new maplibregl.Marker({ color: '#2563eb' })
            .setLngLat([result.longitude, result.latitude])
            .setPopup(new maplibregl.Popup().setHTML(`
                <div>
                    <strong>${this.escapeHtml(result.name || result.label || 'Selected location')}</strong><br>
                    ${this.escapeHtml(result.label || result.name || 'Selected location')}
                </div>
            `))
            .addTo(this.map);
    }

    updateWaterLevelVibe(waterLevel, vibeElement) {
        vibeElement.className = '';

        let vibeText = '';
        let vibeClass = '';

        if (waterLevel <= 2) {
            vibeText = 'Normal';
            vibeClass = 'vibe-normal';
        } else if (waterLevel <= 5) {
            vibeText = 'Concerning';
            vibeClass = 'vibe-concerning';
        } else if (waterLevel <= 20) {
            vibeText = 'Dangerous';
            vibeClass = 'vibe-dangerous';
        } else if (waterLevel <= 100) {
            vibeText = 'EXTREME';
            vibeClass = 'vibe-extreme';
        } else {
            vibeText = 'APOCALYPTIC';
            vibeClass = 'vibe-apocalyptic';
        }

        vibeElement.textContent = vibeText;
        vibeElement.className = vibeClass;
    }

    async findUserLocation() {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    const lat = position.coords.latitude;
                    const lng = position.coords.longitude;

                    this.map.setCenter([lng, lat]);
                    this.map.setZoom(this.map.getMaxZoom());
                    this.assessLocationRisk(lat, lng);
                },
                (error) => {
                    console.warn('Geolocation error:', error);
                    alert('Could not get your location. Please click on the map instead.');
                }
            );
        } else {
            alert('Geolocation is not supported by this browser.');
        }
    }

    async assessLocationRisk(lat, lng, lngLat = null) {
        // Track location view in Umami (raw lat/lon as requested)
        this.trackLocationView(lat, lng);

        try {
            // Calculate tile coordinates for current zoom level if lngLat provided
            let tileInfo = '';
            if (lngLat && this.map) {
                const zoom = Math.floor(this.map.getZoom());
                const tileCoords = this.getTileCoordinates(lat, lng, zoom);
                const tilePath = `/api/v1/tiles/elevation-data/${zoom}/${tileCoords.x}/${tileCoords.y}.u16`;
                tileInfo = `🗂️ Tile: ${zoom}/${tileCoords.x}/${tileCoords.y} (${tilePath})`;
            }

            // Water/coastal context detection via rendered vector tiles (simple + fast).
            // If we're clicking on a lake/ocean polygon, show "Water" rather than
            // a misleading land-based risk from DEM artefacts.
            let isWater = false;
            let isCoastal = false;
            if (this.map) {
                const point = this.map.project([lng, lat]);
                const pad = 2; // small tolerance for edge clicks / antialiasing
                const bbox = [
                    [point.x - pad, point.y - pad],
                    [point.x + pad, point.y + pad]
                ];
                const waterFeatures = this.map.queryRenderedFeatures(bbox, { layers: ['water', 'water-ocean-hit'] });
                const waterwayFeatures = this.map.queryRenderedFeatures(bbox, { layers: ['waterway'] });

                isWater = (Array.isArray(waterFeatures) && waterFeatures.length > 0) ||
                    (Array.isArray(waterwayFeatures) && waterwayFeatures.length > 0);

                // Heuristic: classify as "coastal" when the feature hints ocean/sea.
                const candidates = []
                    .concat(Array.isArray(waterFeatures) ? waterFeatures : [])
                    .concat(Array.isArray(waterwayFeatures) ? waterwayFeatures : [])
                    .map(f => String(f?.properties?.class ?? f?.properties?.kind ?? f?.properties?.type ?? '').toLowerCase())
                    .filter(Boolean);
                isCoastal = candidates.some(v => v.includes('ocean') || v.includes('sea'));
            }

            this.updateModelNote({ nearWater: isWater, coastal: isCoastal });

            if (isWater) {
                const data = {
                    latitude: lat,
                    longitude: lng,
                    elevation_m: null,
                    flood_risk_level: 'water',
                    water_level_m: this.currentWaterLevel,
                    risk_description: 'Open water (vector mask)',
                    tileInfo
                };
                this.updateRiskPanel(data);
                this.updateLocationInfo(data);
                this.addLocationMarker(lng, lat, data);
                return;
            }

            const response = await fetch(requireFloodmapUrlHelper('floodmapApiUrl')('/risk/location'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    latitude: lat,
                    longitude: lng,
                    waterLevelM: this.currentWaterLevel,
                    isWater
                })
            });

            const data = await response.json();
            // Add tile info to data for display
            data.tileInfo = tileInfo;

            this.updateRiskPanel(data);
            this.updateLocationInfo(data);
            this.addLocationMarker(lng, lat, data);

        } catch (error) {
            console.error('Risk assessment error:', error);
        }
    }

    updateModelNote({ nearWater = false, coastal = false } = {}) {
        this.modelNoteState = { nearWater: !!nearWater, coastal: !!coastal };
        const el = document.getElementById('model-note');
        if (!el) return;

        // Only show in Flood Risk mode (it explains the slider’s meaning).
        if (this.viewMode !== 'flood') {
            el.style.display = 'none';
            return;
        }

        el.style.display = 'block';

        if (coastal) {
            el.className = 'model-note model-note--ok';
            el.innerHTML = `
                <div class="model-note__title">Coastal surge model</div>
                <div class="model-note__body">Slider ≈ sea level + storm surge (m above mean sea level).</div>
            `;
            return;
        }

        if (nearWater) {
            el.className = 'model-note model-note--warning';
            el.innerHTML = `
                <div class="model-note__title">Inland water nearby</div>
                <div class="model-note__body">Slider is absolute sea level/surge; river stage/levees aren’t modeled.</div>
            `;
            return;
        }

        el.className = 'model-note';
        el.innerHTML = `
            <div class="model-note__title">Storm surge model</div>
            <div class="model-note__body">Slider is absolute sea level/surge (m above mean sea level).</div>
        `;
    }

    hasElevationValue(value) {
        return Number.isFinite(value);
    }

    escapeHtml(value) {
        return String(value)
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    clearMapMarkers() {
        const existingMarkers = document.querySelectorAll('.maplibregl-marker');
        existingMarkers.forEach(marker => marker.remove());
    }

    updateLocationInfo(data) {
        const locationInfo = document.getElementById('location-info');
        locationInfo.innerHTML = `
            📍 ${data.latitude.toFixed(4)}°, ${data.longitude.toFixed(4)}°
            ${this.hasElevationValue(data.elevation_m) ? `• ${data.elevation_m}m elevation` : ''}
            ${data.tileInfo ? `<br>${data.tileInfo}` : ''}
        `;
    }

    updateRiskPanel(data) {
        const riskDetails = document.getElementById('risk-details');
        const riskClass = `risk-${data.flood_risk_level}`;

        riskDetails.innerHTML = `
            <div class="risk-summary ${riskClass}">
                <strong>Risk Level: ${data.flood_risk_level.toUpperCase()}</strong>
            </div>
            <p><strong>Location:</strong> ${data.latitude.toFixed(4)}°, ${data.longitude.toFixed(4)}°</p>
            ${this.hasElevationValue(data.elevation_m) ? `<p><strong>Elevation:</strong> ${data.elevation_m}m</p>` : ''}
            <p><strong>Water Level:</strong> ${data.water_level_m}m</p>
            <p><strong>Assessment:</strong> ${data.risk_description}</p>
            ${data.tileInfo ? `<p><strong>Debug:</strong> ${data.tileInfo}</p>` : ''}
        `;
    }

    /**
     * Track location click event in Umami analytics.
     * Fires when user clicks map or uses "Find My Location".
     */
    trackLocationView(lat, lng) {
        if (typeof umami !== 'undefined' && typeof umami.track === 'function') {
            try {
                umami.track('location_click', {
                    lat: lat.toFixed(6),
                    lng: lng.toFixed(6)
                });
            } catch (e) {
                // Silently ignore tracking errors
            }
        }
    }

    /**
     * Track viewport view event in Umami analytics.
     * Fires on initial load and when user stops panning/zooming.
     */
    trackViewportView() {
        if (!this.map) return;
        if (typeof umami !== 'undefined' && typeof umami.track === 'function') {
            try {
                const center = this.map.getCenter();
                const zoom = this.map.getZoom();
                const bounds = this.map.getBounds();
                umami.track('viewport_view', {
                    lat: center.lat.toFixed(4),
                    lng: center.lng.toFixed(4),
                    zoom: zoom.toFixed(1),
                    ne_lat: bounds.getNorth().toFixed(4),
                    ne_lng: bounds.getEast().toFixed(4),
                    sw_lat: bounds.getSouth().toFixed(4),
                    sw_lng: bounds.getWest().toFixed(4)
                });
            } catch (e) {
                // Silently ignore tracking errors
            }
        }
    }

    addLocationMarker(lng, lat, data) {
        this.clearMapMarkers();

        const marker = new maplibregl.Marker({ color: '#ef4444' })
            .setLngLat([lng, lat])
            .setPopup(new maplibregl.Popup().setHTML(`
                <div>
                    <strong>Flood Risk: ${this.escapeHtml(data.flood_risk_level)}</strong><br>
                    Elevation: ${this.hasElevationValue(data.elevation_m) ? this.escapeHtml(data.elevation_m) : 'Unknown'}m<br>
                    ${this.escapeHtml(data.risk_description)}
                </div>
            `))
            .addTo(this.map);
    }
}

function floodmapInit() {
    if (typeof window === 'undefined') return;
    if (window.floodMap) return;
    window.floodMap = new FloodMapClient();
}

// Initialize robustly whether scripts are parser-inserted or injected after DOMContentLoaded.
if (typeof window !== 'undefined') {
    window.floodmapInit = floodmapInit;
    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', floodmapInit, { once: true });
        } else {
            floodmapInit();
        }
    }
}
