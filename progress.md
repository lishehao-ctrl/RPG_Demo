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
