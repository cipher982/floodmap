import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { FloodSimFixtures, FloodSimCpu } = require("./flood-sim-core.js");

test("synthetic scenarios stay finite and non-negative", () => {
  for (const name of FloodSimFixtures.names()) {
    const scenario = FloodSimFixtures.makeScenario(name, 64, 64);
    const sim = new FloodSimCpu(scenario);
    const initial = sim.metrics();
    const final = sim.run(240);

    assert.equal(final.nanCount, 0, name);
    assert.equal(final.negativeDepthCount, 0, name);
    assert.equal(final.waterMass > 0, true, name);
    assert.equal(sim.scenarioPass(name, initial, final), true, name);
  }
});

test("CPU reference conserves water mass without sources", () => {
  const scenario = FloodSimFixtures.makeScenario("channel", 64, 64);
  const sim = new FloodSimCpu(scenario);
  const initial = sim.metrics();
  const final = sim.run(300);
  const drift = Math.abs(final.waterMass - initial.waterMass);

  assert.equal(drift < initial.waterMass * 0.0005, true);
});

test("slope scenario moves water downhill", () => {
  const scenario = FloodSimFixtures.makeScenario("slope", 64, 64);
  const sim = new FloodSimCpu(scenario);
  const initial = sim.metrics();
  const final = sim.run(240);

  assert.equal(final.centerOfMassX > initial.centerOfMassX + 4, true);
});
