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

### Phase 12: Add live city and ZIP typeahead suggestions
Maps to docket: `Add live city and ZIP typeahead suggestions`

Goal:
- show useful location suggestions while the user types instead of waiting for submit

Depends on:
- Phases 1 and 4

Acceptance criteria:
- typing a city or ZIP shows live suggestions after a debounce
- current submit/search behavior still works as a fallback
- loading, empty, and error states stay understandable

### Phase 13: Add keyboard navigation for location suggestions
Maps to docket: `Add keyboard navigation for location suggestions`

Goal:
- make the suggestion list fully usable without a mouse

Depends on:
- Phase 12

Acceptance criteria:
- arrow keys move through suggestions
- Enter selects the active suggestion
- Escape dismisses the suggestion list cleanly

### Phase 14: Support browser autocomplete and search history in location field
Maps to docket: `Support browser autocomplete and search history in location field`

Goal:
- make the search field cooperate with browser-level history/autocomplete instead of fighting it

Depends on:
- Phase 12

Acceptance criteria:
- the field uses an intentional autocomplete setting
- browser-level history does not conflict badly with live suggestions
- final behavior is covered by tests or explicit rationale

### Phase 15: Stabilize location-search suggestion layout
Maps to docket: follow-up to `Add live city and ZIP typeahead suggestions`
Cross-cutting: `Rerun HAR suite after each speed change`

Goal:
- remove the visible sidebar thrash caused by inline suggestion cards while preserving the search flow

Depends on:
- Phases 12-14

Acceptance criteria:
- live suggestions render as an overlay instead of pushing the rest of the sidebar down
- typeahead stays quiet while typing unless there is an actual error
- keyboard navigation, submit fallback, and selection still work
- updated profiling artifacts are stored in `tools/map-profiling/results/...`

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
- Completed on 2026-04-10.
- Shipped via commit `2dd94b1`, pushed to `origin/main`, and deployed with Coolify deployment `towc4cc4k04ko44csogogcos`.
- Added JSON-LD structured data in `src/api/page_renderer.py`:
  - homepage now emits a `WebSite` + `WebPage` graph
  - city pages now emit a `WebSite` + `WebPage` + `Place` + `BreadcrumbList` graph
- Added a visible breadcrumb on city pages so the breadcrumb markup matches the page that users actually see, with a relative home link that works at both `/` and `/floodmap`.
- Regression coverage added in `tests/unit/test_structured_data.py` for homepage and city-page graph contents, plus an updated browser assertion in `tests/e2e/test_city_pages.py` for the visible breadcrumb.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` serves asset version `20260410g` and a JSON-LD `WebSite`/`WebPage` graph
  - `https://drose.io/floodmap/fl/tampa` serves asset version `20260410g`, a JSON-LD `WebSite`/`WebPage`/`Place`/`BreadcrumbList` graph, and a visible breadcrumb nav
  - live browser smoke confirms the Tampa page still loads in flood mode at water `3.0`, centered on Tampa
  - `https://drose.io/floodmap/api/places/search?q=Tampa` still returns results
- Claude Haiku cursory review: `APPROVE`.

### Phase 10 status
- Completed on 2026-04-10.
- Shipped via commit `aa63f48`, pushed to `origin/main`, and deployed with Coolify deployment `mss8ogok4ko0s88w8cggccwo`.
- Added XML sitemap support in `src/api/sitemaps.py` and route wiring in `src/api/main.py`:
  - `https://drose.io/floodmap/sitemap.xml` now serves a sitemap index
  - `https://drose.io/floodmap/sitemaps/pages.xml` lists the homepage URL
  - `https://drose.io/floodmap/sitemaps/cities.xml` lists the curated city slug URLs
- Added normal internal city links in the rendered HTML:
  - homepage now exposes a `Popular city flood maps` section with direct `<a href>` links to city pages
  - city pages now expose `Related city flood maps` links based on the curated city relationships in `src/api/location_catalog.py`
- Added regression coverage in `tests/unit/test_sitemaps.py` for sitemap XML and internal-link HTML, plus a browser assertion in `tests/e2e/test_city_pages.py` for the related-links section.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap/sitemap.xml` serves a sitemap index with `pages.xml` and `cities.xml`
  - `https://drose.io/floodmap/sitemaps/cities.xml` lists city URLs including Tampa, New York, and Seattle
  - `https://drose.io/floodmap` serves asset version `20260410h` and visible city links such as `/floodmap/fl/tampa`
  - `https://drose.io/floodmap/fl/tampa` serves visible related city links for Miami, Savannah, and New Orleans
  - live browser smoke confirms the Tampa slug page still loads in flood mode at water `3.0`, centered on Tampa
- Claude Haiku cursory review: `APPROVE`.

### Phase 11 status
- Completed on 2026-04-10.
- Shipped via commit `bca5158`, pushed to `origin/main`, and deployed with Coolify deployment `fg8w0k0sos8k4sockksogo40`.
- Added curated ZIP routes in `src/api/location_catalog.py`, server-side ZIP rendering in `src/api/page_renderer.py`, and ZIP route wiring in `src/api/main.py`.
- ZIP pages now provide:
  - useful ZIP-specific copy and tighter default map views for an initial curated set of ZIPs
  - explicit `noindex,follow` control in both HTML metadata and the `X-Robots-Tag` response header
  - breadcrumb/internal-link wiring back to the broader city page
- Added regression coverage:
  - `tests/unit/test_zip_pages.py` for ZIP-page metadata, route context, `X-Robots-Tag`, and 404 handling
  - `tests/e2e/test_zip_pages.py` for ZIP route defaults and explicit-query override behavior
  - updated `tests/unit/test_sitemaps.py` to assert ZIP URLs remain out of published sitemaps
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap/zip/33602` returns `200` with `X-Robots-Tag: noindex, follow`
  - live HTML for `https://drose.io/floodmap/zip/33602` serves asset version `20260410i`, the ZIP-specific title/copy, and `<meta name="robots" content="noindex,follow">`
  - live browser smoke confirms `/floodmap/zip/33602` loads in flood mode at water `3.0`, centered on Tampa ZIP `33602`, with zoom `11.0`
- `https://drose.io/floodmap/sitemap.xml` still omits ZIP URLs and no ZIP sitemap is published
- Claude Haiku cursory review: `APPROVE`.

### Phase 12 status
- Completed on 2026-04-10.
- Shipped via commits `eb585bd` and `b0b7291`, pushed to `origin/main`, and deployed with Coolify deployment `b4oo4k44s80kggsg0k0cgk0g`.
- Added debounced typeahead search in `src/web/js/map-client.js` so the existing places endpoint now powers live city/ZIP suggestions while the user types, without removing the existing `Go`/Enter submit path.
- Updated the search hint copy in `src/web/index.html` to reflect the new suggestion-first flow and added browser coverage in `tests/e2e/test_search_functionality.py` for live suggestions before submit plus selection from the suggestion list.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` serves asset version `20260410j` and the updated search hint text
  - live browser smoke confirms typing `tampa` without pressing `Go` shows multiple suggestions and a status message before submit
  - clicking the first live suggestion sets the input to `Tampa`, shows the `Showing Tampa...` status, and moves the live map to Tampa
- Claude Haiku cursory review: `APPROVE` with no obvious regressions called out.

### Phase 13 status
- Completed on 2026-04-10.
- Shipped via commits `5e4fc67` and `8080e44`, pushed to `origin/main`, and deployed with Coolify deployment `jsgk8c4og480koo4cg8c4gs4`.
- Added keyboard navigation and ARIA state management for search suggestions across `src/web/js/map-client.js`, `src/web/index.html`, and `src/web/css/style.css`:
  - ArrowDown and ArrowUp move the active suggestion
  - Enter selects the active suggestion from the input without needing a mouse
  - Escape dismisses the suggestion list and clears the combobox state cleanly
- Expanded browser coverage in `tests/e2e/test_search_functionality.py` for ArrowDown, ArrowUp, Enter selection, and Escape dismissal. After the Haiku review called out missing ArrowUp coverage, a follow-up test-only commit `e8e9a88` was pushed to close that gap.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e -q`
  - `uv run pytest tests/e2e/test_search_functionality.py -q` after the ArrowUp coverage addition
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` serves asset version `20260410k` plus the listbox/ARIA attributes on the search input and results container
  - live browser smoke confirms ArrowDown activates the second `tampa` suggestion, Enter selects it, dismisses the list, clears `aria-activedescendant`, leaves `aria-expanded=false`, and moves the map to Kansas
  - reopening the suggestions and pressing Escape clears the list, clears `aria-activedescendant`, sets `aria-expanded=false`, and clears the status text
- Claude Haiku cursory review: `APPROVE`, with a minor note about ArrowUp coverage that was addressed immediately in `e8e9a88`.

### Phase 14 status
- Completed on 2026-04-10.
- Shipped via commit `ab806c8`, pushed to `origin/main`, and deployed with Coolify deployment `z0g4w40cs088o0c8k0k844wo`.
- Updated the search input in `src/web/index.html` to stop fighting the browser:
  - added a stable `name="location-query"`
  - changed `autocomplete` from `off` to `on`
- Added explicit regression coverage in `tests/unit/test_homepage_content.py` for the search-input markup contract so the browser-history decision is intentional and visible in tests.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
- Live verification passed after Cloudflare purge:
  - `https://drose.io/floodmap` now serves the search input with `name="location-query"` and `autocomplete="on"`
  - the typeahead and keyboard-navigation flows from Phases 12-13 remain in place
- Claude Haiku cursory review: `APPROVE`, with no regressions called out.

### Phase 15 status
- Completed on 2026-04-10.
- Shipped via commit `1f1f287`, pushed to `origin/main`, and deployed with Coolify deployment `wsokg4sko0g80w484cscgcog`.
- Reworked the location search UI so suggestions no longer live in normal sidebar flow:
  - moved the results/status into a dedicated `.location-search-shell` in `src/web/index.html`
  - switched `.search-results` to an absolute overlay with fixed max height, internal scroll, and clamped metadata rows in `src/web/css/style.css`
  - reduced search DOM churn in `src/web/js/map-client.js` by silencing typeahead status spam, skipping identical status/button rewrites, and swapping results with `replaceChildren(...)`
- Added regression coverage in `tests/e2e/test_search_functionality.py` for layout stability so typing a 3-result query no longer pushes the `Share This View` label down.
- Checks passed:
  - `uv run pytest tests/unit -q`
  - `node --test src/web/js/render-worker.test.mjs src/web/js/url-state.test.mjs`
  - `uv run pytest tests/e2e/test_search_functionality.py -q`
  - `uv run pytest tests/e2e -q`
- Live verification passed after Cloudflare global-key purge:
  - `https://drose.io/floodmap` serves asset version `20260410l` plus the new `.location-search-shell` markup
  - `https://drose.io/floodmap/static/css/style.css?v=20260410l` serves the absolute-positioned `.search-results` overlay with line clamping and stable scrollbar gutter
  - `https://drose.io/floodmap/static/js/map-client.js?v=20260410l` serves the `searchResultsSignature`, `createSearchResultsSignature(...)`, and `replaceChildren(...)` updates
  - live browser measurement on `https://drose.io/floodmap?no_analytics=1` shows the `Share This View` label stays at `280.015625` before and after typing `new`, with the 3-result overlay at `270.4375` px tall
  - pre-change live baseline for the same interaction shifted the `Share This View` label from `306.40625` to `570.984375`, so the visible sidebar shift dropped from `264.578125` px to `0`
  - live smoke confirms clicking the first `tampa` suggestion still shows `Showing Tampa. Click the map for a precise flood-risk sample.` and collapses the list (`aria-expanded=false`)
- Updated HAR artifacts are stored in `tools/map-profiling/results/20260410-181450/`.
  - Compared with the prior speed baseline in `tools/map-profiling/results/20260410-165551/`, this UI-only change produced no meaningful network regression: `warm` stayed effectively flat (`5.07 MB` -> `5.06 MB`), `cold` improved (`1.08 MB` -> `950 kB`), and the rest stayed in the same range.
- Claude Haiku cursory review: `APPROVE` after a constrained real-file review, with only a non-blocking note that more edge-case search tests could be added later.
