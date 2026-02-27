Original prompt: 我希望可以美化一遍前端ui 你想想怎么做好 想想对于user play来说 哪些信息是重要的 布局应该是啥样子 哪些信息可以省略 如果是想要针story debug可以再出个有复杂详情页的dev ui

## 2026-02-26
- Start implementing dual-track UI plan: immersive /play + /play-dev with new debug APIs.
- Phase order: M1 debug backend, M2 play UI, M3 play-dev UI, M4 tests/docs.
- Added `tests/test_debug_api.py`:
  - list filter coverage for `/api/v1/debug/sessions`
  - step order coverage for `/api/v1/debug/sessions/{session_id}/timeline`
  - payload shape coverage for `/api/v1/debug/sessions/{session_id}/steps/{step_index}`
  - author token guard coverage for debug routes
- Updated `tests/test_play_telemetry_language.py`:
  - adapted `/play` availability assertions to new immersive UI copy
  - added `/play-dev` availability test
- Updated `README.md`:
  - documented `/play` vs `/play-dev` usage
  - added `/api/v1/debug/*` endpoint overview and key payload fields
- Fixed JS runtime syntax errors in `app/modules/play_ui/router.py`:
  - switched several `innerHTML` fallback snippets to single-quoted JS strings
  - removed browser `Unexpected identifier` errors on both `/play` and `/play-dev`
- Ran Playwright smoke via `develop-web-game` client:
  - `/play` screenshot: `output/web-game/play/shot-0.png`
  - `/play-dev` screenshot: `output/web-game/play-dev/shot-0.png`
  - no `errors-*.json` generated after fix
- Regression status: `pytest -q` => `83 passed`

### TODO / Suggestions
- Add Playwright flow that seeds `campus_week_v1`, clicks `Start Session`, and verifies one `choice` step + one `free_input` step on `/play`.
- Add Playwright flow for `/play-dev` to load timeline and open one inspector tab after creating a session.
- Consider extracting large inline HTML/JS from `app/modules/play_ui/router.py` into template/static files for maintainability.

## 2026-02-26 (Performance-first foundation pass)
- Implemented runtime response enhancements for one-request rendering:
  - `SessionCreateResponse` now includes `story_id`, `story_version`, `current_node`
  - `StepResponse` now includes `session_status`, `current_node`
- Updated runtime step action log payload to persist:
  - `selection_result_json.run_ended`
  - `selection_result_json.ending_id`
  - `selection_result_json.ending_outcome`
  - `selection_result_json.step_index`
- Implemented debug backend bundle API:
  - `GET /api/v1/debug/sessions/{session_id}/bundle`
  - default full bundle (overview + timeline + telemetry + versions + latest_step_detail)
  - include flags parsing (`telemetry,versions,latest_step_detail`)
- Optimized `GET /api/v1/debug/sessions` to remove N+1 latest-action queries:
  - replaced per-session lookups with one aggregated latest-action query
- Refactored `/play` into lean core flow:
  - query-driven story (`?story_id=`; default `campus_week_v1`)
  - removed refresh/version/activity branches
  - advanced section reduced to metadata only
- Refactored `/play-dev` to Runner+Inspector with single Sync branch:
  - removed separate panel refresh buttons (`Overview`, `Timeline`, `Telemetry`, `Versions`)
  - added `Sync` as unified bundle refresh action
- Added/updated tests:
  - debug query-count bound (`<=3` SELECTs for list endpoint)
  - debug bundle default/include subset/auth behavior
  - timeline + selection_result ending fields
  - runtime create/step response contract expansions
  - play/play-dev page branch assertions
- Verification:
  - `pytest -q` => `90 passed`
  - Playwright smoke screenshots:
    - `output/web-game/play/shot-0.png`
    - `output/web-game/play-dev/shot-0.png`

## 2026-02-26 (SSE stream UX pass)
- Added runtime stream endpoint:
  - `POST /api/v1/sessions/{session_id}/step/stream`
  - SSE events: `meta`, `phase`, `narrative_delta`, `replay`, `final`, `error`, `done`
- Extended runtime orchestration hooks:
  - phase callbacks and narrative delta callbacks in `run_step` path
  - added `run_step_with_replay_flag(...)` for stream replay signaling
- Extended llm boundary stream behavior:
  - `call_chat_completions_stream_text(..., on_delta=...)`
  - `LLMBoundary.narrative_stream(...)` + backward-compatible `narrative(...)`
- Updated `/play` UI:
  - step calls stream endpoint first, auto-fallback to legacy `/step`
  - live phase status + incremental narrative rendering
  - lightweight loading animation (shimmer/caret/pulse, reduced-motion aware)
- Updated `/play-dev` UI:
  - step controls use stream endpoint
  - new Live Stream panel (status/chunk count/char count/stream text)
  - keeps existing post-step bundle sync and inspector flow
- Added tests:
  - stream idempotency header guard
  - stream meta/phase/final/done event path
  - stream free-input emits narrative deltas
  - stream replay event path
  - stream LLM unavailable error path
  - ending step non-delta stream behavior
  - legacy `/step` compatibility assertion
  - `/play` and `/play-dev` HTML nodes for stream UI markers
- Updated README:
  - documented stream runtime API and event protocol
  - documented `/play` and `/play-dev` stream UX behavior
- Verification:
  - targeted: `pytest -q tests/test_api_runtime_flow.py tests/test_play_telemetry_language.py` -> pass
  - full: `pytest -q` -> `107 passed`

## 2026-02-26 (SSE robustness + short-transaction split)
- Refactored runtime step execution into staged flow while keeping API compatibility:
  - prepare in short DB transaction (selection/fallback/state transition planning)
  - narration generation outside write transaction
  - commit in short DB transaction with existing CAS semantics
- Added stream abort semantics:
  - new `StreamAbortedError`
  - `run_step_with_replay_flag` now accepts `abort_check` and marks idempotency failed with `STREAM_ABORTED`
  - stream router wires disconnect signal via `threading.Event` and passes it down
  - stream error mapping now includes `STREAM_ABORTED`
- Updated docs:
  - README stream API section now states early disconnect behavior (`STREAM_ABORTED`, no session advance)
- Added/updated tests:
  - replaced flaky HTTP disconnect test with deterministic service-level abort test
  - verifies idempotency row becomes `failed` with `STREAM_ABORTED` and session/action_log stay unchanged
- Fixed inline JS regressions in `app/modules/play_ui/router.py` discovered by Playwright:
  - corrected escaped newline handling in SSE parser strings (`\\n`, `\\n\\n`)
  - restored missing `/play-dev` live stream helper functions
  - removed duplicated `/play` stream helper definitions
- Verification:
  - `pytest -q` => `108 passed`
  - Playwright smoke run via `develop-web-game` client on `/play` and `/play-dev`
  - latest screenshots reviewed:
    - `output/web-game/play/shot-0.png`
    - `output/web-game/play-dev/shot-0.png`
  - no `errors-*.json` after final rerun

### TODO / Suggestions
- If you want true live-play smoke (not just UI skeleton) from Playwright, seed a published story before clicking `Start New Run` so browser logs stay clean while exercising stream step end-to-end.

## 2026-02-27 (Narration rendering corruption fix)
- Scope: `/play` + `/play-dev` streaming text rendering stabilization (no API change).
- Updated SSE parsing in both pages:
  - removed `trim()` from `data:` extraction
  - parse now strips only one optional space after `event:`/`data:`
  - normalized chunk line endings (`\\r\\n`/`\\r` -> `\\n`)
  - added trailing-buffer consumption to avoid dropping final partial event block
- Added frontend render queue (both pages):
  - narrative/live text deltas now enqueue then flush on `requestAnimationFrame`
  - one DOM text write per frame (reduced jitter/reflow)
  - explicit `flush...Now()` before stream finish/finalization
  - final response `narrative_text` now used as authoritative end-state fallback
- Added text layout stability improvements:
  - `overflow-wrap: anywhere`
  - `word-break: break-word`
  - `unicode-bidi: plaintext`
  - extended font stacks with CJK fallbacks for mixed-language output
- Test updates:
  - `tests/test_play_telemetry_language.py` now asserts no `dataLines.push(line.slice(5).trim())` in rendered page source
  - asserts new parser hooks remain present for both pages
- Verification:
  - targeted: `pytest -q tests/test_play_telemetry_language.py tests/test_api_runtime_flow.py` => `23 passed`
  - full: `pytest -q` => `112 passed`
  - Playwright smoke using `develop-web-game` script on isolated local server (`:18000`) with published `city_signal_v1`
  - screenshots reviewed:
    - `output/web-game/play-stream-fix/shot-1.png`
    - `output/web-game/play-dev-stream-fix/shot-1.png`
  - no `errors-*.json` generated

### TODO / Suggestions
- `/play` and `/play-dev` currently duplicate SSE parser/render-queue logic inside inline JS; extract shared helpers when you split templates/static assets to reduce drift risk.
