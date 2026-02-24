# Code Structure & Ownership

This document defines the current module boundaries after the backend refactor (PR1-PR5), and the guardrails for long-term development.
For Chinese deep-dive boundary and troubleshooting guidance, see `docs/architecture-llm-boundary-zh.md`.

## Core Product Flow
1. Author draft (`ASF v4`) is edited in `/demo/author`.
2. `POST /stories/author-assist` returns suggestion payload (`suggestions`, `patch_preview`) only.
3. `POST /stories/compile-author` compiles `ASF v4 -> StoryPack v10`.
4. `POST /stories` stores runtime `StoryPack`.
5. `/sessions/*` executes deterministic runtime progression against stored StoryPack.

## Layering (Backend)
1. HTTP layer (`router`)
- `app/modules/story/router.py`
- `app/modules/session/router.py`
- Responsibility: request parsing, response shape, status-code mapping.

2. Application orchestration layer
- `app/modules/story/service_api.py` (validate/compile/store orchestration)
- `app/modules/story/author_assist.py` (assist API facade + error mapping)
- `app/modules/session/service.py` (session API facade + transaction boundaries)
- `app/modules/session/runtime_orchestrator.py` (runtime step orchestration)
- Responsibility: use-case coordination, no low-level deterministic rules.

3. Domain deterministic layer
- `app/modules/story/authoring/*` (`schema_v4.py`, `compiler_v4.py`, `diagnostics.py`)
- `app/modules/story/playability.py`
- `app/modules/narrative/*_engine.py`
- `app/modules/session/runtime_pack.py`
- `app/modules/session/story_runtime/phases/*`
- Responsibility: compile rules, validation, consequence/state progression, playability checks.

4. Infrastructure/adapters layer
- `app/modules/llm/providers/*`
- `app/modules/llm/runtime/*` (`transport.py`, `protocol.py`, `parsers.py`, `orchestrators.py`)
- `app/modules/session/runtime_deps.py` (runtime dependency builders + startup strict scan)
- Responsibility: external calls, protocol fallback, strict loading/scanning of persisted pack data.

## Hard-Cut Compatibility Policy
1. Author schema is ASF v4 only.
2. Runtime pack is StoryPack v10 strict only.
3. `StoryPack` metadata keeps `author_source_v4` only (`author_source_v3` removed).
4. Startup scan blocks service if stored packs include non-strict/legacy payloads (`LEGACY_STORYPACKS_BLOCK_STARTUP`).
5. Runtime load rejects non-strict pack payloads (`RUNTIME_PACK_V10_REQUIRED`).

## Story Module Ownership
1. `app/modules/story/schemas.py`
- API schemas and StoryPack schema definitions.
- Runtime pack model is strict v10-only.

2. `app/modules/story/service_api.py`
- Compile/validate/store orchestration.
- Converts deterministic diagnostics into author-facing errors/warnings.

3. `app/modules/story/author_assist.py`
- Assist entrypoint facade with task routing.
- Delegates task logic to `app/modules/story/author_assist_core/*`.

4. `app/modules/story/author_assist_core/`
- `service.py`: assist orchestration internals.
- `deterministic_tasks.py`: deterministic transforms.
- `seed_normalize.py`: `seed_expand` normalization rules.
- `patch_ops.py`, `postprocess.py`: patch sanitization, graph repair, ending sync.
- `errors.py`, `types.py`: internal contracts.

5. `app/modules/story/authoring/`
- Deterministic ASF v4 compiler and schema validation.
- Must never import LLM runtime/provider modules.

## Session Module Ownership
1. `app/modules/session/service.py`
- Thin façade: session lifecycle endpoints and error mapping.
- Delegates runtime load helpers to `runtime_deps.py`.
- Delegates step orchestration to `runtime_orchestrator.py`.

2. `app/modules/session/runtime_deps.py`
- Story pack strict load/normalize helpers.
- startup scan helper (`assert_stored_storypacks_v10_strict`).
- runtime dependency bundle builders.

3. `app/modules/session/runtime_orchestrator.py`
- Build runtime dependencies and invoke pipeline runner.

4. `app/modules/session/story_runtime/pipeline.py`
- Phase scheduler only.
- Detailed phase logic resides in `app/modules/session/story_runtime/phases/*`.

5. `app/modules/session/story_runtime/phases/`
- `context.py`, `selection.py`, `transition.py`, `progression.py`, `narration.py`, `response.py`, `observability.py`.

## LLM Boundary
1. Allowed LLM touchpoints:
- `app/modules/session/selection.py`
- `app/modules/session/service.py`
- `app/modules/session/story_runtime/pipeline.py`
- `app/modules/story/author_assist.py`

2. Forbidden LLM coupling:
- `app/modules/story/authoring/*`
- `app/modules/story/service_api.py`
- `app/modules/narrative/*`

3. Boundary enforcement:
- `tests/test_architecture_boundaries.py` must pass for any architecture PR.

## Demo Frontend Ownership
1. `app/modules/demo/static/index.author.html`
- Author shell and stable selector contract.

2. `app/modules/demo/static/author/`
- `app.js`, `assist.js`, `state.js`, `patch_engine.js`.
- `page_compose.js`, `page_shape.js`, `page_build.js`.

3. `app/modules/demo/static/author.js`
- Thin boot entrypoint.

## Architecture PR Checklist
1. Did this change introduce `app.modules.llm` imports into forbidden deterministic modules?
2. Did this change alter `/stories/*` or `/sessions/*` response contracts?
3. Did this change reintroduce legacy story compatibility paths?
4. Did this change move business logic from service/orchestrator into router?
5. Did you run the minimum regression set in `docs/verification.md`?
