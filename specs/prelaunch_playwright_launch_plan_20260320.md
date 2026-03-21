# Prelaunch Playwright Launch Plan

## Purpose

This document defines the canonical prelaunch Playwright integration plan for the product-facing app.

It replaces ad hoc manual browser clicking as the release gate for frontend-backend integration.
It does **not** replace:

- backend unit and integration tests
- HTTP smoke checks
- gameplay quality benchmarks under `tools/play_benchmarks/`

Instead, it answers one specific launch question:

> Can a real user, through the deployed frontend only, complete the product loop reliably on the release candidate?

## Release Gate Position

Before production deploy, the system should pass all three layers:

1. backend validation
   - `pytest -q`
2. frontend validation
   - `cd frontend && npm run check`
3. deployed Playwright launch suite
   - same-origin frontend
   - real backend
   - no placeholder client
   - no direct use of `/benchmark/*` by the browser flow

This Playwright plan is the browser-level release gate.

## Current Topology Assumption

This plan assumes the current production topology:

- AWS Ubuntu single host
- `nginx` serving built frontend
- one backend `uvicorn` process
- local persistent SQLite files
- benchmark routes disabled in public deployment

Important current constraint:

- runtime state is persisted, but multi-instance locking is not done
- launch validation should therefore be run against the same single-host topology we plan to ship

## Scope

The Playwright suite covers only product-facing public flows:

- create story
- author loading and completion
- publish into library
- browse/search/filter library
- open story detail
- create play session
- play through turns
- refresh/re-entry recovery on public pages

It must not depend on:

- `/benchmark/*`
- internal diagnostics payloads
- backend-only bundle internals
- placeholder mode

## Success Criteria

The release candidate should be considered browser-ready only if all of the following pass:

- no blocker in `create -> author -> publish -> library -> play`
- no frontend route dead-end
- no browser console error except known non-product noise
- no public API contract mismatch visible in the UI
- refresh recovery works on author loading, story detail, and play session
- deploy topology works with same-origin frontend and nginx proxying
- parallel users do not produce product-visible corruption

## Test Environment

### Environment requirements

- release candidate deployed to AWS Ubuntu staging host
- same nginx and backend process model intended for production
- persistent disk mounted and writable
- real `APP_RESPONSES_*` model configuration
- `APP_ENABLE_BENCHMARK_API=0`
- frontend served from built static assets, not Vite dev mode

### Browser matrix

Minimum:

- Chromium desktop
- WebKit desktop
- mobile viewport on Chromium

Optional final confidence pass:

- Firefox desktop

### Artifact policy

Playwright run artifacts should be written under:

- `output/playwright/launch_readiness/<timestamp>/`

Each failed test should preserve:

- screenshot
- trace
- console log
- network log

## Suite Structure

The suite should be run in four layers, in this order.

### Layer 0: Environment Gate

Goal:

- fail fast if the deployed environment is fundamentally wrong

Checks:

- home page loads
- app routes bootstrap correctly from built frontend
- `/health` returns `ok`
- browser uses HTTP client, not placeholder client
- same-origin API requests resolve correctly through nginx
- no unexpected 404/500 on initial boot

### Layer 1: Core Single-User Product Flow

Goal:

- verify the main loop from the user point of view

Single-user scenarios:

1. `PLW-CORE-001` Create story from seed
   - open `#/create-story`
   - enter English seed
   - request preview
   - verify preview card populates title, premise, structure, flashcards

2. `PLW-CORE-002` Start author job
   - click `Start Authoring`
   - verify route changes to `#/author-jobs/{job_id}`
   - verify loading page renders progress state rather than empty failure shell

3. `PLW-CORE-003` Author loading progression
   - verify progress percentage changes over time
   - verify loading cards appear only when value-bearing
   - verify spotlight card rotates over time
   - verify final state reaches publish-ready UI

4. `PLW-CORE-004` Publish to library
   - click `Publish to Library`
   - verify redirect to library
   - verify newly published story is present and selectable

5. `PLW-CORE-005` Open story detail
   - verify title, premise, structure, cast, protagonist, runtime profile all render
   - verify page semantics match dossier mode rather than play-session mode

6. `PLW-CORE-006` Start play session
   - click `Start Play Session`
   - verify route changes to `#/play/sessions/{session_id}`
   - verify opening narration, protagonist card, state bars, suggested actions render

7. `PLW-CORE-007` Submit first turn
   - type natural-language action
   - verify input enters submitting state
   - verify pending transcript animation appears
   - verify returned narration, feedback, state deltas, history hydration all update

8. `PLW-CORE-008` Complete session
   - submit turns until ending or max public turns
   - verify ending card appears
   - verify input disables on completed session

## Functional Coverage Matrix

### Authoring

Coverage items:

- empty seed validation
- preview request success
- preview refresh after seed edit
- author route creation
- loading card pool behavior
- progress stage text updates
- publish button appears only at completion
- publish redirect lands in library
- publish remains idempotent under accidental repeat click

### Library

Coverage items:

- default list load
- newly published story appears near top
- search with `q`
- theme filter with `theme`
- pagination / cursor load more if exposed in UI
- story detail entry from library card
- back navigation to library preserves context where intended

### Story Detail

Coverage items:

- presentation status
- play overview
- protagonist metadata
- cast manifest
- structure list
- start play CTA
- dossier-specific sidebar semantics

### Play

Coverage items:

- initial transcript
- state bars
- support surface disabled states
- suggestion selection populates input
- manual natural-language input
- submitting animation
- history reconstruction after submit
- ending rendering
- completed-session disabled state

## Recovery and Re-entry Suite

Goal:

- ensure a real deployed app survives refresh and re-entry without breaking user continuity

Scenarios:

1. `PLW-REC-001` Refresh on author loading page
   - start author job
   - refresh while still running
   - verify page rehydrates current job state and continues progressing

2. `PLW-REC-002` Refresh after author completion before publish
   - refresh completed author page
   - verify publish CTA still available

3. `PLW-REC-003` Refresh on story detail page
   - verify detail page rehydrates from public story detail API

4. `PLW-REC-004` Refresh on active play session page
   - submit at least one turn
   - refresh
   - verify transcript restores from public history route
   - verify latest snapshot matches visible state bars and beat metadata

5. `PLW-REC-005` Open play URL directly in fresh tab
   - verify session can re-enter without library round-trip

## Error and Resilience Suite

Goal:

- verify the frontend fails clearly and recoverably when public APIs fail

Scenarios:

1. `PLW-ERR-001` preview request failure
   - simulate backend 5xx or network cut
   - verify visible error message
   - verify user can retry

2. `PLW-ERR-002` author page polling interruption
   - temporary backend unavailability during running job
   - verify page surfaces recoverable error state
   - verify page can recover once backend returns

3. `PLW-ERR-003` publish failure
   - simulate non-200 publish
   - verify page does not navigate away falsely

4. `PLW-ERR-004` play turn timeout/failure
   - simulate turn submit failure
   - verify pending UI clears correctly
   - verify input text is restored rather than lost

5. `PLW-ERR-005` not-found route handling
   - direct open invalid story/session ids
   - verify stable empty/error states instead of broken shell

## Large-Scale Parallel Integration Layer

Goal:

- simulate realistic multi-user release pressure through the frontend

This is the main large-scale Playwright run.

### Proposed worker mix

Run `10` parallel Playwright workers against staging:

- `4` author-heavy workers
  - create preview
  - start author job
  - wait
  - publish
- `4` play-heavy workers
  - use already published stories
  - create sessions
  - play 2-4 turns
  - refresh mid-session
- `2` mixed recovery workers
  - start author
  - publish
  - immediately open story detail and start play
  - refresh during play

### Why this mix

- it matches the real risk surface better than 10 identical users
- it stresses both author write-path and play read/write path
- it tests library freshness under concurrent publishes

### Parallel scenarios

1. `PLW-PAR-001` concurrent author creation
   - 4 workers create stories simultaneously
   - verify all jobs get unique job ids
   - verify all completed jobs can publish

2. `PLW-PAR-002` library freshness under publish churn
   - while author workers publish, player workers open library
   - verify library remains navigable and cards render cleanly

3. `PLW-PAR-003` concurrent play session creation
   - 4 workers create sessions concurrently on same or different stories
   - verify all sessions get unique ids

4. `PLW-PAR-004` concurrent turn submission
   - player workers submit overlapping turns
   - verify no cross-session transcript bleed
   - verify no story/session mix-up in UI

5. `PLW-PAR-005` mixed publish-plus-play race
   - mixed workers publish and then immediately play
   - verify just-published story detail loads without partial UI corruption

### Parallel pass criteria

- zero frontend crash
- zero route mismatch
- zero session transcript cross-contamination
- zero duplicate session id surfaced in UI
- zero publish CTA false-positive after failed publish
- no unhandled console error attributable to product code

## Session Integrity Checks

These assertions should be made inside Playwright during play flows:

- session route hash and returned story title remain consistent
- transcript order is monotonic
- player turn appears before corresponding GM narration
- history length after refresh is not shorter than pre-refresh history
- state bars change only within same session
- completed session disables further submit

## Visual Consistency Checks

These are not pixel-perfect snapshot tests.
They are launch-readiness consistency checks.

Required assertions:

- story detail sidebar uses dossier semantics
- play sidebar uses play semantics
- submitting animation uses the same visual token family as the rest of the product
- author loading and play pending states do not introduce off-brand UI primitives
- mobile viewport does not collapse primary CTA or make transcript unreadable

## Console and Network Policy

Per test, collect:

- browser console logs
- failed network requests

Default failure policy:

- fail on any product JavaScript error
- fail on any failed request to `/author`, `/stories`, `/play`
- allow missing favicon noise only if still present and explicitly allowlisted

## Data and Story Strategy

For launch-readiness Playwright runs:

- use fresh English seeds for author scenarios
- use a mix of newly published and pre-existing stories for play scenarios
- do not rely on benchmark-only seeded manifests

Recommended seed buckets for author workers:

- blackout punishment record
- harbor quarantine manipulation
- ration diversion and infrastructure stress
- archive vote legitimacy crisis

## Proposed Execution Order

### Phase A: Single-user gate

Run all Layer 0 and Layer 1 tests serially.
If any fail, stop.

### Phase B: Recovery gate

Run all recovery tests.
If refresh/re-entry fails anywhere, stop.

### Phase C: Error gate

Run resilience/error tests in controlled conditions.
If pending UI or retry semantics are broken, stop.

### Phase D: Parallel gate

Run 10-worker mixed Playwright integration.
Collect traces for all failures.

### Phase E: Cross-browser confidence

Run reduced smoke subset on WebKit and optional Firefox.

## Exit Criteria For Deployment

Ship only if all of the following are true:

- single-user product flow passes
- recovery tests pass
- error handling tests pass
- 10-worker mixed integration run passes without blocker
- console/network policy stays clean
- no evidence that frontend depends on benchmark-only routes

## Explicit Non-Goals

This plan does not try to cover:

- backend model-quality judgment
- benchmark scoring
- deep token/cost analysis
- multi-instance backend clustering
- load testing at true backend throughput scale

Those belong to other systems.

## Implementation Recommendation

When we implement this plan, use one canonical Playwright launch suite rather than parallel scripts.

Recommended shape:

- `tools/playwright_launch/` or equivalent release-specific tooling
- reusable page helpers for:
  - create story
  - author loading
  - library
  - story detail
  - play session
- one release summary JSON
- one release summary Markdown
- traces/screenshots in `output/playwright/launch_readiness/`

The launch suite should be treated as the browser gate for deployment, not as a benchmark replacement.
