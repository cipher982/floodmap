#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const __dirname = path.dirname(new URL(import.meta.url).pathname);

function parseArgs(argv) {
  const args = {
    url: null,
    width: 1440,
    height: 900,
    mode: 'hand',
    sliderSelector: '#water-level',
    warmupMs: 2500,
    settleMs: 2500,
    dragStart: 18,
    dragEnd: 80,
    dragStep: 2,
    dragDelay: 10,
    singleValue: 50,
    scenario: 'both',
    outputDir: null,
    trace: false,
    timeoutMs: 60000
  };

  for (const arg of argv.slice(2)) {
    if (!arg.startsWith('--')) {
      args.url = arg;
      continue;
    }
    const [key, rawValue] = arg.replace(/^--/, '').split('=');
    const value = rawValue === undefined ? true : rawValue;
    if ([
      'width',
      'height',
      'warmupMs',
      'settleMs',
      'dragStart',
      'dragEnd',
      'dragStep',
      'dragDelay',
      'singleValue',
      'timeoutMs'
    ].includes(key)) {
      args[key] = Number(value);
    } else if (key === 'trace') {
      args.trace = value === true || value === 'true' || value === '1';
    } else {
      args[key] = value;
    }
  }

  if (!args.url) {
    console.error('Usage: node slider-profile.mjs <url> [--scenario=single|drag|both] [--width=1440] [--height=900] [--mode=hand] [--trace]');
    process.exit(1);
  }
  if (!['single', 'drag', 'both'].includes(args.scenario)) {
    console.error('--scenario must be one of: single, drag, both');
    process.exit(1);
  }
  return args;
}

function nowStamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function writeJSON(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

function percentile(sorted, q) {
  if (!sorted.length) return null;
  return sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)))];
}

function summarize(values) {
  if (!values.length) return { count: 0 };
  const sorted = [...values].sort((a, b) => a - b);
  const total = values.reduce((sum, value) => sum + value, 0);
  return {
    count: values.length,
    min: sorted[0],
    p50: percentile(sorted, 0.5),
    p90: percentile(sorted, 0.9),
    p95: percentile(sorted, 0.95),
    max: sorted[sorted.length - 1],
    avg: total / values.length
  };
}

function metricMap(metricsResponse) {
  return Object.fromEntries(metricsResponse.metrics.map((metric) => [metric.name, metric.value]));
}

function metricDelta(after, before, name) {
  return (after[name] || 0) - (before[name] || 0);
}

function buildDragValues(args) {
  const values = [];
  const step = Math.abs(args.dragStep) || 1;
  const direction = args.dragEnd >= args.dragStart ? 1 : -1;
  for (
    let value = args.dragStart;
    direction > 0 ? value <= args.dragEnd : value >= args.dragEnd;
    value += direction * step
  ) {
    values.push(value);
  }
  for (
    let value = args.dragEnd - direction * step;
    direction > 0 ? value >= args.dragStart : value <= args.dragStart;
    value -= direction * step
  ) {
    values.push(value);
  }
  return values;
}

function summarizeRequests(responses) {
  const summary = {};
  for (const response of responses) {
    const headerBits = [
      response.status,
      response.headers['x-cache'] || '',
      response.headers['x-terrain-source'] || response.headers['x-tile-source'] || '',
      response.headers['content-encoding'] || 'identity'
    ];
    const key = headerBits.join(' ').trim();
    summary[key] = (summary[key] || 0) + 1;
  }
  return summary;
}

async function waitForAppReady(page, timeoutMs) {
  await page.goto(page.__profileUrl, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
  await page.waitForFunction(
    '() => Boolean(window.floodMap && window.floodMap.map && window.floodMap.map.loaded())',
    { timeout: timeoutMs }
  );
  try {
    await page.waitForFunction(
      '() => !window.floodMap.map.areTilesLoaded || window.floodMap.map.areTilesLoaded()',
      { timeout: Math.min(timeoutMs, 20000) }
    );
  } catch {}
}

async function installInstrumentation(page) {
  return await page.evaluate(() => {
    const summarizeState = () => {
      const fm = window.floodMap;
      if (!fm) return null;
      return {
        href: window.location.href,
        viewMode: fm.viewMode,
        water: fm.currentWaterLevel,
        zoom: fm.map?.getZoom?.() ?? null,
        center: fm.map?.getCenter?.() ?? null,
        workerReady: !!fm.workerReady,
        tileUrl: typeof fm.getTileUrl === 'function' ? fm.getTileUrl() : null,
        rendererStats: fm.elevationRenderer?.getStats?.() ?? null,
        tileDebug: fm.tileDebug ?? null,
        handGpuStats: fm.handGpuStats ?? fm.handGpuLayer?.getStats?.() ?? null,
        terrainConfig: fm.getTerrainLayerConfig?.('hand') ?? null,
        webgl2: !!document.querySelector('#map canvas')?.getContext?.('webgl2'),
        webgpu: !!navigator.gpu,
        offscreenCanvas: typeof OffscreenCanvas !== 'undefined'
      };
    };

    window.__fmPerf = {
      updateCalls: 0,
      updateDurations: [],
      generateCalls: 0,
      generateDurations: [],
      workerCalls: 0,
      workerDurations: [],
      loadTerrainCalls: 0,
      loadTerrainDurations: [],
      inputEvents: [],
      inputToNextFrame: [],
      longTasks: [],
      frames: [],
      wrapped: [],
      missing: [],
      initialState: summarizeState()
    };

    const perf = window.__fmPerf;
    const fm = window.floodMap;
    const wrapSync = (obj, name, counter, durations) => {
      if (!obj || typeof obj[name] !== 'function') {
        perf.missing.push(name);
        return;
      }
      const original = obj[name].bind(obj);
      perf.wrapped.push(name);
      obj[name] = function wrappedSync(...args) {
        const start = performance.now();
        perf[counter] += 1;
        try {
          return original(...args);
        } finally {
          perf[durations].push(performance.now() - start);
        }
      };
    };
    const wrapAsync = (obj, name, counter, durations) => {
      if (!obj || typeof obj[name] !== 'function') {
        perf.missing.push(name);
        return;
      }
      const original = obj[name].bind(obj);
      perf.wrapped.push(name);
      obj[name] = async function wrappedAsync(...args) {
        const start = performance.now();
        perf[counter] += 1;
        try {
          return await original(...args);
        } finally {
          perf[durations].push(performance.now() - start);
        }
      };
    };

    wrapSync(fm, 'updateFloodLayer', 'updateCalls', 'updateDurations');
    wrapAsync(fm, 'generateTile', 'generateCalls', 'generateDurations');
    wrapAsync(fm, 'renderTileInWorker', 'workerCalls', 'workerDurations');
    wrapAsync(fm?.elevationRenderer, 'loadTerrainTile', 'loadTerrainCalls', 'loadTerrainDurations');

    if (window.PerformanceObserver) {
      try {
        perf.longTaskObserver = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            perf.longTasks.push({ startTime: entry.startTime, duration: entry.duration });
          }
        });
        perf.longTaskObserver.observe({ type: 'longtask', buffered: true });
      } catch (error) {
        perf.longTaskError = String(error);
      }
    }

    let lastFrame = performance.now();
    let frameCount = 0;
    function frame(timestamp) {
      perf.frames.push(timestamp - lastFrame);
      lastFrame = timestamp;
      frameCount += 1;
      if (frameCount < 900) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return { wrapped: perf.wrapped, missing: perf.missing, initialState: perf.initialState };
  });
}

async function collectPerf(page) {
  return await page.evaluate(() => {
    const perf = window.__fmPerf;
    const summarizeValues = (values) => {
      if (!values.length) return { count: 0 };
      const sorted = [...values].sort((a, b) => a - b);
      const pick = (q) => sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)))];
      return {
        count: values.length,
        min: sorted[0],
        p50: pick(0.5),
        p90: pick(0.9),
        p95: pick(0.95),
        max: sorted[sorted.length - 1],
        avg: values.reduce((sum, value) => sum + value, 0) / values.length
      };
    };
    const fm = window.floodMap;
    return {
      wrapped: perf.wrapped,
      missing: perf.missing,
      updateCalls: perf.updateCalls,
      updateDurations: summarizeValues(perf.updateDurations),
      generateCalls: perf.generateCalls,
      generateDurations: summarizeValues(perf.generateDurations),
      workerCalls: perf.workerCalls,
      workerDurations: summarizeValues(perf.workerDurations),
      loadTerrainCalls: perf.loadTerrainCalls,
      loadTerrainDurations: summarizeValues(perf.loadTerrainDurations),
      inputEvents: perf.inputEvents.length,
      inputToNextFrame: summarizeValues(perf.inputToNextFrame),
      longTasks: summarizeValues(perf.longTasks.map((entry) => entry.duration)),
      longTaskTotalMs: perf.longTasks.reduce((sum, entry) => sum + entry.duration, 0),
      frames: summarizeValues(perf.frames.slice(5)),
      frameOver16: perf.frames.filter((value) => value > 16.7).length,
      frameOver33: perf.frames.filter((value) => value > 33.4).length,
      finalState: {
        href: window.location.href,
        viewMode: fm?.viewMode ?? null,
        water: fm?.currentWaterLevel ?? null,
        tileUrl: typeof fm?.getTileUrl === 'function' ? fm.getTileUrl() : null,
        rendererStats: fm?.elevationRenderer?.getStats?.() ?? null,
        tileDebug: fm?.tileDebug ?? null,
        handGpuStats: fm?.handGpuStats ?? fm?.handGpuLayer?.getStats?.() ?? null
      }
    };
  });
}

async function ensureMode(page, mode, settleMs) {
  await page.evaluate(async ({ mode: targetMode }) => {
    const fm = window.floodMap;
    if (!fm || fm.viewMode === targetMode) return;
    const label = document.querySelector(`label[for="${targetMode}-mode"]`);
    if (label) label.click();
    await new Promise((resolve) => setTimeout(resolve, 300));
  }, { mode });
  await page.waitForTimeout(Math.min(500, settleMs));
}

async function dispatchSliderValues(page, selector, values, delayMs) {
  await page.evaluate(async ({ selector: sliderSelector, values: sliderValues, delayMs: delay }) => {
    const slider = document.querySelector(sliderSelector);
    if (!slider) throw new Error(`Slider not found: ${sliderSelector}`);
    const perf = window.__fmPerf;
    for (const value of sliderValues) {
      const start = performance.now();
      perf.inputEvents.push({ value, start });
      slider.value = String(value);
      slider.dispatchEvent(new Event('input', { bubbles: true }));
      requestAnimationFrame((timestamp) => {
        perf.inputToNextFrame.push(timestamp - start);
      });
      if (delay > 0) {
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }
  }, { selector, values, delayMs });
}

async function runScenario(browser, args, outDir, scenarioName) {
  const context = await browser.newContext({
    viewport: { width: args.width, height: args.height },
    ignoreHTTPSErrors: true
  });
  const tracePath = path.join(outDir, `${scenarioName}.trace.zip`);
  if (args.trace) {
    await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  }

  const page = await context.newPage();
  page.__profileUrl = args.url;

  const requests = [];
  const responses = [];
  const failures = [];
  const consoleMessages = [];
  const pageErrors = [];
  page.on('request', (request) => {
    requests.push({ url: request.url(), method: request.method(), ts: performance.now() });
  });
  page.on('requestfailed', (request) => {
    failures.push({ url: request.url(), failure: request.failure(), ts: performance.now() });
  });
  page.on('response', async (response) => {
    const url = response.url();
    if (!url.includes('/api/v2/terrain/') && !url.includes('/api/v1/tiles/elevation-data/')) return;
    responses.push({
      url,
      status: response.status(),
      headers: await response.allHeaders(),
      ts: performance.now()
    });
  });
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      consoleMessages.push({
        type: message.type(),
        text: message.text(),
        ts: performance.now()
      });
    }
  });
  page.on('pageerror', (error) => {
    pageErrors.push({
      message: error.message,
      stack: error.stack,
      ts: performance.now()
    });
  });

  await waitForAppReady(page, args.timeoutMs);
  await ensureMode(page, args.mode, args.settleMs);
  await page.waitForTimeout(args.warmupMs);

  const install = await installInstrumentation(page);
  const cdp = await context.newCDPSession(page);
  await cdp.send('Performance.enable', { timeDomain: 'threadTicks' });
  const beforeMetrics = metricMap(await cdp.send('Performance.getMetrics'));
  const requestStart = requests.length;
  const responseStart = responses.length;
  const failureStart = failures.length;
  const consoleStart = consoleMessages.length;
  const pageErrorStart = pageErrors.length;

  const wallStart = performance.now();
  if (scenarioName === 'single') {
    await dispatchSliderValues(page, args.sliderSelector, [args.singleValue], 0);
  } else if (scenarioName === 'drag') {
    await dispatchSliderValues(page, args.sliderSelector, buildDragValues(args), args.dragDelay);
  } else {
    throw new Error(`Unknown scenario: ${scenarioName}`);
  }
  const dispatchMs = performance.now() - wallStart;

  try {
    await page.waitForFunction(
      '() => !window.floodMap?.map?.areTilesLoaded || window.floodMap.map.areTilesLoaded()',
      { timeout: Math.max(1000, args.settleMs) }
    );
  } catch {}
  await page.waitForTimeout(args.settleMs);

  const afterMetrics = metricMap(await cdp.send('Performance.getMetrics'));
  const perf = await collectPerf(page);
  const newResponses = responses.slice(responseStart);

  const result = {
    scenario: scenarioName,
    meta: {
      url: args.url,
      mode: args.mode,
      viewport: { width: args.width, height: args.height },
      ts: new Date().toISOString()
    },
    install,
    wallMs: performance.now() - wallStart,
    dispatchMs,
    requestCount: requests.length - requestStart,
    terrainResponseCount: newResponses.length,
    terrainResponseSummary: summarizeRequests(newResponses),
    failures: failures.slice(failureStart),
    consoleMessages: consoleMessages.slice(consoleStart),
    pageErrors: pageErrors.slice(pageErrorStart),
    cdpDelta: {
      TaskDuration: metricDelta(afterMetrics, beforeMetrics, 'TaskDuration'),
      ScriptDuration: metricDelta(afterMetrics, beforeMetrics, 'ScriptDuration'),
      LayoutDuration: metricDelta(afterMetrics, beforeMetrics, 'LayoutDuration'),
      RecalcStyleDuration: metricDelta(afterMetrics, beforeMetrics, 'RecalcStyleDuration'),
      JSHeapUsedSize: metricDelta(afterMetrics, beforeMetrics, 'JSHeapUsedSize'),
      JSHeapTotalSize: metricDelta(afterMetrics, beforeMetrics, 'JSHeapTotalSize')
    },
    perf
  };

  if (args.trace) {
    await context.tracing.stop({ path: tracePath });
    result.tracePath = tracePath;
  }

  await context.close();
  return result;
}

function formatMs(value) {
  if (value == null || Number.isNaN(value)) return 'n/a';
  return `${value.toFixed(1)} ms`;
}

function writeSummary(outDir, results) {
  const lines = ['# Slider Profile Summary', ''];
  for (const result of results) {
    const perf = result.perf;
    lines.push(`## ${result.scenario}`);
    lines.push(`- wall: ${formatMs(result.wallMs)}; dispatch: ${formatMs(result.dispatchMs)}`);
    lines.push(`- update calls: ${perf.updateCalls}; generate calls: ${perf.generateCalls}; worker calls: ${perf.workerCalls}; terrain load calls: ${perf.loadTerrainCalls}`);
    lines.push(`- worker p50/p95/max: ${formatMs(perf.workerDurations.p50)} / ${formatMs(perf.workerDurations.p95)} / ${formatMs(perf.workerDurations.max)}`);
    lines.push(`- generate p50/p95/max: ${formatMs(perf.generateDurations.p50)} / ${formatMs(perf.generateDurations.p95)} / ${formatMs(perf.generateDurations.max)}`);
    lines.push(`- input to next frame p50/p95: ${formatMs(perf.inputToNextFrame.p50)} / ${formatMs(perf.inputToNextFrame.p95)}`);
    lines.push(`- frames >16.7ms: ${perf.frameOver16}; >33.4ms: ${perf.frameOver33}; long tasks: ${perf.longTasks.count || 0}`);
    lines.push(`- terrain responses: ${result.terrainResponseCount}; requests: ${result.requestCount}`);
    lines.push(`- CDP TaskDuration delta: ${formatMs(result.cdpDelta.TaskDuration * 1000)}`);
    if (result.consoleMessages.length || result.pageErrors.length) {
      lines.push(`- console/page errors: ${result.consoleMessages.length} console; ${result.pageErrors.length} page`);
    }
    if (perf.finalState?.handGpuStats) {
      lines.push(`- hand GPU stats: \`${JSON.stringify(perf.finalState.handGpuStats)}\``);
    }
    lines.push('');
  }
  fs.writeFileSync(path.join(outDir, 'summary.md'), `${lines.join('\n')}\n`);
}

async function main() {
  const args = parseArgs(process.argv);
  const outDir = args.outputDir
    ? path.resolve(args.outputDir)
    : path.join(__dirname, 'results', `${nowStamp()}-slider`);
  fs.mkdirSync(outDir, { recursive: true });
  writeJSON(path.join(outDir, 'meta.json'), {
    ...args,
    outputDir: outDir,
    ts: new Date().toISOString()
  });

  const scenarios = args.scenario === 'both' ? ['single', 'drag'] : [args.scenario];
  const browser = await chromium.launch({
    headless: true,
    args: [
      '--disable-background-timer-throttling',
      '--disable-backgrounding-occluded-windows'
    ]
  });
  const results = [];
  try {
    for (const scenario of scenarios) {
      process.stdout.write(`[slider-profile] ${scenario}\n`);
      const result = await runScenario(browser, args, outDir, scenario);
      results.push(result);
      writeJSON(path.join(outDir, `${scenario}.json`), result);
    }
  } finally {
    await browser.close();
  }

  writeJSON(path.join(outDir, 'summary.json'), { results });
  writeSummary(outDir, results);
  console.log(`Results written to ${outDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
