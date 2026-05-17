# Flood Sandbox Tier 3 Lab

## Goal

Build FloodMap toward a real-world browser flood sandbox: basemap context,
DEM/HAND terrain inputs, and browser GPU water simulation. The first milestone is
not the public product UI; it is the dev harness that lets agents prove the
simulation is stable, visible, and improving without user QA.

## Milestone 1 Scope

- Dev-only `/sim-lab` page.
- Deterministic synthetic terrain scenarios: flat, slope, bowl, ridge, channel.
- CPU shallow-water reference solver for correctness checks.
- WebGPU two-pass virtual-pipes solver scaffold:
  - compute outflow per cell,
  - gather neighbor outflows,
  - update water depth with ping-pong buffers.
- Browser QA runner that emits screenshots, metrics, and pass/fail summaries.

## Pass Gates

- No console errors or failed browser requests in the lab path.
- WebGPU backend runs at least one scenario when requested.
- No NaN water depths.
- No negative water depths.
- Mass drift stays below 0.5% for closed synthetic scenarios.
- Scenario-specific plausibility checks pass:
  - flat spreads outward,
  - slope moves downhill,
  - bowl pools inward,
  - ridge remains constrained by the barrier,
  - channel follows the carved corridor.

## Artifact Contract

`tools/sim_lab/run_sim_lab_qa.py` writes:

```text
docs/qa/flood-sandbox/runs/<timestamp>/
  summary.json
  summary.md
  metrics/<scenario>.json
  screenshots/<scenario>.png
```

Generated runs are ignored by git. Commit code, specs, and tests; do not commit
large run artifacts.

## Review URLs

WebGPU requires HTTPS or a localhost origin in normal browsers. Direct Cube
review URLs such as `http://100.125.140.78:18000/sim-lab` can serve the lab but
may fall back to CPU. For WebGPU review against Cube, tunnel the Cube app to a
local port and open the localhost URL:

```bash
ssh -N -L 127.0.0.1:18081:100.125.140.78:18000 cube
uv run python tools/sim_lab/run_sim_lab_qa.py --base-url http://127.0.0.1:18081 --backend webgpu
```

## Next Milestone

Feed the lab from one real Birmingham terrain patch. DEM drives the physical
heightfield, HAND supplies drainage-relative context and initialization hints,
and the lab keeps the same screenshot/metrics/pass-fail contract.
