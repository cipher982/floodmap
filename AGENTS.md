# Floodmap (drose.io/floodmap) — Agent Quickstart

This repo powers `https://drose.io/floodmap` (MapLibre + client-side elevation/flood rendering).

## Non‑Negotiables
- Never create/overwrite `.env` (ask before appending).
- Prefer project tooling: `uv run ...` (don’t assume `python` exists).
- Avoid `docker wait` (can hang).

## Fast Checks
- Python unit tests: `uv run pytest tests/unit -q`
- JS unit test: `node --test src/web/js/render-worker.test.mjs`

## Where To Look Next
- Agent docs index: `docs/AGENTS.md`
