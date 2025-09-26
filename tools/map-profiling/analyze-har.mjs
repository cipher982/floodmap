#!/usr/bin/env node
import fs from 'node:fs';
import prettyBytes from 'pretty-bytes';

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

function sizeOf(entry) {
  // Prefer actual bodySize/transferSize if available; fallback to content.size
  const r = entry.response || {};
  const contentSize = r.content && typeof r.content.size === 'number' ? r.content.size : 0;
  const bodySize = typeof r.bodySize === 'number' && r.bodySize >= 0 ? r.bodySize : 0;
  const headersSize = typeof r.headersSize === 'number' && r.headersSize >= 0 ? r.headersSize : 0;
  const transfer = bodySize || (headersSize + contentSize) || contentSize;
  return transfer || 0;
}

function collect(har) {
  const entries = har.log && har.log.entries ? har.log.entries : [];
  const totals = { bytes: 0, count: entries.length, byHost: new Map(), byType: new Map() };
  for (const e of entries) {
    const sz = sizeOf(e);
    totals.bytes += sz;
    const host = hostname(e.request.url);
    const type = mimeGroup(e.response && e.response.content && e.response.content.mimeType || '');
    totals.byHost.set(host, (totals.byHost.get(host)||0) + sz);
    totals.byType.set(type, (totals.byType.get(type)||0) + sz);
  }
  return { entries, totals };
}

function top(entries, n=20) {
  const arr = entries.map(e => ({
    url: e.request.url,
    type: mimeGroup(e.response && e.response.content && e.response.content.mimeType || ''),
    bytes: sizeOf(e),
    status: e.response && e.response.status,
    time: e.time
  })).sort((a,b) => b.bytes - a.bytes).slice(0, n);
  return arr;
}

function printTotals(totals) {
  console.log('=== Totals ===');
  console.log(`Requests: ${totals.count}`);
  console.log(`Transfer: ${prettyBytes(totals.bytes)}\n`);

  console.log('=== By Host ===');
  for (const [host, bytes] of [...totals.byHost.entries()].sort((a,b)=>b[1]-a[1])) {
    console.log(`${host.padEnd(40)} ${prettyBytes(bytes)}`);
  }
  console.log();

  console.log('=== By Type ===');
  for (const [type, bytes] of [...totals.byType.entries()].sort((a,b)=>b[1]-a[1])) {
    console.log(`${type.padEnd(12)} ${prettyBytes(bytes)}`);
  }
  console.log();
}

function printTop(arr) {
  console.log('=== Largest Resources ===');
  for (const item of arr) {
    console.log(`${prettyBytes(item.bytes).padStart(8)}  ${String(item.status).padStart(3)}  ${item.type.padEnd(8)}  ${item.url}`);
  }
}

function main() {
  const file = process.argv[2] || 'har.json';
  if (!fs.existsSync(file)) {
    console.error(`HAR not found: ${file}`);
    process.exit(1);
  }
  const har = readHar(file);
  const { entries, totals } = collect(har);
  printTotals(totals);
  printTop(top(entries, 25));
}

main();
