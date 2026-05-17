/*
 * Deterministic shallow-water simulation core for the Flood Sandbox lab.
 *
 * This is intentionally small and dependency-free so it can run in Node tests,
 * browser QA, and as the CPU reference for future WebGPU readback checks.
 */

const FloodSimFixtures = {
  makeScenario(name, width = 96, height = 96) {
    const bed = new Float32Array(width * height);
    const water = new Float32Array(width * height);
    const centerX = (width - 1) / 2;
    const centerY = (height - 1) / 2;

    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const i = y * width + x;
        const dx = (x - centerX) / width;
        const dy = (y - centerY) / height;
        const r = Math.hypot(dx, dy);
        if (name === "slope") {
          bed[i] = 0.075 * (width - x) + 0.04 * Math.sin(y * 0.2);
        } else if (name === "bowl") {
          bed[i] = r * r * 18;
        } else if (name === "ridge") {
          bed[i] = 0.018 * x + (Math.abs(x - centerX) < 3 ? 2.4 : 0);
        } else if (name === "channel") {
          const channel = Math.abs(y - centerY - Math.sin(x * 0.1) * 8);
          bed[i] = 0.16 * (width - x) + Math.min(1.2, channel * 0.12);
        } else {
          bed[i] = 0;
        }
      }
    }

    if (name === "flat") {
      FloodSimFixtures.addDisk(water, width, height, centerX, centerY, width * 0.12, 1.0);
    } else if (name === "slope") {
      FloodSimFixtures.addDisk(water, width, height, width * 0.18, centerY, width * 0.08, 1.4);
    } else if (name === "bowl") {
      FloodSimFixtures.addDisk(water, width, height, width * 0.5, height * 0.22, width * 0.08, 1.2);
    } else if (name === "ridge") {
      FloodSimFixtures.addDisk(water, width, height, width * 0.2, centerY, width * 0.09, 1.4);
    } else if (name === "channel") {
      FloodSimFixtures.addDisk(water, width, height, width * 0.18, centerY, width * 0.08, 1.6);
    } else {
      throw new Error(`Unknown Flood Sandbox scenario: ${name}`);
    }

    return {
      name,
      width,
      height,
      bed,
      water,
      description: FloodSimFixtures.description(name)
    };
  },

  addDisk(target, width, height, cx, cy, radius, amount) {
    for (let y = 0; y < height; y += 1) {
      for (let x = 0; x < width; x += 1) {
        const d = Math.hypot(x - cx, y - cy);
        if (d <= radius) {
          const falloff = 1 - d / Math.max(1, radius);
          target[y * width + x] += amount * (0.35 + 0.65 * falloff);
        }
      }
    }
  },

  description(name) {
    return {
      flat: "Flat plane: water should spread without directional bias.",
      slope: "Tilted plane: water should move downhill across the grid.",
      bowl: "Bowl: water should pool toward the center.",
      ridge: "Ridge: water should split around the barrier.",
      channel: "Channel: water should follow the carved low corridor."
    }[name];
  },

  names() {
    return ["flat", "slope", "bowl", "ridge", "channel"];
  }
};

class FloodSimCpu {
  constructor({ width, height, bed, water = null, cellSize = 10 }) {
    this.width = width;
    this.height = height;
    this.cellSize = cellSize;
    this.bed = new Float32Array(bed);
    this.water = water ? new Float32Array(water) : new Float32Array(width * height);
    this.nextWater = new Float32Array(width * height);
    this.velocityX = new Float32Array(width * height);
    this.velocityY = new Float32Array(width * height);
    this.stepCount = 0;
  }

  clone() {
    return new FloodSimCpu({
      width: this.width,
      height: this.height,
      bed: this.bed,
      water: this.water,
      cellSize: this.cellSize
    });
  }

  index(x, y) {
    return y * this.width + x;
  }

  resetWater(water) {
    this.water.set(water);
    this.nextWater.fill(0);
    this.velocityX.fill(0);
    this.velocityY.fill(0);
    this.stepCount = 0;
  }

  step(options = {}) {
    const dt = options.dt ?? 0.18;
    const conductance = options.conductance ?? 0.19;
    const rainRate = options.rainRate ?? 0;
    const friction = options.friction ?? 0.92;
    const source = options.source ?? null;
    const n = this.width * this.height;
    this.nextWater.set(this.water);
    this.velocityX.fill(0);
    this.velocityY.fill(0);

    if (rainRate > 0) {
      const rain = rainRate * dt;
      for (let i = 0; i < n; i += 1) this.nextWater[i] += rain;
    }

    if (source?.amount > 0) {
      FloodSimFixtures.addDisk(
        this.nextWater,
        this.width,
        this.height,
        source.x,
        source.y,
        source.radius ?? 4,
        source.amount * dt
      );
    }

    for (let y = 0; y < this.height; y += 1) {
      for (let x = 0; x < this.width; x += 1) {
        const i = this.index(x, y);
        const available = Math.max(0, this.water[i]);
        if (available <= 0) continue;

        const surface = this.bed[i] + this.water[i];
        const flows = [];
        let out = 0;
        const consider = (nx, ny, dirX, dirY) => {
          if (nx < 0 || nx >= this.width || ny < 0 || ny >= this.height) return;
          const j = this.index(nx, ny);
          const delta = surface - (this.bed[j] + this.water[j]);
          if (delta <= 0) return;
          const flow = Math.min(available, delta * conductance * dt);
          if (flow <= 0) return;
          flows.push([j, flow, dirX, dirY]);
          out += flow;
        };

        consider(x - 1, y, -1, 0);
        consider(x + 1, y, 1, 0);
        consider(x, y - 1, 0, -1);
        consider(x, y + 1, 0, 1);

        const scale = out > available ? available / out : 1;
        let scaledOut = 0;
        for (const [j, flow, dirX, dirY] of flows) {
          const amount = flow * scale;
          if (amount <= 0) continue;
          this.nextWater[j] += amount;
          this.velocityX[i] += dirX * amount;
          this.velocityY[i] += dirY * amount;
          scaledOut += amount;
        }
        this.nextWater[i] -= scaledOut;
      }
    }

    for (let i = 0; i < n; i += 1) {
      this.water[i] = Math.max(0, this.nextWater[i]);
      this.velocityX[i] *= friction / Math.max(0.001, this.water[i] + 0.1);
      this.velocityY[i] *= friction / Math.max(0.001, this.water[i] + 0.1);
    }
    this.stepCount += 1;
    return this.metrics();
  }

  run(steps, options = {}) {
    let metrics = this.metrics();
    for (let i = 0; i < steps; i += 1) {
      metrics = this.step(options);
      if (metrics.nanCount > 0 || metrics.negativeDepthCount > 0) break;
    }
    return metrics;
  }

  metrics() {
    const n = this.width * this.height;
    let waterMass = 0;
    let wetCells = 0;
    let nanCount = 0;
    let negativeDepthCount = 0;
    let maxDepth = 0;
    let maxVelocity = 0;
    let weightedX = 0;
    let weightedY = 0;

    for (let i = 0; i < n; i += 1) {
      const depth = this.water[i];
      if (!Number.isFinite(depth)) {
        nanCount += 1;
        continue;
      }
      if (depth < -1e-6) negativeDepthCount += 1;
      const clampedDepth = Math.max(0, depth);
      if (clampedDepth > 1e-4) wetCells += 1;
      waterMass += clampedDepth;
      maxDepth = Math.max(maxDepth, clampedDepth);
      const speed = Math.hypot(this.velocityX[i], this.velocityY[i]);
      maxVelocity = Math.max(maxVelocity, speed);
      const x = i % this.width;
      const y = Math.floor(i / this.width);
      weightedX += x * clampedDepth;
      weightedY += y * clampedDepth;
    }

    return {
      step: this.stepCount,
      width: this.width,
      height: this.height,
      waterMass,
      wetCells,
      maxDepth,
      maxVelocity,
      nanCount,
      negativeDepthCount,
      centerOfMassX: waterMass > 0 ? weightedX / waterMass : null,
      centerOfMassY: waterMass > 0 ? weightedY / waterMass : null
    };
  }

  scenarioPass(name, initialMetrics, finalMetrics) {
    const basePass =
      finalMetrics.nanCount === 0 &&
      finalMetrics.negativeDepthCount === 0 &&
      finalMetrics.waterMass > 0 &&
      finalMetrics.maxDepth > 0;
    if (!basePass) return false;

    if (name === "slope" || name === "channel") {
      return finalMetrics.centerOfMassX > initialMetrics.centerOfMassX + 4;
    }
    if (name === "ridge") {
      return (
        finalMetrics.wetCells > initialMetrics.wetCells * 2 &&
        finalMetrics.centerOfMassX < this.width * 0.45
      );
    }
    if (name === "bowl") {
      const cx = (this.width - 1) / 2;
      const cy = (this.height - 1) / 2;
      return (
        Math.abs(finalMetrics.centerOfMassX - cx) < this.width * 0.18 &&
        Math.abs(finalMetrics.centerOfMassY - cy) < this.height * 0.22
      );
    }
    return finalMetrics.wetCells > initialMetrics.wetCells * 1.4;
  }
}

if (typeof window !== "undefined") {
  window.FloodSimFixtures = FloodSimFixtures;
  window.FloodSimCpu = FloodSimCpu;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { FloodSimFixtures, FloodSimCpu };
}
