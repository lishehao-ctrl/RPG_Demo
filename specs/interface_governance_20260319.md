# Interface Governance

## Purpose

This document is the architecture-level contract governance baseline for the current product.

Field-level usage tiers are defined in:

- `/Users/lishehao/Desktop/Project/RPG_Demo/specs/interface_stability_matrix_20260319.md`

From this point forward:

- backend Pydantic contracts are the canonical source of truth for public HTTP payloads
- frontend API types are a maintained mirror of those contracts
- benchmark and diagnostics payloads stay explicitly separate from product-facing API payloads

The goal is to keep author, library, and play evolving without letting frontend assumptions drift away from backend truth.

## Source Of Truth

### Canonical backend contracts

These files define the public product contract:

- `rpg_backend/author/contracts.py`
- `rpg_backend/library/contracts.py`
- `rpg_backend/play/contracts.py`

These files define internal-only benchmark diagnostics:

- `rpg_backend/benchmark/contracts.py`

### Frontend mirrors

These files mirror the public backend contract:

- `frontend/src/api/contracts.ts`
- `frontend/src/api/route-map.ts`
- `frontend/src/api/http-client.ts`

Frontend mirrors are allowed to be narrower than backend only when the omitted fields are intentionally unused in UI.
They must not invent fields or field meanings that do not exist in backend contracts.

## Public API Surface

### Author domain

- `POST /author/story-previews`
- `POST /author/jobs`
- `GET /author/jobs/{job_id}`
- `GET /author/jobs/{job_id}/events`
- `GET /author/jobs/{job_id}/result`
- `POST /author/jobs/{job_id}/publish`

Public author responses are:

- preview-oriented
- progress-oriented
- publish-oriented

They must not expose raw author bundle internals beyond the currently declared `bundle` field on `AuthorJobResultResponse`.

### Library domain

- `GET /stories`
- `GET /stories/{story_id}`

Current stable query shape for `GET /stories`:

- `q`
- `theme`
- `limit`
- `cursor`
- `sort`

Current stable response shape:

- `stories`
- optional `meta`
- optional `facets`

### Play domain

- `POST /play/sessions`
- `GET /play/sessions/{session_id}`
- `GET /play/sessions/{session_id}/history`
- `POST /play/sessions/{session_id}/turns`

Current stable `PlaySessionSnapshot` surface includes:

- story/session identifiers
- narration
- protagonist
- feedback
- progress
- support surfaces
- state bars
- suggested actions
- ending

This is the product-facing play contract.
It is the only play payload the frontend should bind to by default.
Transcript restoration should use the public history route instead of benchmark diagnostics.

## Internal vs Public Boundary

### Public product API

Public payloads are:

- safe for frontend consumption
- additive-first
- semantically stable across UI iterations

### Internal benchmark API

Benchmark payloads under `/benchmark/...` are:

- local or controlled-environment only
- allowed to change faster
- not part of frontend product compatibility

Frontend must not depend on:

- `BenchmarkAuthorJobDiagnosticsResponse`
- `BenchmarkPlaySessionDiagnosticsResponse`
- turn traces
- provider usage internals
- benchmark-only quality metadata

If a field becomes product-relevant, it should be promoted into the public contracts first rather than consumed from benchmark routes.

## Change Rules

### General

- Change backend contract first.
- Update backend route behavior second.
- Add or update backend tests third.
- Mirror the change into frontend contracts fourth.
- Update frontend client and UI usage last.

### Allowed without migration

- adding optional response fields
- adding new routes
- adding new query params when defaults preserve old behavior
- adding new enum values only if frontend does not assume exhaustive handling

### Not allowed without explicit coordination

- removing public fields
- renaming public fields
- changing field meaning while keeping the same name
- turning optional fields into required fields
- changing enum semantics in a way that breaks existing UI assumptions

### Special rule for benchmark-led development

If a quality or runtime improvement needs new data:

- prefer keeping it internal first
- promote it to the public API only when the frontend has a concrete product use for it

This prevents benchmark instrumentation from leaking into the stable app contract.

## Ownership Model

### Backend owns

- request validation
- response schema
- enum meaning
- pagination/query semantics
- runtime state semantics

### Frontend owns

- view composition
- optional use of stable additive fields
- route transitions
- placeholder compatibility for local UI work

### Architecture owner responsibilities

- decide whether a new field belongs in public API or benchmark API
- prevent duplicate contract definitions with conflicting meaning
- keep `frontend/src/api/contracts.ts` aligned with backend contracts
- refuse UI-only fields that should really be derived presentation

## Current Contract Notes

### Stable and good enough

- author preview/job flow
- library list/detail flow
- play session snapshot flow
- play session public history flow
- additive play feedback payloads
- story detail presentation metadata

### Still intentionally not promoted

- benchmark diagnostics
- raw turn traces
- provider/token/cache internals
- internal closeout reasoning chain

### Still open

- no known public API gap is currently blocking the main frontend flow

## Working Process

For any future frontend-backend interface change:

1. Update backend contract definitions.
2. Update route handlers and service output.
3. Add or adjust backend tests.
4. Mirror type changes into frontend API contracts.
5. Update frontend route/client usage.
6. Update relevant spec docs if the product-facing contract changed.

If a change does not pass all six, it is not considered interface-complete.
