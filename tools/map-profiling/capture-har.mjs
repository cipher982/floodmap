#!/usr/bin/env node
import { chromium, firefox, webkit } from 'playwright';

function parseArgs(argv) {
  const args = {
    width: 1280,
    height: 800,
    duration: 8000,
    outfile: 'har.json',
    browser: 'chromium',
    interact: true,
    selector: null,
    panFraction: 0.25, // fraction of element size
    panCount: 6,
    panDelay: 400,
    button: 'left',
    modifiers: '',
    // zoom controls
    zoomOut: 0,
    zoomIn: 0,
    zoomDelay: 300,
    zoomMethod: 'wheel', // wheel|keys
    wheelDelta: 300,
    // reload controls (to simulate warm reload within same context)
    reload: 0,
    reloadDelay: 500
  };
  for (const arg of argv.slice(2)) {
    if (!arg.startsWith('--')) { args.url = arg; continue; }
    const [k, v] = arg.replace(/^--/, '').split('=');
    if (v === undefined) {
      args[k] = true;
    } else if (['width','height','duration','panCount'].includes(k)) {
      args[k] = Number(v);
    } else if (['panFraction'].includes(k)) {
      args[k] = Math.max(0.05, Math.min(0.9, Number(v)));
    } else if (['panDelay','zoomDelay','wheelDelta','zoomOut','zoomIn','reload','reloadDelay'].includes(k)) {
      args[k] = Math.max(0, Number(v));
    } else {
      args[k] = v;
    }
  }
  return args;
}

function pickBrowser(name) {
  switch ((name||'').toLowerCase()) {
    case 'firefox': return firefox;
    case 'webkit': return webkit;
    default: return chromium;
  }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function findMapLocator(page, selector) {
  if (selector) return page.locator(selector).first();
  // Heuristics for common map/canvas libraries
  const candidates = [
    'canvas.mapboxgl-canvas',
    '.mapboxgl-canvas',
    '.leaflet-pane.leaflet-map-pane canvas',
    '.leaflet-container canvas',
    '#map canvas',
    '#map',
    'canvas[data-map]',
    'div[role="application"] canvas',
    'canvas'
  ];
  for (const sel of candidates) {
    const loc = page.locator(sel).first();
    try {
      if (await loc.count()) return loc;
    } catch {}
  }
  // Fallback to body
  return page.locator('body');
}

function buildMoves(box, fraction, count) {
  const dx = Math.max(10, Math.floor(box.width * fraction));
  const dy = Math.max(10, Math.floor(box.height * fraction));
  const base = [
    { dx, dy: 0 }, { dx: -dx, dy: 0 },
    { dx: 0, dy }, { dx: 0, dy: -dy },
    { dx: Math.floor(dx*0.75), dy: Math.floor(dy*0.75) },
    { dx: -Math.floor(dx*0.75), dy: -Math.floor(dy*0.75) }
  ];
  if (count <= base.length) return base.slice(0, count);
  // Repeat pattern if more moves requested
  const arr = [];
  while (arr.length < count) arr.push(...base);
  return arr.slice(0, count);
}

async function gentlePan(page, locator, { panFraction, panCount, panDelay, button, modifiers }) {
  const box = await locator.boundingBox();
  if (!box) throw new Error('Target element has no bounding box (not visible yet)');
  const cx = Math.floor(box.x + box.width / 2);
  const cy = Math.floor(box.y + box.height / 2);
  const moves = buildMoves(box, panFraction, panCount);
  // Ensure element is focused to capture events
  try { await locator.scrollIntoViewIfNeeded(); } catch {}
  await page.mouse.move(cx, cy);
  for (const { dx, dy } of moves) {
    if (modifiers) {
      const mods = String(modifiers).split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
      const map = { shift: 'Shift', alt: 'Alt', ctrl: 'Control', meta: 'Meta' };
      const pressed = mods.map(m => map[m]).filter(Boolean);
      if (pressed.length) await page.keyboard.down(pressed[0]);
    }
    await page.mouse.down({ button });
    await page.mouse.move(cx + dx, cy + dy, { steps: 24 });
    await page.mouse.up();
    if (modifiers) {
      const mods = String(modifiers).split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
      const map = { shift: 'Shift', alt: 'Alt', ctrl: 'Control', meta: 'Meta' };
      const pressed = mods.map(m => map[m]).filter(Boolean);
      if (pressed.length) await page.keyboard.up(pressed[0]);
    }
    await sleep(panDelay);
    try { await page.waitForLoadState('networkidle', { timeout: 3000 }); } catch {}
  }
}

async function gentleZoom(page, locator, { zoomOut, zoomIn, zoomDelay, zoomMethod, wheelDelta }) {
  const box = await locator.boundingBox();
  if (!box) return;
  const cx = Math.floor(box.x + box.width / 2);
  const cy = Math.floor(box.y + box.height / 2);
  await page.mouse.move(cx, cy);
  if (zoomMethod === 'keys') {
    for (let i = 0; i < zoomOut; i++) { await page.keyboard.press('-'); await sleep(zoomDelay); try { await page.waitForLoadState('networkidle', { timeout: 3000 }); } catch {} }
    for (let i = 0; i < zoomIn; i++)  { await page.keyboard.press('='); await sleep(zoomDelay); try { await page.waitForLoadState('networkidle', { timeout: 3000 }); } catch {} }
  } else {
    for (let i = 0; i < zoomOut; i++) { await page.mouse.wheel(0, wheelDelta); await sleep(zoomDelay); try { await page.waitForLoadState('networkidle', { timeout: 3000 }); } catch {} }
    for (let i = 0; i < zoomIn; i++)  { await page.mouse.wheel(0, -wheelDelta); await sleep(zoomDelay); try { await page.waitForLoadState('networkidle', { timeout: 3000 }); } catch {} }
  }
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.url) {
    console.error('Usage: node capture-har.mjs <url> [--width=1280] [--height=800] [--duration=8000] [--outfile=har.json] [--browser=chromium|firefox|webkit] [--no-interact] [--zoomOut=3] [--zoomIn=0] [--reload=1]');
    process.exit(1);
  }

  const browserType = pickBrowser(args.browser);
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: args.width, height: args.height },
    ignoreHTTPSErrors: true,
    recordHar: { path: args.outfile, content: 'embed', mode: 'full' }
  });
  const page = await context.newPage();

  try {
    await page.goto(args.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } catch (e) {
    console.error('Navigation failed:', e.message);
  }

  // Let network settle a bit
  try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}

  // Optional warm reload(s) within same context to capture memory/disk cache behavior
  if ((args.reload|0) > 0) {
    for (let i = 0; i < (args.reload|0); i++) {
      try {
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 });
        await page.waitForLoadState('networkidle', { timeout: 15000 });
      } catch (e) { console.error('Reload failed:', e.message); }
      await sleep(args.reloadDelay|0);
    }
  }

  if (args.interact && args.interact !== 'false' && args.interact !== false) {
    try {
      const loc = await findMapLocator(page, args.selector);
      // Optional zooms first to simulate low/high zoom cost
      if ((args.zoomOut|0) > 0 || (args.zoomIn|0) > 0) {
        await gentleZoom(page, loc, {
          zoomOut: args.zoomOut|0,
          zoomIn: args.zoomIn|0,
          zoomDelay: args.zoomDelay|0,
          zoomMethod: args.zoomMethod,
          wheelDelta: args.wheelDelta|0
        });
      }
      await gentlePan(page, loc, {
        panFraction: args.panFraction,
        panCount: args.panCount,
        panDelay: args.panDelay,
        button: args.button,
        modifiers: args.modifiers
      });
    } catch (e) { console.error('Interaction failed:', e.message); }
  }

  // Keep the page open for a bit to capture lazy loads / tiles
  await sleep(args.duration);

  await context.close(); // flush HAR
  await browser.close();
  console.log(`HAR written to ${args.outfile}`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
