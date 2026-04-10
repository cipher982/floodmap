#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';

import { chromium } from 'playwright';
import { PNG } from 'pngjs';
import prettyBytes from 'pretty-bytes';

const __dirname = path.dirname(new URL(import.meta.url).pathname);
const repoRoot = path.resolve(__dirname, '..', '..');
const resultsRoot = path.join(__dirname, 'results');
const BACKGROUND_RGB = [248, 249, 250];
const DEFAULT_VIEW = { view: 'elevation', water: '1.0' };

function parseArgs(argv) {
    const args = {
        url: null,
        width: 1440,
        height: 900,
        observeMs: 12000,
        sampleMs: 250,
        clipWidth: 320,
        clipHeight: 240,
        blankThreshold: 0.92,
        visibleThreshold: 0.85,
        pairSpecs: [],
        pairCount: 4,
        flyDurationMs: 1100
    };

    for (const arg of argv.slice(2)) {
        if (!arg.startsWith('--')) {
            args.url = arg;
            continue;
        }
        const [key, rawValue] = arg.replace(/^--/, '').split('=');
        const value = rawValue ?? '';
        if (['width', 'height', 'observeMs', 'sampleMs', 'clipWidth', 'clipHeight', 'pairCount', 'flyDurationMs'].includes(key)) {
            args[key] = Number(value);
            continue;
        }
        if (['blankThreshold', 'visibleThreshold'].includes(key)) {
            args[key] = Number(value);
            continue;
        }
        if (key === 'pair') {
            args.pairSpecs.push(value);
            continue;
        }
        args[key] = value;
    }

    if (!args.url) {
        console.error(
            'Usage: node city-jump-profile.mjs <url> [--pair=state/city:state/city] [--pairCount=4] [--observeMs=12000]'
        );
        process.exit(1);
    }

    return args;
}

function runCommand(command, args, options = {}) {
    const result = spawnSync(command, args, {
        cwd: options.cwd,
        encoding: 'utf8',
        maxBuffer: 8 * 1024 * 1024
    });
    if (result.status !== 0) {
        const stderr = (result.stderr || '').trim();
        const stdout = (result.stdout || '').trim();
        throw new Error(
            `${command} ${args.join(' ')} failed: ${stderr || stdout || `exit ${result.status}`}`
        );
    }
    return result.stdout;
}

function nowStamp() {
    const date = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function gitHash() {
    try {
        return runCommand('git', ['rev-parse', '--short', 'HEAD'], { cwd: repoRoot }).trim();
    } catch {
        return 'unknown';
    }
}

function loadCityCatalog() {
    const script = `
import json
import sys
sys.path.append('src/api')
from location_catalog import list_city_pages

pages = []
for page in list_city_pages():
    pages.append({
        "id": f"{page.state_slug}/{page.city_slug}",
        "name": page.full_name,
        "state_slug": page.state_slug,
        "city_slug": page.city_slug,
        "lat": page.default_view_state.lat,
        "lng": page.default_view_state.lng,
        "zoom": page.default_view_state.zoom,
    })

print(json.dumps(pages, separators=(",", ":")))
    `.trim();

    return JSON.parse(runCommand('python3', ['-c', script], { cwd: repoRoot }));
}

function haversineKm(a, b) {
    const toRadians = (degrees) => (degrees * Math.PI) / 180;
    const earthRadiusKm = 6371.0088;
    const deltaLat = toRadians(b.lat - a.lat);
    const deltaLng = toRadians(b.lng - a.lng);
    const sinLat = Math.sin(deltaLat / 2);
    const sinLng = Math.sin(deltaLng / 2);
    const aa = sinLat * sinLat
        + Math.cos(toRadians(a.lat)) * Math.cos(toRadians(b.lat)) * sinLng * sinLng;
    return earthRadiusKm * 2 * Math.atan2(Math.sqrt(aa), Math.sqrt(1 - aa));
}

function buildDefaultPairs(cities, pairCount) {
    const candidates = [];
    for (let i = 0; i < cities.length; i += 1) {
        for (let j = 0; j < cities.length; j += 1) {
            if (i === j) continue;
            const from = cities[i];
            const to = cities[j];
            candidates.push({
                from,
                to,
                distanceKm: haversineKm(from, to)
            });
        }
    }

    candidates.sort((left, right) => right.distanceKm - left.distanceKm);

    const selected = [];
    const usedSignatures = new Set();
    for (const candidate of candidates) {
        if (selected.length >= pairCount) break;
        const signature = `${candidate.from.id}>${candidate.to.id}`;
        if (usedSignatures.has(signature)) continue;
        selected.push(candidate);
        usedSignatures.add(signature);
    }
    return selected;
}

function resolvePairs(cities, pairSpecs, pairCount) {
    const byId = new Map(cities.map((city) => [city.id, city]));
    if (!pairSpecs.length) {
        return buildDefaultPairs(cities, pairCount);
    }

    return pairSpecs.map((spec) => {
        const [fromId, toId] = String(spec).split(':');
        const from = byId.get(fromId);
        const to = byId.get(toId);
        if (!from || !to) {
            throw new Error(`Unknown pair "${spec}". Expected state/city identifiers from location_catalog.py.`);
        }
        return {
            from,
            to,
            distanceKm: haversineKm(from, to)
        };
    });
}

function createProfileUrl(baseUrl, city) {
    const targetUrl = new URL(baseUrl);
    targetUrl.searchParams.set('lat', city.lat.toFixed(6));
    targetUrl.searchParams.set('lng', city.lng.toFixed(6));
    targetUrl.searchParams.set('zoom', city.zoom.toFixed(2));
    targetUrl.searchParams.set('view', DEFAULT_VIEW.view);
    targetUrl.searchParams.set('water', DEFAULT_VIEW.water);
    targetUrl.searchParams.set('no_analytics', '1');
    return targetUrl.toString();
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseTileUrl(url) {
    const elevationMatch = url.match(/\/elevation-data\/(\d+)\/(\d+)\/(\d+)\.u16/);
    if (elevationMatch) {
        return {
            type: 'elevation',
            z: Number(elevationMatch[1]),
            x: Number(elevationMatch[2]),
            y: Number(elevationMatch[3]),
            url
        };
    }

    const vectorMatch = url.match(/\/vector\/usa\/(\d+)\/(\d+)\/(\d+)\.pbf/);
    if (vectorMatch) {
        return {
            type: 'vector',
            z: Number(vectorMatch[1]),
            x: Number(vectorMatch[2]),
            y: Number(vectorMatch[3]),
            url
        };
    }

    return null;
}

function summarizeEvents(events) {
    const summary = {
        requests: 0,
        responses: 0,
        finished: 0,
        failed: 0,
        firstRequestMs: null,
        firstResponseMs: null,
        firstFinishedMs: null,
        firstFailedMs: null,
        byZoom: {}
    };

    for (const event of events) {
        const bucket = summary.byZoom[event.z] || {
            requests: 0,
            responses: 0,
            finished: 0,
            failed: 0
        };
        if (event.kind === 'request') {
            summary.requests += 1;
            bucket.requests += 1;
            summary.firstRequestMs ??= event.elapsedMs;
        } else if (event.kind === 'response') {
            summary.responses += 1;
            bucket.responses += 1;
            summary.firstResponseMs ??= event.elapsedMs;
        } else if (event.kind === 'finished') {
            summary.finished += 1;
            bucket.finished += 1;
            summary.firstFinishedMs ??= event.elapsedMs;
        } else if (event.kind === 'failed') {
            summary.failed += 1;
            bucket.failed += 1;
            summary.firstFailedMs ??= event.elapsedMs;
        }
        summary.byZoom[event.z] = bucket;
    }

    return summary;
}

function analyzeBlankRatio(pngBuffer, tolerance = 10, stride = 4) {
    const png = PNG.sync.read(pngBuffer);
    let total = 0;
    let blank = 0;

    for (let y = 0; y < png.height; y += stride) {
        for (let x = 0; x < png.width; x += stride) {
            const offset = (png.width * y + x) << 2;
            const red = png.data[offset];
            const green = png.data[offset + 1];
            const blue = png.data[offset + 2];
            const alpha = png.data[offset + 3];
            total += 1;

            if (alpha === 0) {
                blank += 1;
                continue;
            }

            const isBackground = Math.abs(red - BACKGROUND_RGB[0]) <= tolerance
                && Math.abs(green - BACKGROUND_RGB[1]) <= tolerance
                && Math.abs(blue - BACKGROUND_RGB[2]) <= tolerance;
            if (isBackground) {
                blank += 1;
            }
        }
    }

    return total ? blank / total : 1;
}

async function waitForAppReady(page) {
    await page.waitForSelector('#map', { timeout: 15000 });
    await page.waitForFunction(
        `() => Boolean(window.floodMap && window.floodMap.map && window.floodMap.map.loaded())`,
        { timeout: 30000 }
    );
    await page.waitForTimeout(400);
}

async function waitForTilesLoaded(page, timeoutMs = 15000) {
    await page.waitForFunction(
        `() => Boolean(window.floodMap && window.floodMap.map && !window.floodMap.map.isMoving() && window.floodMap.map.areTilesLoaded())`,
        { timeout: timeoutMs }
    );
}

async function getMapClip(page, options) {
    const box = await page.locator('#map').boundingBox();
    if (!box) {
        throw new Error('Could not resolve #map bounding box.');
    }

    const clipWidth = Math.min(options.clipWidth, Math.floor(box.width * 0.45));
    const clipHeight = Math.min(options.clipHeight, Math.floor(box.height * 0.45));

    return {
        x: box.x + Math.max(0, Math.floor((box.width - clipWidth) / 2)),
        y: box.y + Math.max(0, Math.floor((box.height - clipHeight) / 2)),
        width: clipWidth,
        height: clipHeight
    };
}

async function sampleJumpState(page, clip, startedAtMs) {
    const screenshot = await page.screenshot({ clip });
    const blankRatio = analyzeBlankRatio(screenshot);
    const state = await page.evaluate(() => {
        const map = window.floodMap.map;
        const center = map.getCenter();
        return {
            elapsedMs: performance.now() - (window.__jumpStartPerf || performance.now()),
            tilesLoaded: map.areTilesLoaded(),
            moving: map.isMoving(),
            zoom: map.getZoom(),
            center: { lat: center.lat, lng: center.lng }
        };
    });

    return {
        ...state,
        blankRatio,
        nodeElapsedMs: performance.now() - startedAtMs
    };
}

function computeBlankMetrics(samples, blankThreshold, visibleThreshold) {
    let blankStartMs = null;
    let blankRecoveredMs = null;
    let peakBlankRatio = 0;

    for (const sample of samples) {
        peakBlankRatio = Math.max(peakBlankRatio, sample.blankRatio);
        if (sample.elapsedMs < 150) {
            continue;
        }
        if (blankStartMs == null && sample.blankRatio >= blankThreshold) {
            blankStartMs = sample.elapsedMs;
            continue;
        }
        if (blankStartMs != null && blankRecoveredMs == null && sample.blankRatio < visibleThreshold) {
            blankRecoveredMs = sample.elapsedMs;
            break;
        }
    }

    return {
        blankStartMs: blankStartMs == null ? null : Math.round(blankStartMs),
        blankRecoveredMs: blankRecoveredMs == null ? null : Math.round(blankRecoveredMs),
        blankDurationMs: blankStartMs != null && blankRecoveredMs != null
            ? Math.round(blankRecoveredMs - blankStartMs)
            : 0,
        peakBlankRatio: Number(peakBlankRatio.toFixed(3))
    };
}

function computeTilesLoadedMs(samples) {
    const stableSamples = [];
    for (const sample of samples) {
        if (!sample.moving && sample.tilesLoaded) {
            stableSamples.push(sample);
            if (stableSamples.length >= 2) {
                return Math.round(stableSamples[0].elapsedMs);
            }
        } else {
            stableSamples.length = 0;
        }
    }
    return null;
}

function summarizeFinishedTransfers(events) {
    const finishedEvents = events.filter((event) => event.kind === 'finished');
    const summary = {
        count: finishedEvents.length,
        transferBytes: 0,
        bodyBytes: 0,
        firstFinishedMs: null,
        lastFinishedMs: null,
        byZoom: {}
    };

    for (const event of finishedEvents) {
        const transferBytes = (event.responseHeadersSize || 0) + (event.responseBodySize || 0);
        summary.transferBytes += transferBytes;
        summary.bodyBytes += event.responseBodySize || 0;
        summary.firstFinishedMs ??= event.elapsedMs;
        summary.lastFinishedMs = event.elapsedMs;

        const bucket = summary.byZoom[event.z] || {
            count: 0,
            transferBytes: 0,
            bodyBytes: 0
        };
        bucket.count += 1;
        bucket.transferBytes += transferBytes;
        bucket.bodyBytes += event.responseBodySize || 0;
        summary.byZoom[event.z] = bucket;
    }

    return summary;
}

function toPrettyTransferSummary(summary) {
    return {
        count: summary.count,
        transfer: prettyBytes(summary.transferBytes),
        body: prettyBytes(summary.bodyBytes),
        firstFinishedMs: summary.firstFinishedMs == null ? null : Math.round(summary.firstFinishedMs),
        lastFinishedMs: summary.lastFinishedMs == null ? null : Math.round(summary.lastFinishedMs),
        byZoom: Object.fromEntries(
            Object.entries(summary.byZoom).map(([zoom, bucket]) => [
                zoom,
                {
                    count: bucket.count,
                    transfer: prettyBytes(bucket.transferBytes),
                    body: prettyBytes(bucket.bodyBytes)
                }
            ])
        )
    };
}

async function profileJump(browser, pair, options) {
    const context = await browser.newContext({
        viewport: { width: options.width, height: options.height },
        ignoreHTTPSErrors: true
    });
    const page = await context.newPage();
    const networkEvents = [];
    const requestSizePromises = [];

    let activeJumpStart = null;
    const recordNetworkEvent = (kind, url) => {
        if (activeJumpStart == null) return;
        const tile = parseTileUrl(url);
        if (!tile) return;
        networkEvents.push({
            kind,
            type: tile.type,
            z: tile.z,
            x: tile.x,
            y: tile.y,
            url,
            elapsedMs: Number((performance.now() - activeJumpStart).toFixed(1))
        });
    };

    const onRequest = (request) => recordNetworkEvent('request', request.url());
    const onResponse = (response) => recordNetworkEvent('response', response.url());
    const onRequestFailed = (request) => {
        if (activeJumpStart == null) return;
        const tile = parseTileUrl(request.url());
        if (!tile) return;
        networkEvents.push({
            kind: 'failed',
            type: tile.type,
            z: tile.z,
            x: tile.x,
            y: tile.y,
            url: request.url(),
            elapsedMs: Number((performance.now() - activeJumpStart).toFixed(1)),
            errorText: request.failure()?.errorText || 'unknown'
        });
    };
    const onRequestFinished = (request) => {
        if (activeJumpStart == null) return;
        const tile = parseTileUrl(request.url());
        if (!tile) return;

        const event = {
            kind: 'finished',
            type: tile.type,
            z: tile.z,
            x: tile.x,
            y: tile.y,
            url: request.url(),
            elapsedMs: Number((performance.now() - activeJumpStart).toFixed(1)),
            responseBodySize: 0,
            responseHeadersSize: 0
        };
        networkEvents.push(event);

        if (typeof request.sizes === 'function') {
            requestSizePromises.push(
                request.sizes()
                    .then((sizes) => {
                        event.responseBodySize = sizes.responseBodySize || 0;
                        event.responseHeadersSize = sizes.responseHeadersSize || 0;
                    })
                    .catch(() => {})
            );
        }
    };

    page.on('request', onRequest);
    page.on('response', onResponse);
    page.on('requestfailed', onRequestFailed);
    page.on('requestfinished', onRequestFinished);

    try {
        await page.goto(createProfileUrl(options.url, pair.from), {
            waitUntil: 'domcontentloaded',
            timeout: 60000
        });
        await waitForAppReady(page);
        await waitForTilesLoaded(page);
        await page.waitForTimeout(500);

        const clip = await getMapClip(page, options);
        const baselineShot = await page.screenshot({ clip });
        const baselineBlankRatio = analyzeBlankRatio(baselineShot);

        await page.evaluate(() => {
            performance.clearResourceTimings();
            window.__jumpStartPerf = performance.now();
        });

        activeJumpStart = performance.now();
        await page.evaluate(
            ({ to, duration }) => {
                window.floodMap.map.flyTo({
                    center: [to.lng, to.lat],
                    zoom: to.zoom,
                    essential: true,
                    duration
                });
            },
            { to: pair.to, duration: options.flyDurationMs }
        );

        const samples = [];
        const startedAtMs = performance.now();
        let stableLoadedCount = 0;
        while (performance.now() - startedAtMs < options.observeMs) {
            const sample = await sampleJumpState(page, clip, startedAtMs);
            samples.push(sample);

            if (!sample.moving && sample.tilesLoaded) {
                stableLoadedCount += 1;
            } else {
                stableLoadedCount = 0;
            }

            if (stableLoadedCount >= 2 && sample.elapsedMs > options.flyDurationMs) {
                break;
            }

            await sleep(options.sampleMs);
        }
        activeJumpStart = null;

        await Promise.all(requestSizePromises);
        const elevationNetworkEvents = networkEvents.filter((event) => event.type === 'elevation');
        const vectorNetworkEvents = networkEvents.filter((event) => event.type === 'vector');
        const elevationEvents = summarizeEvents(elevationNetworkEvents);
        const vectorEvents = summarizeEvents(vectorNetworkEvents);
        const blankMetrics = computeBlankMetrics(samples, options.blankThreshold, options.visibleThreshold);
        const tilesLoadedMs = computeTilesLoadedMs(samples);

        return {
            from: pair.from,
            to: pair.to,
            distanceKm: Number(pair.distanceKm.toFixed(1)),
            baselineBlankRatio: Number(baselineBlankRatio.toFixed(3)),
            blank: blankMetrics,
            tilesLoadedMs,
            elevation: {
                events: elevationEvents,
                resources: toPrettyTransferSummary(summarizeFinishedTransfers(elevationNetworkEvents))
            },
            vector: {
                events: vectorEvents,
                resources: toPrettyTransferSummary(summarizeFinishedTransfers(vectorNetworkEvents))
            },
            sampleCount: samples.length,
            tailSample: samples.length ? {
                elapsedMs: Math.round(samples[samples.length - 1].elapsedMs),
                blankRatio: Number(samples[samples.length - 1].blankRatio.toFixed(3)),
                moving: samples[samples.length - 1].moving,
                tilesLoaded: samples[samples.length - 1].tilesLoaded
            } : null
        };
    } finally {
        page.off('request', onRequest);
        page.off('response', onResponse);
        page.off('requestfailed', onRequestFailed);
        page.off('requestfinished', onRequestFinished);
        await context.close();
    }
}

function summarizeCityZooms(cities) {
    const zooms = cities.map((city) => city.zoom);
    const avg = zooms.reduce((sum, zoom) => sum + zoom, 0) / zooms.length;
    return {
        count: cities.length,
        minZoom: Number(Math.min(...zooms).toFixed(1)),
        maxZoom: Number(Math.max(...zooms).toFixed(1)),
        avgZoom: Number(avg.toFixed(2)),
        cities: cities.map((city) => ({
            id: city.id,
            name: city.name,
            zoom: city.zoom
        }))
    };
}

function renderSummaryMarkdown(meta, cityZooms, results) {
    const lines = [];
    lines.push('# City Jump Profiling Summary');
    lines.push(`URL: ${meta.url}`);
    lines.push(`Commit: ${meta.git}`);
    lines.push(`Viewport: ${meta.width}x${meta.height}`);
    lines.push('');
    lines.push('## City Defaults');
    lines.push(`- city pages: ${cityZooms.count}`);
    lines.push(`- default zoom range: ${cityZooms.minZoom} - ${cityZooms.maxZoom}`);
    lines.push(`- average default zoom: ${cityZooms.avgZoom}`);
    lines.push('');

    for (const result of results) {
        lines.push(`## ${result.from.name} -> ${result.to.name}`);
        lines.push(`- distance: ${result.distanceKm} km`);
        lines.push(`- default zooms: ${result.from.zoom} -> ${result.to.zoom}`);
        lines.push(`- baseline blank ratio: ${result.baselineBlankRatio}`);
        lines.push(`- peak blank ratio: ${result.blank.peakBlankRatio}`);
        lines.push(`- blank duration: ${result.blank.blankDurationMs} ms`);
        lines.push(`- first elevation response: ${result.elevation.events.firstResponseMs ?? 'n/a'} ms`);
        lines.push(`- first elevation finished: ${result.elevation.events.firstFinishedMs ?? 'n/a'} ms`);
        lines.push(`- first vector response: ${result.vector.events.firstResponseMs ?? 'n/a'} ms`);
        lines.push(`- tiles loaded: ${result.tilesLoadedMs ?? 'n/a'} ms`);
        lines.push(`- elevation transfer: ${result.elevation.resources.transfer} across ${result.elevation.resources.count} resources`);
        lines.push(`- vector transfer: ${result.vector.resources.transfer} across ${result.vector.resources.count} resources`);
        lines.push('');
    }

    return lines.join('\n');
}

async function main() {
    const options = parseArgs(process.argv);
    const cities = loadCityCatalog();
    const pairs = resolvePairs(cities, options.pairSpecs, options.pairCount);
    const meta = {
        url: options.url,
        width: options.width,
        height: options.height,
        observeMs: options.observeMs,
        sampleMs: options.sampleMs,
        blankThreshold: options.blankThreshold,
        visibleThreshold: options.visibleThreshold,
        git: gitHash(),
        ts: new Date().toISOString()
    };

    const browser = await chromium.launch({ headless: true });
    try {
        const results = [];
        for (const pair of pairs) {
            process.stdout.write(`\n[RUN] ${pair.from.name} -> ${pair.to.name}...\n`);
            results.push(await profileJump(browser, pair, options));
        }

        const outputDir = path.join(resultsRoot, `${nowStamp()}-city-jumps`);
        fs.mkdirSync(outputDir, { recursive: true });

        const cityZooms = summarizeCityZooms(cities);
        const summary = {
            meta,
            cityZooms,
            results
        };
        fs.writeFileSync(
            path.join(outputDir, 'summary.json'),
            `${JSON.stringify(summary, null, 2)}\n`
        );
        fs.writeFileSync(
            path.join(outputDir, 'summary.md'),
            `${renderSummaryMarkdown(meta, cityZooms, results)}\n`
        );

        console.log(`\nResults written to ${outputDir}`);
    } finally {
        await browser.close();
    }
}

main().catch((error) => {
    console.error(error);
    process.exit(1);
});
