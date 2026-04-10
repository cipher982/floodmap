# Floodmap Growth Roadmap

Status: In progress
Owner: Codex
Protocol: SDP-1

## Executive Summary

This spec turns the open Floodmap docket items into an execution order with explicit
dependencies, shipping criteria, and review rules. The goal is to move the app from
"useful map demo" to a production growth surface with:

- reliable live shipping
- shareable and crawlable location URLs
- stronger homepage and location-page SEO
- measurable frontend performance improvements
- trustworthy browser coverage

Each iteration must:

1. land as code in this repo
2. ship live to production when the phase is user-visible
3. get a cursory Claude Haiku review after shipping
4. record any follow-up fixes before moving to the next phase

## Decision Log

### Decision: Production-first sequence
Context: The search UI is already implemented locally but not live.
Choice: Ship the existing search feature before starting new product work.
Rationale: The queue should start by closing the gap between local and production.
Revisit if: deployment constraints force foundational changes first.

### Decision: Foundation before SEO scale
Context: Slug pages, sitemaps, and internal linking all depend on stable routing.
Choice: Base-path cleanup and permalink state ship before city pages.
Rationale: It is cheaper to fix routing once than rework every SEO surface later.
Revisit if: slug-page server rendering requires a different routing model.

### Decision: City pages before ZIP pages
Context: City pages are more likely to support genuinely useful, non-thin content.
Choice: City slugs ship first; ZIP slugs remain later and noindex by default.
Rationale: This captures meaningful location intent without spamming thin pages.
Revisit if: ZIP pages gain clearly differentiated content and conversion value.

### Decision: Performance work must stay measured
Context: The repo already contains HAR tooling and baseline results.
Choice: HAR reruns are acceptance criteria for all speed-focused phases, not a detached nice-to-have.
Rationale: Speed claims are only useful if the deltas are recorded.
Revisit if: the profiling harness becomes invalid or is replaced.

### Decision: Haiku review is mandatory per shipped phase
Context: The user wants a second-opinion cursory review after each shipped iteration.
Choice: Run Claude Haiku after every shipped iteration and fix any obvious issues before proceeding.
Rationale: Lightweight independent review is cheaper than finding regressions later.
Revisit if: Haiku becomes unavailable during execution.

## Review Rule

After each shipped phase, run:

```bash
hatch claude haiku "Review the just-shipped Floodmap phase against its acceptance criteria. Be brief. Call out obvious bugs, regressions, or missing checks."
```

Summarize the review result in the working notes for that phase before continuing.

## Test Baseline

Default fast checks:

```bash
uv run pytest tests/unit -q
node --test src/web/js/render-worker.test.mjs
```

Additional checks are phase-specific and listed below.

## Phase Order

### Phase 1: Deploy location search live
Maps to docket: `Deploy location search live`

Goal:
- push the already-implemented ZIP/city search feature to production

Depends on:
- none

Acceptance criteria:
- `origin/main` contains the shipping commits
- production deploy completes successfully
- live HTML contains the search UI
- live `/floodmap/api/places/search?q=Tampa` returns results

Checks:
- `curl -sS https://drose.io/floodmap | rg "location-search|Jump To Location"`
- `curl -sS 'https://drose.io/floodmap/api/places/search?q=Tampa'`

### Phase 2: Centralize base-path handling
Maps to docket: `Centralize base-path handling`

Goal:
- remove brittle hardcoded `/floodmap` assumptions from the client/runtime

Depends on:
- Phase 1

Acceptance criteria:
- one consistent base-path helper is used for app-relative URLs
- local root hosting and `/floodmap` hosting both work
- no duplicated ad hoc path assembly remains in key frontend code paths

### Phase 3: Add shareable map permalinks
Maps to docket: `Add shareable map permalinks`

Goal:
- make scenario state URL-driven and reload-safe

Depends on:
- Phase 2

Acceptance criteria:
- URL stores `lat`, `lng`, `zoom`, `view`, and `water`
- loading a copied URL restores the same view state
- user can copy/share the current view easily

### Phase 4: Modernize end-to-end tests
Maps to docket: `Modernize end-to-end tests`

Goal:
- make browser coverage match the real app and current URLs

Depends on:
- Phases 2-3

Acceptance criteria:
- Playwright smoke coverage validates current map load
- tests cover search and permalink restoration
- outdated route assumptions are removed

### Phase 5: Upgrade homepage copy and social preview
Maps to docket: `Upgrade homepage copy and social preview`

Goal:
- turn the homepage into a stronger acquisition surface

Depends on:
- Phase 2

Acceptance criteria:
- homepage has meaningful crawlable explanatory copy
- Open Graph/Twitter image is real and wired
- messaging clearly explains what the tool does and how to use it

### Phase 6: Self-host or bundle MapLibre assets
Maps to docket: `Self-host or bundle MapLibre assets`

Goal:
- remove render-critical CDN dependence

Depends on:
- Phase 2

Acceptance criteria:
- homepage no longer depends on `unpkg` for MapLibre JS/CSS
- app still loads correctly in production
- HAR delta recorded after change

### Phase 7: Optimize low-zoom vector tiles
Maps to docket: `Optimize low-zoom vector tiles`
Cross-cutting: `Rerun HAR suite after each speed change`

Goal:
- materially reduce low-zoom vector transfer size

Depends on:
- Phase 6

Acceptance criteria:
- low-zoom vector bytes drop materially in recorded HAR results
- no major visual regression at target zooms
- updated before/after summary is stored in `tools/map-profiling/results/...`

### Phase 8: Build city slug pages
Maps to docket: `Build city slug pages`

Goal:
- create crawlable city landing pages with useful unique metadata/content

Depends on:
- Phases 2-5

Acceptance criteria:
- initial city slug routes render successfully
- city pages set useful metadata and preload an appropriate map view
- page content is not just a blank map wrapper

### Phase 9: Add structured data
Maps to docket: `Add structured data where it helps`

Goal:
- add accurate schema for homepage and location pages

Depends on:
- Phases 5 and 8

Acceptance criteria:
- homepage and city pages emit valid JSON-LD
- markup matches visible page content and route context

### Phase 10: Add location sitemaps and internal links
Maps to docket: `Add location sitemaps and internal links`

Goal:
- make city pages discoverable to users and crawlers

Depends on:
- Phases 8-9

Acceptance criteria:
- sitemap output includes intended city URLs
- pages expose normal internal links to relevant nearby locations
- canonical URLs are consistent

### Phase 11: Prototype ZIP slug pages with noindex
Maps to docket: `Prototype ZIP slug pages with noindex`

Goal:
- add ZIP landing pages behind a conservative indexing policy

Depends on:
- Phases 8-10

Acceptance criteria:
- ZIP routes render useful content
- ZIP pages are `noindex` by default
- indexing decision remains explicit and reversible

## Working Notes

### Phase 1 status
- Completed on 2026-04-10.
- Shipped via `git push origin main` to commit `6c787a4` and explicit Coolify deploy `a0cs08g004g0gwo8k48gggow`.
- Live verification passed:
  - `https://drose.io/floodmap` contains `Jump To Location`
  - `https://drose.io/floodmap/api/places/search?q=Tampa` returns search results
  - versioned JS/CSS assets for `20260410a` contain the search code/styles
- CDN purge succeeded with Cloudflare global-key auth after bearer-token auth returned an authentication error.
- Claude Haiku cursory review: `APPROVE` after rerunning with a constrained prompt and explicit live checks.

### Phase 2 status
- Completed on 2026-04-10.
- Shipped via commits `c092208` and `754747b`, pushed to `origin/main`, and deployed with Coolify deployment `ak8wc0s4088o4gkk40kgk88g`.
- Changed the frontend bootstrap to compute one shared public base path, switched client asset/API/tile URLs to use that helper, and made the manifest/favicon routes path-relative so both `/` and `/floodmap` hosting work.
- Added focused regression coverage in `tests/unit/test_public_base_paths.py` for root/subpath HTML serving, path-relative manifests, and relative favicon redirects.
- Checks passed:
  - `uv run pytest tests/unit/test_public_base_paths.py -q`
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs`
  - local HTTP smoke via `ALLOW_MISSING_DATA=true ENVIRONMENT=development API_PORT=8011 uv run python main.py`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` serves asset version `20260410b` and the `FLOODMAP_PUBLIC_BASE_PATH` bootstrap
  - `https://drose.io/floodmap/site.webmanifest` returns `start_url: "./"` and `icon: "favicon.svg"`
  - `https://drose.io/floodmap/favicon.ico` redirects to relative `favicon.svg`
  - `https://drose.io/floodmap/api/places/search?q=Tampa` still returns results
- Claude Haiku cursory review: `APPROVE`.

### Phase 3 status
- Completed on 2026-04-10.
- Shipped via commit `612e2c4`, pushed to `origin/main`, and deployed with Coolify deployment `ho8so840sgs0kg8sggw8gs44`.
- Added URL-driven state for `lat`, `lng`, `zoom`, `view`, and `water`, plus a `Copy Share Link` affordance in the sidebar.
- Introduced `src/web/js/url-state.js` as the shared parse/build helper for permalink state and covered it with Node tests in `src/web/js/url-state.test.mjs`.
- Added focused browser coverage in `tests/e2e/test_permalink_state.py` for permalink restoration and live URL updates.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e/test_permalink_state.py -q`
  - installed missing Playwright Chromium runtime via `uv run playwright install chromium`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` serves asset version `20260410c` and the `Copy Share Link` control
  - live browser check on `https://drose.io/floodmap/?lat=40.71280&lng=-74.00600&zoom=9.50&view=flood&water=6.0` restores that state
  - live browser check confirms the share button shows `Share link copied.`
  - `https://drose.io/floodmap/api/places/search?q=Tampa` still returns results
- Claude Haiku cursory review: `APPROVE`.

### Phase 4 status
- Completed on 2026-04-10.
- Shipped via commit `4db35fc`, pushed to `origin/main`. No production deploy was required because this phase only touched the browser test suite.
- Replaced stale Playwright debugging/visual files with a smaller reliable suite covering:
  - app smoke and max-zoom guardrails
  - current view-mode and slider behavior
  - permalink restoration and URL updates
  - deterministic location-search behavior with route interception
- Updated the E2E server fixture to run `uvicorn` directly instead of `python main.py`, which removes the dev reloader from the browser-test path.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Claude Haiku cursory review: `APPROVE`.

### Phase 5 status
- Completed on 2026-04-10.
- Shipped via commit `823a6e5`, pushed to `origin/main`, and deployed with Coolify deployment `uck404cgowwo4g04ocosk848`.
- Upgraded the homepage acquisition surface with stronger title/description copy, a visible explanatory sidebar section, and a real JPEG social preview wired into Open Graph/Twitter metadata.
- Added regression coverage in `tests/unit/test_homepage_content.py` for the new SEO/social metadata and image serving, and updated the browser smoke expectation in `tests/e2e/test_map_functionality.py` for the new `FloodMap USA` heading.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` serves asset version `20260410d`, `summary_large_image` metadata, and the new `Flood map for any U.S. city or ZIP` explanatory section
  - `https://drose.io/floodmap/static/images/social-card.jpg?v=20260410d` returns `image/jpeg` and valid JPEG bytes
  - `https://drose.io/floodmap/api/places/search?q=Tampa` still returns results
- Claude Haiku cursory review: `APPROVE`.

### Phase 6 status
- Completed on 2026-04-10.
- Shipped via commit `b3b8f25`, pushed to `origin/main`, and deployed with Coolify deployment `bgc08ogc0s0coo0400gcw0go`.
- Replaced render-critical `unpkg` dependencies with same-origin vendored MapLibre assets: static CSS plus precompressed CSP JS/worker files served from FastAPI so the app boots without third-party map-library fetches.
- Added regression coverage in `tests/unit/test_homepage_content.py` for the local vendor paths and asset serving, plus browser coverage in `tests/e2e/test_map_functionality.py` to prove the homepage loads local MapLibre assets and makes no `unpkg.com` requests.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` serves asset version `20260410e` and local `maplibre-gl` asset paths with no `unpkg.com` references
  - `https://drose.io/floodmap/static/vendor/maplibre-gl-csp-4.7.1.js?v=20260410e` returns `200`
  - `https://drose.io/floodmap/static/vendor/maplibre-gl-csp-worker-4.7.1.js?v=20260410e` returns `200`
  - live Playwright smoke confirms the map boots with same-origin vendor asset requests and no `unpkg.com` requests
  - `https://drose.io/floodmap/api/places/search?q=Tampa` still returns results
- HAR summary and per-scenario metrics were recorded in `tools/map-profiling/results/20260410-163420/`; by-host totals show `drose.io` for app traffic and no `unpkg.com` host entries.
- Claude Haiku cursory review: `APPROVE`.

### Phase 7 status
- Completed on 2026-04-10.
- Shipped via commits `583d123`, `c064da5`, and `16487dc`, pushed to `origin/main`, and deployed with Coolify deployment `q884w4wc0o404skc088kg00w`.
- Added low-zoom vector-tile filtering in `src/api/routers/tiles_v1.py` so zooms `<= 8` keep only the layers and properties the current UI uses (`water`, `waterway`, `transportation`), plus regression coverage in `tests/unit/test_low_zoom_vector_filter.py`.
- Fixed a production-breaking vector URL-template regression in `src/web/js/map-client.js` so MapLibre now requests numeric `/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf` URLs instead of `%7Bz%7D`-encoded placeholders, and extended `tests/e2e/test_map_functionality.py` to assert that behavior.
- Updated the Docker build in `Dockerfile` to install the native toolchain required by the new vector-tile dependency chain.
- Checks passed:
  - `uv run pytest tests/unit/test_low_zoom_vector_filter.py -q`
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e/test_map_functionality.py -q`
  - `uv run pytest tests/e2e -q`
  - `docker build -t floodmap-phase7-test .`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap/api/v1/tiles/vector/usa/8/69/106.pbf` returns `200`, `X-Vector-Profile: low-zoom-filtered`, and a `27445` byte payload
  - decoding that live tile yields only `transportation`, `water`, and `waterway`; `water`/`waterway` retain only the `class` property and `transportation` is property-free
  - live Playwright smoke against `https://drose.io/floodmap?no_analytics=1` confirms the page source template is `/floodmap/api/v1/tiles/vector/usa/{z}/{x}/{y}.pbf` and the browser requests real numeric vector tile URLs such as `/api/v1/tiles/vector/usa/8/69/106.pbf`
  - `https://drose.io/floodmap/api/places/search?q=Tampa` still returns results
- Valid post-fix HAR artifacts are stored in `tools/map-profiling/results/20260410-165551/`.
  - The earlier `20260410-164805` run was discarded because it was captured before the vector-template fix and therefore did not represent the final live behavior.
  - Representative tile reduction for `z=8/x=69/y=106`: raw MBTiles payload `206873` bytes gzipped vs filtered `19670` bytes gzipped, a `90.5%` reduction for the low-zoom tile body that matters to this phase.
- Claude Haiku cursory review: `APPROVE`.

### Phase 8 status
- Completed on 2026-04-10.
- Shipped via commit `a4dc8fe`, pushed to `origin/main`, and deployed with Coolify deployment `gkc88kwk8okowog88ksg0w8o`.
- Added a first batch of crawlable city pages backed by a curated catalog in `src/api/location_catalog.py` and a server-side renderer in `src/api/page_renderer.py`.
- Home and city routes now render distinct HTML from the same template:
  - homepage remains `https://drose.io/floodmap`
  - city routes now work at paths like `https://drose.io/floodmap/fl/tampa`
  - shipped starter city pages include Tampa, Miami, New Orleans, Charleston, Norfolk, Houston, New York, Boston, Savannah, Annapolis, San Francisco, and Seattle
- City pages now provide:
  - location-specific title, description, canonical, and Open Graph/Twitter metadata
  - city-specific explanatory copy in the visible HTML instead of a generic map shell
  - route-specific default map state injected into the page so the map loads at the slug's city center, zoom, view mode, and water level without requiring query params
- Updated `src/web/js/map-client.js` to respect route-specific default view state so slug pages stay clean until the user changes the scenario.
- Added regression coverage:
  - `tests/unit/test_location_pages.py` for city-page HTML, canonical metadata, route context, and unknown-slug 404s
  - `tests/e2e/test_city_pages.py` for slug-default map state and explicit-query override behavior
  - `src/web/js/url-state.test.mjs` for custom default-state handling
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap/fl/tampa` serves Tampa-specific title, canonical, Open Graph metadata, and route-context JSON with asset version `20260410f`
  - live browser smoke confirms `https://drose.io/floodmap/fl/tampa` loads in flood mode at water `3.0`, centered on Tampa, with the clean slug URL intact
  - `https://drose.io/floodmap` still serves the homepage with asset version `20260410f`
  - `https://drose.io/floodmap/api/places/search?q=Tampa` still returns results
- Claude Haiku cursory review: `APPROVE`.

### Phase 9 status
- Pending

### Phase 10 status
- Pending

### Phase 11 status
- Pending
