/**
 * Pure helpers for parsing and building shareable Floodmap URLs.
 * These stay side-effect free so browser behavior can be unit tested in Node.
 */

const FLOODMAP_STATE_PARAM_KEYS = Object.freeze([
    'lat',
    'lng',
    'zoom',
    'view',
    'water'
]);

const FLOODMAP_DEFAULT_VIEW_STATE = Object.freeze({
    lat: 27.95,
    lng: -82.46,
    zoom: 8,
    view: 'elevation',
    water: 1.0
});

const FLOODMAP_MAX_LATITUDE = 85.051129;
const FLOODMAP_MIN_ZOOM = 0;
const FLOODMAP_MAX_ZOOM = 11;
const FLOODMAP_MIN_WATER_LEVEL = 0.1;
const FLOODMAP_MAX_WATER_LEVEL = 1000;

function parseFiniteNumber(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
}

function roundTo(value, digits) {
    const factor = 10 ** digits;
    return Math.round(value * factor) / factor;
}

function normalizeLatitude(value, fallback = FLOODMAP_DEFAULT_VIEW_STATE.lat) {
    const parsed = parseFiniteNumber(value);
    if (parsed === null) return fallback;
    return roundTo(clamp(parsed, -FLOODMAP_MAX_LATITUDE, FLOODMAP_MAX_LATITUDE), 5);
}

function normalizeLongitude(value, fallback = FLOODMAP_DEFAULT_VIEW_STATE.lng) {
    const parsed = parseFiniteNumber(value);
    if (parsed === null) return fallback;
    return roundTo(clamp(parsed, -180, 180), 5);
}

function normalizeZoom(value, fallback = FLOODMAP_DEFAULT_VIEW_STATE.zoom) {
    const parsed = parseFiniteNumber(value);
    if (parsed === null) return fallback;
    return roundTo(clamp(parsed, FLOODMAP_MIN_ZOOM, FLOODMAP_MAX_ZOOM), 2);
}

function normalizeViewMode(value, fallback = FLOODMAP_DEFAULT_VIEW_STATE.view) {
    return value === 'flood' || value === 'elevation' ? value : fallback;
}

function normalizeWaterLevel(value, fallback = FLOODMAP_DEFAULT_VIEW_STATE.water) {
    const parsed = parseFiniteNumber(value);
    if (parsed === null || parsed <= 0) return fallback;
    return roundTo(
        clamp(parsed, FLOODMAP_MIN_WATER_LEVEL, FLOODMAP_MAX_WATER_LEVEL),
        1
    );
}

function normalizeViewState(viewState = {}, defaults = FLOODMAP_DEFAULT_VIEW_STATE) {
    return {
        lat: normalizeLatitude(viewState.lat, defaults.lat),
        lng: normalizeLongitude(viewState.lng, defaults.lng),
        zoom: normalizeZoom(viewState.zoom, defaults.zoom),
        view: normalizeViewMode(viewState.view, defaults.view),
        water: normalizeWaterLevel(viewState.water, defaults.water)
    };
}

function parseFloodmapUrlState(urlLike, defaults = FLOODMAP_DEFAULT_VIEW_STATE) {
    const url = new URL(urlLike, 'https://drose.io/floodmap');
    const params = url.searchParams;
    const normalizedDefaults = normalizeViewState(defaults, FLOODMAP_DEFAULT_VIEW_STATE);

    return {
        ...normalizeViewState(
            {
                lat: params.get('lat'),
                lng: params.get('lng'),
                zoom: params.get('zoom'),
                view: params.get('view'),
                water: params.get('water')
            },
            normalizedDefaults
        ),
        hasExplicitState: FLOODMAP_STATE_PARAM_KEYS.some((key) => params.has(key))
    };
}

function stripFloodmapStateParams(urlLike) {
    const url = new URL(urlLike, 'https://drose.io/floodmap');
    FLOODMAP_STATE_PARAM_KEYS.forEach((key) => {
        url.searchParams.delete(key);
    });
    return url.toString();
}

function isDefaultViewState(viewState, defaults = FLOODMAP_DEFAULT_VIEW_STATE) {
    const normalizedState = normalizeViewState(viewState, defaults);
    const normalizedDefaults = normalizeViewState(defaults, FLOODMAP_DEFAULT_VIEW_STATE);

    return FLOODMAP_STATE_PARAM_KEYS.every(
        (key) => normalizedState[key] === normalizedDefaults[key]
    );
}

function buildFloodmapShareUrl(urlLike, viewState, defaults = FLOODMAP_DEFAULT_VIEW_STATE) {
    const url = new URL(urlLike, 'https://drose.io/floodmap');
    const normalizedState = normalizeViewState(viewState, defaults);

    url.searchParams.set('lat', normalizedState.lat.toFixed(5));
    url.searchParams.set('lng', normalizedState.lng.toFixed(5));
    url.searchParams.set('zoom', normalizedState.zoom.toFixed(2));
    url.searchParams.set('view', normalizedState.view);
    url.searchParams.set('water', normalizedState.water.toFixed(1));

    return url.toString();
}

const FloodmapUrlState = {
    DEFAULT_VIEW_STATE: FLOODMAP_DEFAULT_VIEW_STATE,
    STATE_PARAM_KEYS: FLOODMAP_STATE_PARAM_KEYS,
    parseFloodmapUrlState,
    buildFloodmapShareUrl,
    stripFloodmapStateParams,
    isDefaultViewState
};

if (typeof window !== 'undefined') {
    window.FloodmapUrlState = FloodmapUrlState;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = FloodmapUrlState;
}
