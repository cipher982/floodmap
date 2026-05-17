/*
 * Flood Sandbox lab controller.
 *
 * This page is a dev-only harness: it makes the simulation observable through
 * deterministic scenarios, metrics, screenshots, and a stable window API for
 * Playwright/agent QA.
 */

(function () {
  const params = new URLSearchParams(window.location.search);
  const scenarioName = params.get("scenario") || "bowl";
  const steps = Number.parseInt(params.get("steps") || "360", 10);
  const size = Number.parseInt(params.get("size") || "96", 10);
  const backendPreference = params.get("backend") || "auto";
  const autorun = params.get("autorun") === "1";

  const canvas = document.getElementById("sim-canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: false });
  const scenarioSelect = document.getElementById("scenario-select");
  const backendSelect = document.getElementById("backend-select");
  const runButton = document.getElementById("run-button");
  const stepButton = document.getElementById("step-button");
  const resetButton = document.getElementById("reset-button");
  const statusEl = document.getElementById("status");
  const metricsEl = document.getElementById("metrics");

  let scenario = null;
  let cpuSim = null;
  let gpuSim = null;
  let activeBackend = "cpu";
  let initialMetrics = null;
  let finalMetrics = null;
  let running = false;
  let lastFrameAt = performance.now();

  function setupControls() {
    for (const name of window.FloodSimFixtures.names()) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      scenarioSelect.append(option);
    }
    scenarioSelect.value = scenarioName;
    backendSelect.value = backendPreference;
    scenarioSelect.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("scenario", scenarioSelect.value);
      window.location.href = url.toString();
    });
    backendSelect.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("backend", backendSelect.value);
      window.location.href = url.toString();
    });
    runButton.addEventListener("click", () => void runToCompletion(steps));
    stepButton.addEventListener("click", () => void runSteps(1));
    resetButton.addEventListener("click", () => void reset());
  }

  async function reset() {
    scenario = window.FloodSimFixtures.makeScenario(scenarioSelect.value, size, size);
    cpuSim = new window.FloodSimCpu(scenario);
    gpuSim = null;
    activeBackend = "cpu";
    initialMetrics = cpuSim.metrics();
    finalMetrics = initialMetrics;
    window.floodSimLab.summary = null;
    await maybeInitGpu();
    draw(cpuSim.water);
    publishStatus("ready");
  }

  async function maybeInitGpu() {
    if (backendSelect.value === "cpu") return;
    if (!window.FloodSimWebGpu || !(await window.FloodSimWebGpu.isSupported())) {
      publishStatus("WebGPU unavailable; using CPU reference");
      return;
    }
    try {
      gpuSim = await new window.FloodSimWebGpu(scenario).init();
      activeBackend = "webgpu";
      const info = await gpuSim.adapterInfo();
      window.floodSimLab.webgpu = { supported: true, adapter: info };
    } catch (error) {
      window.floodSimLab.webgpu = {
        supported: false,
        error: error?.message || String(error)
      };
      gpuSim = null;
      activeBackend = "cpu";
    }
  }

  async function runSteps(count) {
    const started = performance.now();
    if (activeBackend === "webgpu" && gpuSim) {
      for (let i = 0; i < count; i += 1) gpuSim.step();
      const water = await gpuSim.readWaterBuffer();
      cpuSim.water.set(water);
      cpuSim.stepCount = gpuSim.stepCount;
      finalMetrics = cpuSim.metrics();
      draw(water);
    } else {
      for (let i = 0; i < count; i += 1) finalMetrics = cpuSim.step();
      draw(cpuSim.water);
    }
    window.floodSimLab.lastStepMs = performance.now() - started;
    publishStatus(running ? "running" : "stepped");
  }

  async function runToCompletion(targetSteps) {
    if (running) return;
    running = true;
    const started = performance.now();
    const chunk = 20;
    while (running && cpuSim.stepCount < targetSteps) {
      await runSteps(Math.min(chunk, targetSteps - cpuSim.stepCount));
      if (finalMetrics.nanCount > 0 || finalMetrics.negativeDepthCount > 0) break;
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    running = false;
    const massDriftRatio = Math.abs(finalMetrics.waterMass - initialMetrics.waterMass) /
      Math.max(1e-6, initialMetrics.waterMass);
    const pass = cpuSim.scenarioPass(scenario.name, initialMetrics, finalMetrics) &&
      massDriftRatio < 0.005;
    window.floodSimLab.summary = {
      done: true,
      pass,
      scenario: scenario.name,
      backend: activeBackend,
      steps: cpuSim.stepCount,
      elapsedMs: performance.now() - started,
      massDriftRatio,
      initialMetrics,
      finalMetrics,
      webgpu: window.floodSimLab.webgpu,
      failures: buildFailures(pass, finalMetrics, massDriftRatio)
    };
    publishStatus(pass ? "pass" : "fail");
  }

  function buildFailures(pass, metrics, massDriftRatio) {
    const failures = [];
    if (metrics.nanCount > 0) failures.push("NaN depth values");
    if (metrics.negativeDepthCount > 0) failures.push("negative depth values");
    if (!(metrics.waterMass > 0)) failures.push("no water mass");
    if (!(metrics.maxDepth > 0)) failures.push("no visible depth");
    if (massDriftRatio >= 0.005) failures.push(`mass drift ${(massDriftRatio * 100).toFixed(3)}%`);
    if (!pass && failures.length === 0) failures.push("scenario-specific plausibility check failed");
    return failures;
  }

  function draw(water) {
    const image = ctx.createImageData(canvas.width, canvas.height);
    const scaleX = scenario.width / canvas.width;
    const scaleY = scenario.height / canvas.height;
    const bed = scenario.bed;
    const maxDepth = Math.max(0.01, finalMetrics?.maxDepth || 1);
    for (let py = 0; py < canvas.height; py += 1) {
      for (let px = 0; px < canvas.width; px += 1) {
        const x = Math.min(scenario.width - 1, Math.floor(px * scaleX));
        const y = Math.min(scenario.height - 1, Math.floor(py * scaleY));
        const i = y * scenario.width + x;
        const terrain = Math.max(0, Math.min(1, bed[i] / 5));
        const depth = Math.max(0, water[i]);
        const depthT = Math.min(1, depth / maxDepth);
        const o = (py * canvas.width + px) * 4;
        const dry = 222 - terrain * 110;
        image.data[o] = dry * 0.74;
        image.data[o + 1] = dry * 0.86;
        image.data[o + 2] = dry * 0.62;
        image.data[o + 3] = 255;
        if (depth > 0.002) {
          image.data[o] = 35 + depthT * 12;
          image.data[o + 1] = 120 + depthT * 40;
          image.data[o + 2] = 210 + depthT * 35;
        }
      }
    }
    ctx.putImageData(image, 0, 0);
    drawVelocityOverlay();
  }

  function drawVelocityOverlay() {
    ctx.save();
    ctx.globalAlpha = 0.55;
    ctx.strokeStyle = "#e8fbff";
    ctx.lineWidth = 1;
    const stride = 12;
    for (let y = 4; y < scenario.height; y += stride) {
      for (let x = 4; x < scenario.width; x += stride) {
        const i = y * scenario.width + x;
        const vx = cpuSim.velocityX[i] || 0;
        const vy = cpuSim.velocityY[i] || 0;
        const speed = Math.hypot(vx, vy);
        if (speed < 0.0005) continue;
        const sx = (x / scenario.width) * canvas.width;
        const sy = (y / scenario.height) * canvas.height;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(sx + vx * 90, sy + vy * 90);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  function publishStatus(state) {
    const now = performance.now();
    const frameMs = now - lastFrameAt;
    lastFrameAt = now;
    const payload = {
      state,
      scenario: scenario?.name,
      backend: activeBackend,
      step: cpuSim?.stepCount ?? 0,
      frameMs,
      metrics: finalMetrics,
      webgpu: window.floodSimLab.webgpu
    };
    statusEl.textContent = `${state.toUpperCase()} | ${payload.scenario} | ${payload.backend} | step ${payload.step}`;
    metricsEl.textContent = JSON.stringify(payload, null, 2);
    window.floodSimLab.status = payload;
  }

  async function boot() {
    window.floodSimLab = {
      version: "20260517-tier3-lab-a",
      status: null,
      summary: null,
      webgpu: { supported: !!navigator.gpu },
      runToCompletion,
      runSteps,
      reset
    };
    setupControls();
    await reset();
    if (autorun) void runToCompletion(steps);
  }

  void boot().catch((error) => {
    window.floodSimLab = window.floodSimLab || {};
    window.floodSimLab.summary = {
      done: true,
      pass: false,
      failures: [error?.message || String(error)]
    };
    publishStatus("error");
    throw error;
  });
})();
