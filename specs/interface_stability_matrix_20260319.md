# Interface Stability Matrix

## Purpose

This document defines how product-facing backend data should be treated by frontend and backend engineers.

It works together with:

- `/Users/lishehao/Desktop/Project/RPG_Demo/specs/interface_governance_20260319.md`

This matrix is the practical field-level guide for deciding:

- what the frontend may rely on directly
- what the frontend may use only with graceful fallback
- what must stay out of product UI even if it is technically exposed somewhere

## Stability Tiers

### Stable

Stable fields are part of the core product contract.

Rules:

- frontend may bind to them directly
- semantics must not change silently
- rename/removal requires explicit migration coordination
- tests should protect the shape and meaning

### Additive

Additive fields are product-safe, but optional and evolvable.

Rules:

- frontend may use them
- frontend must degrade gracefully when absent
- backend may add more additive fields without migration
- backend should avoid turning additive fields into required fields without coordination

### Internal-Like

Internal-like fields are not for product UI dependency.

They may be:

- benchmark-only
- provider-facing
- compatibility-exposed but not intended for frontend product binding

Rules:

- frontend must not depend on them
- they may evolve faster
- if the product needs them, promote them into Stable or Additive first

## Author Domain

### `POST /author/story-previews`

Stable:

- `preview_id`
- `prompt_seed`
- `theme`
- `structure`
- `story`
- `cast_slots`
- `beats`
- `flashcards`
- `stage`

Additive:

- `focused_brief`
- `strategies`

Internal-like:

- none in the current preview response

### `POST /author/jobs`
### `GET /author/jobs/{job_id}`

Stable:

- `job_id`
- `status`
- `prompt_seed`
- `preview`
- `progress`
- `error`

Additive:

- `progress_snapshot`
- `cache_metrics`

Internal-like:

- provider/token/cache internals should stay observational only

### `GET /author/jobs/{job_id}/result`

Stable:

- `job_id`
- `status`
- `summary`

Additive:

- `progress_snapshot`
- `cache_metrics`

Internal-like:

- `bundle`
  This field remains exposed for compatibility, but product frontend must not bind to it.

### `GET /author/jobs/{job_id}/events`

Stable:

- SSE event envelope
  - `id`
  - `event`
  - JSON `data`

Additive:

- payload subfields inside event `data`

Internal-like:

- token/cost details should not become frontend hard dependencies

## Library Domain

### `GET /stories`

Stable:

- `stories`
- `meta.total`
- `meta.has_more`
- `meta.next_cursor`
- `meta.limit`
- `meta.sort`
- query params:
  - `q`
  - `theme`
  - `limit`
  - `cursor`
  - `sort`

Additive:

- `meta.query`
- `meta.theme`
- `facets`
- future safe list metadata

Internal-like:

- none

### `GET /stories/{story_id}`

Stable:

- `story`
- `preview`

Additive:

- `presentation`
- `play_overview`

Internal-like:

- raw published bundle storage details

## Play Domain

### `POST /play/sessions`
### `GET /play/sessions/{session_id}`
### `POST /play/sessions/{session_id}/turns`

Stable:

- `session_id`
- `story_id`
- `status`
- `turn_index`
- `beat_index`
- `beat_title`
- `story_title`
- `narration`
- `state_bars`
- `suggested_actions`
- `ending`

Additive:

- `protagonist`
- `feedback`
- `progress`
- `support_surfaces`

Internal-like:

- none inside the public snapshot, but benchmark-only trace data must stay outside this response

### `GET /play/sessions/{session_id}/history`

Stable:

- `session_id`
- `story_id`
- `entries[].speaker`
- `entries[].text`
- `entries[].created_at`
- `entries[].turn_index`

Additive:

- future optional transcript metadata if product UI needs it

Internal-like:

- raw turn traces
- provider/judge/render telemetry

## Benchmark And Diagnostics

Everything under `/benchmark/*` is Internal-like.

Frontend product code must not depend on:

- author diagnostics
- play diagnostics
- turn traces
- provider usage
- judge source distribution
- fallback reason breakdown

If a benchmark-only field becomes genuinely product-useful, promote it by:

1. adding it to public backend contracts
2. adding route/service support
3. adding backend tests
4. mirroring it into frontend contracts
5. then consuming it in UI

## Promotion Rules

Move a field from Additive to Stable when:

- the frontend product depends on it in a durable way
- the field meaning is mature
- the field is expected across environments, not just ideal ones

Move a field from Internal-like to Additive when:

- the UI has a concrete user-facing reason to show it
- the field can be explained without backend/debug vocabulary
- the semantics are stable enough for product use

Do not promote a field just because benchmark tooling finds it useful.

## Current Architecture Decision

As of this document:

- `PlaySessionSnapshot`
- `PublishedStoryDetailResponse`
- `PublishedStoryListResponse`
- `AuthorPreviewResponse`
- `AuthorJobStatusResponse`
- `AuthorJobResultResponse`

are the only product contracts the frontend should build against for the main loop, plus:

- `PlaySessionHistoryResponse`

for transcript restoration.
