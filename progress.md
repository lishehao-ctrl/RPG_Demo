Original prompt: PLEASE IMPLEMENT THIS PLAN: Author Story Studio v3 计划（7层创作结构 + Layer Intent Parse + Dev Layer Inspector）

- [x] Baseline scanned: current code is ASF v2 hard-cut with old assist tasks and no layer-inspector debug endpoint.
- [ ] Implement ASF v3 hard-cut backend.
- [ ] Upgrade author-assist tasks to v3.
- [ ] Rebuild /demo/author to 8-step v3 wizard + global parse/refine UX.
- [ ] Add runtime layer_debug and /sessions/{id}/debug/layer-inspector.
- [ ] Add dev UI layer inspector panel.
- [ ] Update tests and docs to v3-only.

## Update 1 - Backend v3 Hard-Cut
- Added ASF v3 schema and compiler entrypoint in `app/modules/story/authoring.py`.
- Kept v2 compiler as internal deterministic worker via v3 projection.
- Added `looks_like_author_pre_v3_payload` and `AUTHOR_V3_REQUIRED` messaging.
- Added optional `author_source_v3` passthrough in compiled StoryPack payload.
- Router updated to enforce v3-only on `/stories/validate-author` and `/stories/compile-author`.

## Update 2 - Author Assist v3
- Replaced assist tasks with v3 task set:
  - layer_bootstrap, layer_refine, scene_options, intent_aliases, consistency_check.
- Reworked deterministic assist output paths for layered v3 fields.
- Updated author-assist prompt builder for v3 layered constraints.

## Update 3 - Author UI v3 Wizard
- Rebuilt `/demo/author` to 8-step wizard with v3 wording and selectors.
- Added global brief parse entry (`author-global-brief`) and layer intent panel (`author-layer-intent-panel`).
- Rewrote `author.js` state/payload flow to `format_version: 3` and new assist tasks.
- Preserved compatibility selectors (`author-step-advanced`, existing validate/compile/playtest selectors).

## Update 4 - Runtime/Dev Layer Inspector
- Added `layer_debug` snapshot into `ActionLog.classification` in story runtime pipeline.
- Added dev-only endpoint: `GET /sessions/{id}/debug/layer-inspector`.
- Added schema models for layer inspector response.
- Added `/demo/dev` Layer Inspector panel and fetch/render logic.

## Update 5 - Tests & Docs
- Updated authoring/assist/UI/session tests for v3 and layer inspector.
- Updated docs and README to ASF v3 and new assist/debug contracts.
- Test results:
  - `python -m compileall app` ✅
  - `pytest -q` ✅ (159 passed)
  - `python -m pytest -q client/tests` ✅ (9 passed)

## Remaining Notes
- No open TODOs from this implementation batch.

## Update - SSE Stage Visibility (Author + Play)
- Added runtime stage signaling end-to-end for stream routes and UI binding.
- Added `/stories/author-assist/stream` and `/sessions/{id}/step/stream` SSE behavior coverage in tests.
- Play UI now consumes backend `stage.label` and reflects it in button + busy status text.
- Fixed `session/service.py` idempotent step block syntax/regression and ensured stream path is stable.
- Added compatibility fallbacks for runtime stubs missing new stage kwargs.
- Validation: `python -m compileall app` and full `pytest -q` passed (`223 passed`).

## Update - Author/Play waiting UX + Story Overview
- Implemented stage-driven UI animations for Author assist buttons/status and Play busy hint states.
- Added stage-state mappings driven by SSE `stage_code` events (requesting/building/retrying for Author; selection/narration/retry for Play).
- Replaced Compose-page Writer Turn Feed with Story Overview summary card (core goal/conflict/structure/branch/latest update).
- Moved Writer Turn Feed display into Debug panel while retaining existing turn template and diagnostics behavior.
- Added reduced-motion fallbacks for all newly introduced animations.
- Updated demo route/UI tests for new Story Overview markers.
- Validation:
  - `python -m compileall app` ✅
  - `pytest -q tests/test_demo_routes.py tests/test_demo_author_ui.py` ✅
  - `pytest -q tests/test_story_author_assist_api.py tests/test_session_api.py` ✅
  - `pytest -q tests/test_story_engine_integration.py` ✅
  - `pytest -q` ✅ (223 passed)
- Playwright visual smoke not executed: local `playwright` package missing for skill client (`ERR_MODULE_NOT_FOUND: playwright`).

## Update - Author/Dev Readable-First Layer Rendering
- Converted Author Shape main flow to narrative-readable controls for Characters/Action and narrative summaries for Consequence/Ending.
- Moved raw JSON layer editors to Debug fallback panel while preserving legacy element IDs for compatibility.
- Story Overview now renders natural-language paragraphs (from staged `overview_rows` when available, otherwise from story snapshot fallback).
- Dev Layer Inspector now renders narrative layer cards by default; raw payload stays available under collapsible details.
- Updated manual animation screenshot gate to assert natural-language Story Overview text instead of label/value row text.
- Synced route/UI markers for new narrative fields and raw-data debug panel.

Validation:
- `python -m compileall app` ✅
- `pytest -q tests/test_demo_routes.py tests/test_demo_author_ui.py` ✅
- `pytest -q tests/test_story_author_assist_api.py tests/test_session_api.py` ✅
- `pytest -q tests/test_story_engine_integration.py` ✅
- `.venv/bin/python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local --check-author-animation` ✅
- `pytest -q` ✅ (234 passed)

## Update - Shape Always-On + Compose Preflight + Mixed Overview Paragraph
- Author `Shape` editor is no longer collapsible:
  - Replaced `<details id="authorStructureCollapse">` with a regular section container.
  - Removed `structure_open` panel state from `author/state.js` and `author/app.js`.
- Added Compose preflight with hard parse gating:
  - New panel IDs: `authorPreflightPanel`, `authorPreflightScore`, `authorPreflightList`, `authorPreflightHint`.
  - Checks implemented in `author/app.js`:
    - `Entry Input` (Spark seed length / Ingest source length)
    - `Global Brief` minimum length
    - `Conflict Triplet` keyword coverage (deadline + risk + scarce resource, zh/en)
  - `Parse All Layers` is disabled when any check is red; other assist actions remain available.
- Story Overview upgraded to mixed strategy:
  - Backend deterministic cleanup in `app/modules/llm/runtime/author_overview.py` now normalizes dict/list-like values into readable text.
  - Added dirty-text detection (`is_overview_dirty`).
  - Added optional overview rewrite prompt/envelope/parser:
    - `build_author_overview_paragraph_prompt/envelope`
    - `parse_author_overview_paragraph`
  - `LLMRuntime.author_assist_two_stage_with_fallback` now:
    1) builds deterministic overview rows + paragraph
    2) conditionally performs one small rewrite call if dirty
    3) falls back silently to deterministic paragraph if rewrite fails
  - `author.build.start` stage now includes optional `overview_paragraph` (backward-compatible extension).
- Frontend stage consumption:
  - Added `overviewFromExpandParagraph` and render priority:
    - `overview_paragraph` > `overview_rows` narrative > local story fallback.
  - Keeps existing stage animation/cancel behavior unchanged.
- Screenshot script update:
  - `scripts/capture_demo_screenshots.py --check-author-animation` mock now emits `overview_paragraph`.
  - Build-stage assertion checks natural-language paragraph phrase instead of old label-row style text.

### Validation (this batch)
- `python -m compileall app` ✅
- `pytest -q tests/test_demo_routes.py tests/test_demo_author_ui.py` ✅
- `pytest -q tests/test_llm_prompts.py tests/test_prompt_contract_lint.py` ✅
- `pytest -q tests/test_llm_adapter_author_assist_structured.py` ✅
- `pytest -q tests/test_story_author_assist_api.py` ✅
- `pytest -q tests/test_session_api.py` ✅
- `pytest -q tests/test_story_engine_integration.py` ✅
- `pytest -q tests/test_architecture_boundaries.py` ✅
- `pytest -q` ✅ (238 passed, 1 warning)

### Notes / Follow-ups
- Optional manual visual check remains available:
  - `python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local --check-author-animation`
- Untracked local file still present: `.DS_Store`.

## Update - Author UI Simplification (Shape under Shape + Build Save/Publish)
- Simplified Author Build main flow to delivery-only UX in `/demo/author`:
  - Primary Build panel now uses `Save Story` + `Publish` (`publishStoryBtn`, `authorPublishInfo`).
  - Publish is version-pinned to the most recent successful save (`lastSavedStoryId` + `lastSavedVersion`).
  - Publish success/failure writes status to both `authorStatus` and `authorPublishInfo`; no auto-redirect.
- Implemented frontend publish state machine in `app/modules/demo/static/author/app.js`:
  - Added `publishInFlight` guard and button enablement sync.
  - Added API call to `POST /stories/{story_id}/publish?version=...`.
  - Added explicit handling for `STORY_NOT_FOUND` and `STORY_INVALID_FOR_PUBLISH`.
- Kept advanced build operations in Debug (validate/compile/playtest and diagnostics) while keeping existing IDs for compatibility.
- Ensured Shape editor is mounted under Shape page at runtime via `ensureShapeStructureMounted()`.
- Synced docs and route/UI marker tests with Save/Publish primary flow.

### Validation (this batch)
- `python -m compileall app` ✅
- `pytest -q tests/test_demo_routes.py tests/test_demo_author_ui.py` ✅ (`24 passed`)
- `pytest -q tests/test_story_pack_api.py` ✅ (`5 passed`)
- `pytest -q tests/test_session_api.py tests/test_story_engine_integration.py` ✅ (`62 passed`, `1 warning`)

## Update - Runtime Node Lookup Optimization + Playwright Hooks (In Progress)
- Current user request: optimize game backend architecture and validate gameplay loop via develop-web-game skill.
- Decision: implement a low-risk runtime optimization by adding node-id indexing for `runtime_pack.story_node()` to avoid repeated linear scans on large StoryPacks.
- Decision: expose `window.render_game_to_text` and `window.advanceTime` in `/demo/play` so the Playwright skill client can read deterministic text state and drive timing.
- Next: add targeted tests, run focused pytest, then run Playwright loop and inspect screenshots/state/error artifacts.

### Update - Runtime Node Index Optimization (Done)
- Implemented internal node-id index cache in `app/modules/session/runtime_pack.py`:
  - Added `_runtime_node_index` construction helper.
  - `story_node()` now resolves through cached index and lazily initializes it when absent.
  - `normalize_pack_for_runtime()` now pre-populates the node index once per normalized pack.
  - Preserved prior duplicate-id behavior: first node wins.
- Added targeted tests in `tests/test_runtime_pack.py` for duplicate-id semantics, lazy index build, and normalize-path index population.
- Validation:
  - `pytest -q tests/test_runtime_pack.py tests/test_session_api.py::test_create_and_get_session tests/test_story_engine_integration.py::test_story_session_advances_nodes_by_choice_id` ✅ (`5 passed`)
  - `python -m compileall app/modules/session/runtime_pack.py tests/test_runtime_pack.py` ✅

### Update - Play Demo Automation Hooks (Done)
- Added automation hooks in `app/modules/demo/static/play.js`:
  - `window.render_game_to_text()` now returns concise JSON for current run state.
  - `window.advanceTime(ms)` now advances controlled wait time for Playwright stepping.
- Extended internal play state with `currentNodeId` + `currentChoices` so text output mirrors interactive UI state.
- Hook registration is done in `init()` via `attachAutomationHooks()`.
- Validation:
  - `pytest -q tests/test_demo_routes.py tests/test_session_api.py::test_create_and_get_session` ✅ (`5 passed`)

## Update - Accept-All Runtime Extensions (Inventory + External Status + NPC Model)
- Implemented schema-level extensions for StoryPack:
  - Added optional `item_defs`, `npc_defs`, `status_defs`.
  - Extended `StoryChoice.effects` with operation lists: `inventory_ops`, `npc_ops`, `status_ops`, `world_flag_ops`.
- Added deterministic runtime state extensions in `state_json` normalization:
  - `inventory_state` (mixed model: stack + instance + equipment slots + currency)
  - `external_status` (player effects, world flags, faction rep, timers)
  - `npc_state` (relation, mood, beliefs, goals, status, short/long memory refs)
- Added `app/modules/narrative/state_patch_engine.py`:
  - Applies effect operations transactionally to normalized state.
  - Compacts NPC short memory to long-memory refs and enforces state-size pressure trimming.
  - Provides NPC prompt context summarization.
- Wired patch engine into story runtime transition phase and pipeline:
  - New `effect_ops_for_state` path from selection resolution into transition.
  - Selection/narration latency metrics captured in pipeline.
  - Layer debug now includes metrics: selection/narration latency, fallback reason, inventory/npc mutation counts, compacted memory count, state size, prompt NPC count, retry count.
- Added free-input `Input Policy Gate` (`phases/input_policy.py`):
  - Limits free-input length and blocks dangerous prompt-injection/system-leak patterns.
  - Blocked input routes to safe fallback without LLM call.
- Runtime pack normalization now projects operation payloads to deterministic `effect_ops` and carries optional defs for runtime context.
- Session creation now seeds `npc_state` from `npc_defs.relation_axes_init` / goals when absent.

### Added / Updated Tests
- Added `tests/test_state_patch_engine.py`.
- Extended `tests/test_story_pack_api.py` with defs/effect_ops validation coverage.
- Extended `tests/test_session_step_integration.py` with:
  - effect ops applied through step pipeline,
  - input policy blocked free-input fallback behavior.

### Validation
- `python -m compileall ...` on touched modules ✅
- Targeted tests ✅ (`6 passed`)
- Runtime/API regression set ✅ (`96 passed, 1 warning`)
- Prompt/architecture tests ✅ (`14 passed`)
- Full backend tests ✅ (`pytest -q` => `182 passed, 1 warning`)
- Client tests ✅ (`python -m pytest -q client/tests` => `9 passed`)

### Follow-up Suggestions
- Add deterministic replay summary fields for inventory/npc deltas to improve run explainability.
- Add dedicated playability sim metrics for inventory inflation and NPC relation slope drift.

## Update - Accept-All Contract Closure (Schema + Validation + Docs)
- Closed remaining contract gap by adding `StoryChoice.action_effects_v2` to schema and model validation.
- Strengthened structural validation for effect-op references across all executable scopes:
  - visible choice `effects`
  - visible choice `action_effects_v2`
  - node/default fallback `effects`
  - fallback executor `effects`
- Added extra effect-op safety checks:
  - status target mismatch guard (`status_defs.target` vs `status_ops.target`)
  - `add_instance` cannot target `kind=stack` items
  - equipment slot normalization/validation (`weapon|armor|accessory`)
- Improved session bootstrap merge semantics:
  - replaced shallow `initial_state` merge with deterministic deep-merge utility.
- Added/updated tests:
  - `tests/test_story_pack_api.py` (action_effects_v2 + fallback/executor dangling refs + status target mismatch)
  - `tests/test_session_step_integration.py` (LLM_UNAVAILABLE no-commit + action_effects_v2 runtime apply)
  - `tests/test_session_api.py` (deep-merge initial_state + npc seeding preservation)
  - `tests/test_input_policy.py` (input limit + injection blocking)
- Synced docs:
  - `docs/story-pack-spec.md`
  - `docs/architecture_story_runtime.md`
  - `docs/architecture-llm-boundary-zh.md`

Validation:
- `python -m compileall ...` (touched modules) ✅
- `pytest -q tests/test_story_pack_api.py tests/test_session_api.py tests/test_session_step_integration.py tests/test_state_patch_engine.py tests/test_input_policy.py` ✅ (`69 passed, 1 warning`)
- `pytest -q` ✅ (`191 passed, 1 warning`)
- `python -m pytest -q client/tests` ✅ (`9 passed`)
