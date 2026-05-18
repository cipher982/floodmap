/*
 * Small playback controller for the 3D flood demo.
 *
 * It owns timing only. The renderer still owns meshes and controls, which keeps
 * the animation policy out of the WebGL code.
 */

class Terrain3dFloodPlayer {
  constructor({ setValue, min = 0, max = 160, periodMs = 12000, minIntervalMs = 90 }) {
    this.setValue = setValue;
    this.min = min;
    this.max = max;
    this.periodMs = periodMs;
    this.minIntervalMs = minIntervalMs;
    this.playing = false;
    this.startedAt = 0;
    this.lastTickAt = -Infinity;
    this.lastValue = null;
  }

  toggle(now) {
    if (this.playing) {
      this.stop();
      return false;
    }
    this.play(now);
    return true;
  }

  play(now) {
    this.playing = true;
    this.startedAt = now;
    this.lastTickAt = -Infinity;
    this.lastValue = null;
  }

  stop() {
    this.playing = false;
  }

  tick(now) {
    if (!this.playing || now - this.lastTickAt < this.minIntervalMs) return false;
    const cycle = ((now - this.startedAt) % this.periodMs) / this.periodMs;
    const rise = cycle < 0.78
      ? Terrain3dFloodPlayer.smoothstep(cycle / 0.78)
      : 1 - Terrain3dFloodPlayer.smoothstep((cycle - 0.78) / 0.22);
    const value = this.min + (this.max - this.min) * rise;
    const rounded = Number(value.toFixed(value >= 100 ? 0 : 1));
    if (this.lastValue !== null && Math.abs(rounded - this.lastValue) < 0.5) return false;
    this.lastTickAt = now;
    this.lastValue = rounded;
    this.setValue(rounded);
    return true;
  }

  static smoothstep(value) {
    const t = Math.max(0, Math.min(1, value));
    return t * t * (3 - 2 * t);
  }
}

if (typeof window !== "undefined") {
  window.Terrain3dFloodPlayer = Terrain3dFloodPlayer;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { Terrain3dFloodPlayer };
}
