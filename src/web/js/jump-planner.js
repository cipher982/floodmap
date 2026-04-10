/**
 * Pure helpers for deciding when a far-jump should stage through a coarse zoom
 * and which destination tiles to prefetch first.
 */

const EARTH_RADIUS_KM = 6371.0088;
const MAX_MERCATOR_LAT = 85.051129;
const TILE_SIZE = 256;
const PROGRESSIVE_DISTANCE_THRESHOLD_KM = 250;
const PROGRESSIVE_ZOOM_DELTA_THRESHOLD = 2.25;
const MIN_DISTANCE_FOR_ZOOM_DRIVEN_STAGING_KM = 75;
const MAX_PROGRESSIVE_STAGE_ZOOM = 7;
const MAX_PREFETCH_TILES = 24;

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function wrapLongitude(lng) {
    const wrapped = ((Number(lng) + 180) % 360 + 360) % 360 - 180;
    return wrapped === -180 ? 180 : wrapped;
}

function toRadians(value) {
    return (value * Math.PI) / 180;
}

function mercatorWorldPoint(lat, lng, zoom) {
    const normalizedZoom = Math.max(0, Number.isFinite(zoom) ? zoom : 0);
    const scale = TILE_SIZE * (2 ** normalizedZoom);
    const clampedLat = clamp(Number(lat), -MAX_MERCATOR_LAT, MAX_MERCATOR_LAT);
    const wrappedLng = wrapLongitude(lng);
    const sinLat = Math.sin(toRadians(clampedLat));

    return {
        x: ((wrappedLng + 180) / 360) * scale,
        y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
        scale
    };
}

function wrapTileX(x, tileCount) {
    return ((x % tileCount) + tileCount) % tileCount;
}

function calculateDistanceKm(from, to) {
    if (!from || !to) return 0;

    const fromLat = clamp(Number(from.lat), -MAX_MERCATOR_LAT, MAX_MERCATOR_LAT);
    const fromLng = wrapLongitude(from.lng);
    const toLat = clamp(Number(to.lat), -MAX_MERCATOR_LAT, MAX_MERCATOR_LAT);
    const toLng = wrapLongitude(to.lng);

    const dLat = toRadians(toLat - fromLat);
    const dLng = toRadians(toLng - fromLng);
    const a = (
        (Math.sin(dLat / 2) ** 2)
        + Math.cos(toRadians(fromLat))
            * Math.cos(toRadians(toLat))
            * (Math.sin(dLng / 2) ** 2)
    );

    return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

function getViewportPrefetchTiles({
    center,
    zoom,
    viewportWidth,
    viewportHeight,
    paddingTiles = 0,
    maxTiles = MAX_PREFETCH_TILES
}) {
    if (!center) return [];

    const tileZoom = Math.max(0, Math.floor(Number(zoom) || 0));
    const width = Math.max(TILE_SIZE, Number(viewportWidth) || 0);
    const height = Math.max(TILE_SIZE, Number(viewportHeight) || 0);
    const tileCount = 2 ** tileZoom;
    const world = mercatorWorldPoint(center.lat, center.lng, tileZoom);
    const centerTileX = world.x / TILE_SIZE;
    const centerTileY = world.y / TILE_SIZE;

    const minTileX = Math.floor((world.x - width / 2) / TILE_SIZE) - paddingTiles;
    const maxTileX = Math.floor((world.x + width / 2 - 1) / TILE_SIZE) + paddingTiles;
    const minTileY = Math.floor((world.y - height / 2) / TILE_SIZE) - paddingTiles;
    const maxTileY = Math.floor((world.y + height / 2 - 1) / TILE_SIZE) + paddingTiles;

    const tiles = [];
    for (let tileY = minTileY; tileY <= maxTileY; tileY += 1) {
        if (tileY < 0 || tileY >= tileCount) continue;
        for (let tileX = minTileX; tileX <= maxTileX; tileX += 1) {
            tiles.push({
                z: tileZoom,
                x: wrapTileX(tileX, tileCount),
                y: tileY,
                distance: Math.hypot(tileX - centerTileX, tileY - centerTileY)
            });
        }
    }

    tiles.sort((a, b) => a.distance - b.distance || a.y - b.y || a.x - b.x);
    return tiles.slice(0, Math.max(1, maxTiles)).map(({ distance, ...tile }) => tile);
}

function getViewportNeighborTiles({
    center,
    zoom,
    viewportWidth,
    viewportHeight,
    maxTiles = MAX_PREFETCH_TILES
}) {
    const requestedCount = Math.max(1, Number(maxTiles) || MAX_PREFETCH_TILES);
    const visibleTiles = getViewportPrefetchTiles({
        center,
        zoom,
        viewportWidth,
        viewportHeight,
        paddingTiles: 0,
        maxTiles: requestedCount * 3
    });
    const visibleKeys = new Set(
        visibleTiles.map((tile) => `${tile.z}/${tile.x}/${tile.y}`)
    );
    const paddedTiles = getViewportPrefetchTiles({
        center,
        zoom,
        viewportWidth,
        viewportHeight,
        paddingTiles: 1,
        maxTiles: requestedCount * 4
    });

    return paddedTiles
        .filter((tile) => !visibleKeys.has(`${tile.z}/${tile.x}/${tile.y}`))
        .slice(0, requestedCount);
}

function buildProgressiveJumpPlan({
    currentCenter,
    currentZoom,
    targetCenter,
    targetZoom,
    viewportWidth,
    viewportHeight
}) {
    const safeCurrentZoom = Number.isFinite(currentZoom) ? currentZoom : 0;
    const safeTargetZoom = Number.isFinite(targetZoom) ? targetZoom : safeCurrentZoom;
    const distanceKm = calculateDistanceKm(currentCenter, targetCenter);
    const zoomDelta = Math.abs(safeTargetZoom - safeCurrentZoom);
    const useProgressive = (
        distanceKm >= PROGRESSIVE_DISTANCE_THRESHOLD_KM
        || (
            distanceKm >= MIN_DISTANCE_FOR_ZOOM_DRIVEN_STAGING_KM
            && zoomDelta >= PROGRESSIVE_ZOOM_DELTA_THRESHOLD
        )
    );

    const stageZoom = clamp(Math.floor(safeTargetZoom), 0, MAX_PROGRESSIVE_STAGE_ZOOM);
    const prefetchTiles = useProgressive
        ? getViewportPrefetchTiles({
            center: targetCenter,
            zoom: stageZoom,
            viewportWidth,
            viewportHeight
        })
        : [];

    return {
        distanceKm,
        zoomDelta,
        useProgressive,
        stageZoom,
        requiresFinalRefine: safeTargetZoom - stageZoom > 0.35,
        prefetchTiles
    };
}

const FloodmapJumpPlanner = {
    calculateDistanceKm,
    getViewportPrefetchTiles,
    getViewportNeighborTiles,
    buildProgressiveJumpPlan,
    constants: Object.freeze({
        PROGRESSIVE_DISTANCE_THRESHOLD_KM,
        PROGRESSIVE_ZOOM_DELTA_THRESHOLD,
        MIN_DISTANCE_FOR_ZOOM_DRIVEN_STAGING_KM,
        MAX_PROGRESSIVE_STAGE_ZOOM,
        MAX_PREFETCH_TILES,
        TILE_SIZE
    })
};

if (typeof window !== 'undefined') {
    window.FloodmapJumpPlanner = FloodmapJumpPlanner;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = FloodmapJumpPlanner;
}
