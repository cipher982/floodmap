#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import prettyBytes from 'pretty-bytes';
const __dirname = path.dirname(new URL(import.meta.url).pathname);

function parseArgs(argv){
  const args = { width:1440, height:900, duration:10000, selector:null, url:null };
  for (const arg of argv.slice(2)) {
    if (!arg.startsWith('--')) { args.url = arg; continue; }
    const [k,v] = arg.replace(/^--/,'').split('=');
    if (['width','height','duration'].includes(k)) args[k]=Number(v);
    else args[k]=v;
  }
  if (!args.url) {
    console.error('Usage: node profile-suite.mjs <url> [--selector=CSS] [--width=1440] [--height=900] [--duration=10000]');
    process.exit(1);
  }
  return args;
}

function run(cmd, args, opts={}){
  const res = spawnSync(cmd, args, { stdio: ['ignore','pipe','pipe'], ...opts });
  if (res.status !== 0) {
    console.error(`[ERR] ${cmd} ${args.join(' ')}\n${res.stderr.toString()}`);
    process.exit(res.status||1);
  }
  return res.stdout.toString();
}

function writeJSON(p, obj){ fs.writeFileSync(p, JSON.stringify(obj, null, 2)); }

function loadMetrics(file){
  const s = run('node', ['metrics.mjs', file], { cwd: __dirname });
  return JSON.parse(s);
}

function nowStamp(){
  const d=new Date();
  const pad=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function gitHash(){
  try { return run('git',['rev-parse','--short','HEAD']).trim(); } catch { return 'unknown'; }
}

function summarizeMetrics(m){
  const e=m.tiles.elevation; const v=m.tiles.vector;
  const zsum = o => Object.entries(o).map(([z,kv])=>`z${z}:${kv.count} (${prettyBytes(kv.bytes)})`).join(', ');
  return {
    requests: m.totals.count,
    transfer: prettyBytes(m.totals.bytes),
    elevation: { count: e.totalCount, bytes: prettyBytes(e.totalBytes), encodings: e.encodings, byZoom: e.byZoom },
    vector: { count: v.totalCount, bytes: prettyBytes(v.totalBytes), encodings: v.encodings, byZoom: v.byZoom },
    byType: m.totals.byType,
    byHost: m.totals.byHost,
    top: m.largest.slice(0,5)
  };
}

function main(){
  const args = parseArgs(process.argv);
  const root = path.resolve(__dirname);
  const outDir = path.join(root, 'results', nowStamp());
  fs.mkdirSync(outDir, { recursive: true });
  const meta = { url: args.url, selector: args.selector||null, width: args.width, height: args.height, duration: args.duration, git: gitHash(), ts: new Date().toISOString() };
  writeJSON(path.join(outDir,'meta.json'), meta);

  const scenarios = [
    { name: 'cold',    args: ['capture-har.mjs', args.url, `--width=${args.width}`, `--height=${args.height}`, `--duration=${args.duration}`, `--outfile=har_cold.json`, args.selector?`--selector=${args.selector}`:null].filter(Boolean) },
    { name: 'pan',     args: ['capture-har.mjs', args.url, `--width=${args.width}`, `--height=${args.height}`, `--duration=${args.duration}`, '--panCount=6', '--panFraction=0.25', `--outfile=har_pan.json`, args.selector?`--selector=${args.selector}`:null].filter(Boolean) },
    { name: 'zoomout', args: ['capture-har.mjs', args.url, `--width=${args.width}`, `--height=${args.height}`, '--zoomOut=3', '--zoomDelay=500', `--duration=${Math.max(args.duration,12000)}`, `--outfile=har_zoomout.json`, args.selector?`--selector=${args.selector}`:null].filter(Boolean) },
    { name: 'warm',    args: ['capture-har.mjs', args.url, `--width=${args.width}`, `--height=${args.height}`, `--duration=${args.duration}`, '--reload=1', `--outfile=har_warm.json`, args.selector?`--selector=${args.selector}`:null].filter(Boolean) }
  ];

  const summaries = {};
  for (const s of scenarios) {
    process.stdout.write(`\n[RUN] ${s.name}...\n`);
    run('node', s.args, { cwd: root });
    // The outfile name is in the args array; follow our convention
    const outfile = s.args.find(a=>a.startsWith('--outfile='))?.split('=')[1];
    const harFile = path.join(root, outfile);
    // move HAR into results dir
    fs.renameSync(harFile, path.join(outDir, outfile));
    const metrics = loadMetrics(path.join(outDir, outfile));
    writeJSON(path.join(outDir, `${s.name}.metrics.json`), metrics);
    summaries[s.name] = summarizeMetrics(metrics);
  }

  writeJSON(path.join(outDir, 'summary.json'), { meta, summaries });
  const lines = [];
  lines.push(`# Map Profiling Summary`);
  lines.push(`URL: ${meta.url}`);
  lines.push(`Commit: ${meta.git}`);
  lines.push('');
  for (const [name, s] of Object.entries(summaries)) {
    lines.push(`## ${name}`);
    lines.push(`- requests: ${s.requests}`);
    lines.push(`- transfer: ${s.transfer}`);
    lines.push(`- elevation: ${s.elevation.count} (${s.elevation.bytes}); encodings: ${s.elevation.encodings.join(', ')}`);
    lines.push(`- vector: ${s.vector.count} (${s.vector.bytes}); encodings: ${s.vector.encodings.join(', ')}`);
    lines.push('');
  }
  fs.writeFileSync(path.join(outDir, 'summary.md'), lines.join('\n'));

  console.log(`\nResults written to ${outDir}`);
}

main();
