# Code Structure & Ownership

This document defines the current module boundaries for RPG Demo and the expected data flow across authoring, compile, runtime, and debug views.

## Core Data Flow
1. Author draft (`ASF v4`) is edited in `/demo/author`.
2. `POST /stories/author-assist` returns suggestion-only payload (`suggestions`, `patch_preview`).
3. `POST /stories/compile-author` compiles `ASF v4 -> StoryPack v10`.
4. `POST /stories` stores runtime `StoryPack`.
5. `/sessions/*` executes runtime turns against stored `StoryPack`.

## Story Module Ownership
1. `app/modules/story/router.py`
- HTTP layer only.
- Accepts requests, applies HTTP status/error codes, delegates business logic.

2. `app/modules/story/schemas.py`
- Pydantic request/response/runtime schema definitions for Story APIs.
- `StoryPack` read compatibility includes both `author_source_v3` and `author_source_v4`.

3. `app/modules/story/service_api.py`
- Story API business orchestration: compile+runtime checks+playability assembly.
- Converts structural/runtime validation failures into author-facing diagnostics.

4. `app/modules/story/authoring/`
- `schema_v4.py`: ASF v4 schema definitions.
- `compiler_v4.py`: ASF v4 to StoryPack compiler.
- `diagnostics.py`: authoring diagnostics helpers and required-version messaging.
- `__init__.py`: stable public entry points.

5. `app/modules/story/author_assist.py`
- Assist task orchestration and deterministic fallback.
- Must remain suggestion-only at API semantics level.

## Session Module Ownership
1. `app/modules/session/router.py`
- HTTP endpoints for session lifecycle, step, snapshots, replay, debug views.

2. `app/modules/session/service.py`
- Runtime façade and orchestration.
- Coordinates selection, fallback, narrative generation, state persistence, idempotency, and debug APIs.

3. `app/modules/session/story_runtime/pipeline.py`
- Deterministic runtime step pipeline.
- Consumes injected helpers from `service.py`.

## Guardrails
1. Do not reintroduce author compile paths for pre-v4 formats.
2. Keep `/sessions/*` request/response contracts stable.
3. Keep `LLM_UNAVAILABLE` hard-fail semantics for step application.
4. Keep router files thin; complex orchestration belongs in service modules.
