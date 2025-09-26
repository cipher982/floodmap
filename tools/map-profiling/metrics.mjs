#!/usr/bin/env node
import fs from 'node:fs';

function readHar(file) {
  const raw = fs.readFileSync(file, 'utf-8');
  return JSON.parse(raw);
}

function hostname(u) {
  try { return new URL(u).hostname; } catch { return 'invalid'; }
}

function mimeGroup(mime) {
  if (!mime) return 'other';
  if (mime.includes('javascript')) return 'js';
  if (mime.startsWith('text/')) return 'text';
  if (mime.startsWith('image/')) return 'image';
  if (mime.includes('json')) return 'json';
  if (mime.includes('protobuf') || mime.includes('pbf')) return 'pbf';
  if (mime.includes('octet-stream')) return 'binary';
  if (mime.includes('wasm')) return 'wasm';
  return mime.split(';')[0] || 'other';
}

function hget(headers,name){
  name = String(name||'').toLowerCase();
  const h = (headers||[]).find(h=>String(h.name).toLowerCase()===name);
  return h? String(h.value): '';
}

function sizeOf(entry) {
  const r = entry.response || {};
  const contentSize = r.content && typeof r.content.size === 'number' ? r.content.size : 0;
  const bodySize = typeof r.bodySize === 'number' && r.bodySize >= 0 ? r.bodySize : 0;
  const headersSize = typeof r.headersSize === 'number' && r.headersSize >= 0 ? r.headersSize : 0;
  const transfer = bodySize || (headersSize + contentSize) || contentSize;
  return transfer || 0;
}

function byZoomMetrics(entries) {
  const out = {
    elevation: { totalBytes:0,totalCount:0, totalTime:0, avgTime:0, maxTime:0, byZoom:{} , encodings:new Set(), caches:new Set() },
    vector: { totalBytes:0,totalCount:0, totalTime:0, avgTime:0, maxTime:0, byZoom:{}, encodings:new Set(), caches:new Set() }
  };
  for (const e of entries) {
    const url = e.request.url;
    if (!/\/api\/v1\/tiles\//.test(url)) continue;
    const kind = /\/elevation-data\//.test(url) ? 'elevation' : 'vector';
    const m = url.match(/\/(elevation-data|vector\/[^/]+)\/(\d+)\//);
    const z = m ? Number(m[2]) : -1;
    const bytes = sizeOf(e);
    const time = e.time || 0;
    out[kind].totalBytes += bytes;
    out[kind].totalCount += 1;
    out[kind].totalTime += time;
    out[kind].maxTime = Math.max(out[kind].maxTime, time);
    out[kind].byZoom[z] = out[kind].byZoom[z] || { bytes:0, count:0, totalTime:0, avgTime:0, maxTime:0 };
    out[kind].byZoom[z].bytes += bytes;
    out[kind].byZoom[z].count += 1;
    out[kind].byZoom[z].totalTime += time;
    out[kind].byZoom[z].maxTime = Math.max(out[kind].byZoom[z].maxTime, time);
    const enc = hget(e.response.headers, 'content-encoding') || '(none)';
    const cache = hget(e.response.headers, 'cache-control') || '(none)';
    out[kind].encodings.add(enc);
    out[kind].caches.add(cache);
  }
  // Calculate averages and convert sets to arrays for JSON
  out.elevation.avgTime = out.elevation.totalCount > 0 ? out.elevation.totalTime / out.elevation.totalCount : 0;
  out.vector.avgTime = out.vector.totalCount > 0 ? out.vector.totalTime / out.vector.totalCount : 0;
  for (const z of Object.keys(out.elevation.byZoom)) {
    const zd = out.elevation.byZoom[z];
    zd.avgTime = zd.count > 0 ? zd.totalTime / zd.count : 0;
  }
  for (const z of Object.keys(out.vector.byZoom)) {
    const zd = out.vector.byZoom[z];
    zd.avgTime = zd.count > 0 ? zd.totalTime / zd.count : 0;
  }
  out.elevation.encodings = [...out.elevation.encodings];
  out.elevation.caches = [...out.elevation.caches];
  out.vector.encodings = [...out.vector.encodings];
  out.vector.caches = [...out.vector.caches];
  return out;
}

function collect(har) {
  const entries = har.log && har.log.entries ? har.log.entries : [];
  const pages = har.log && har.log.pages ? har.log.pages : [];

  // Extract page timing
  const pageTimings = pages.length > 0 ? {
    onContentLoad: pages[0].pageTimings?.onContentLoad || 0,
    onLoad: pages[0].pageTimings?.onLoad || 0
  } : { onContentLoad: 0, onLoad: 0 };

  const totals = { bytes: 0, count: entries.length, byHost: {}, byType: {} };
  for (const e of entries) {
    const sz = sizeOf(e);
    totals.bytes += sz;
    const host = hostname(e.request.url);
    const type = mimeGroup(e.response && e.response.content && e.response.content.mimeType || '');
    totals.byHost[host] = (totals.byHost[host]||0) + sz;
    totals.byType[type] = (totals.byType[type]||0) + sz;
  }
  const tiles = byZoomMetrics(entries);
  const largest = entries.map(e => ({ url: e.request.url, bytes: sizeOf(e), status: e.response && e.response.status, type: mimeGroup(e.response && e.response.content && e.response.content.mimeType || '') }))
                        .sort((a,b)=>b.bytes-a.bytes).slice(0,25);
  return { totals, tiles, largest, pageTimings };
}

function main() {
  const file = process.argv[2] || 'har.json';
  if (!fs.existsSync(file)) {
    console.error(`HAR not found: ${file}`);
    process.exit(1);
  }
  const har = readHar(file);
  const metrics = collect(har);
  process.stdout.write(JSON.stringify(metrics, null, 2));
}

main();
