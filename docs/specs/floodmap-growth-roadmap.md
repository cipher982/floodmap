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
- Ready to start.

### Phase 4 status
- Pending

### Phase 5 status
- Pending

### Phase 6 status
- Pending

### Phase 7 status
- Pending

### Phase 8 status
- Pending

### Phase 9 status
- Pending

### Phase 10 status
- Pending

### Phase 11 status
- Pending
