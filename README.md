# RPG Backend V2 (Deterministic Story Runtime)

## Quick Start

### Recommended (Project `.venv`)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
./scripts/dev.sh
```

### Fast Path (Current Python / conda / base)

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Startup Script Behavior (`scripts/dev.sh`)

- Prefers `.venv/bin/python -m uvicorn` when `.venv` exists.
- Falls back to `python -m uvicorn` when `.venv` is missing.
- Prints active interpreter path and version before server start.
- Exits with actionable setup instructions when `uvicorn` is unavailable.

### Troubleshooting: `uvicorn: command not found`

Root cause is usually environment mismatch (not API/router configuration).

Checklist:

```bash
command -v python
python -m uvicorn --version
```

If missing:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
./scripts/dev.sh
```

Server:
- `http://127.0.0.1:8000`

Health:
- `GET /health`
- Player UI: `GET /play`
- Story debug UI: `GET /play-dev`

## Web UI

### `/play` (Immersive Player UI)
- Focused on player-visible context:
  - scene title + scene brief
  - latest narrative text
  - choice cards + free input
  - compact status (`energy`, `day/slot`, `step`, `fallbacks`)
  - ending summary when run ends
- Story-first entry flow:
  - open `GET /play`
  - page loads `GET /api/v1/stories/catalog/published`
  - user selects a published story from dropdown, then clicks `Start Story`
  - optional deep-link: `GET /play?story_id=<story_id>` preselects a story if it exists
- Lean branch design:
  - no manual refresh flow
  - no story version input flow
  - no activity feed
- Streaming UX:
  - step requests use `POST /api/v1/sessions/{session_id}/step/stream` when supported
  - narrative text is rendered incrementally (`narrative_delta`)
  - waiting state shows lightweight shimmer/caret/pulse animation
  - browser/runtime fallback: automatically uses legacy `POST /step`
- Technical fields are reduced to session metadata only in `Advanced details`.

### `/play-dev` (Story Debug UI)
- Runner + Inspector workflow:
  - start session + step (`choice` / `free_input`) using runtime API
  - load sessions list
  - single `Sync` action hydrates overview + timeline + telemetry + versions + latest step detail
  - inspector tabs (`Selection`, `State Diff`, `LLM Trace`, `Classification`, `Raw JSON`)
- Live stream panel:
  - shows stream phase in real time
  - accumulates streamed narration chunks and chunk/char counters
  - still auto-syncs bundle after each completed step
- `/play-dev` uses both tokens when needed:
  - `X-Player-Token` for runtime stepping
  - `X-Author-Token` for debug/story/telemetry reads

## API

### Story API
- `POST /api/v1/stories/validate`
- `POST /api/v1/stories/audit`
- `POST /api/v1/stories`
- `POST /api/v1/stories/{story_id}/publish`
- `GET /api/v1/stories/{story_id}/published`
- `GET /api/v1/stories/catalog/published`
  - public list of published stories for player selector
  - response: `stories[]` with `story_id`, `title`, `published_version`, `updated_at`
- `GET /api/v1/stories/{story_id}/versions`
- `GET /api/v1/stories/{story_id}/versions/{version}`
- `POST /api/v1/stories/{story_id}/drafts`
- `PUT /api/v1/stories/{story_id}/versions/{version}`

### Runtime API
- `POST /api/v1/sessions`
  - response includes `current_node`, `story_id`, `story_version`
- `GET /api/v1/sessions/{session_id}`
- `POST /api/v1/sessions/{session_id}/step`
  - Requires header: `X-Idempotency-Key: <unique-request-key>`
  - Missing header -> `400 MISSING_IDEMPOTENCY_KEY`
  - Concurrent CAS conflict -> `409 SESSION_STEP_CONFLICT`
  - response includes `session_status` and `current_node`
- `POST /api/v1/sessions/{session_id}/step/stream`
  - request body is identical to `/step` (`choice_id` or `player_input`)
  - requires `X-Idempotency-Key`
  - returns `text/event-stream`
  - event protocol:
    - `meta`: session + key metadata
    - `phase`: `selection_start|selection_done|narration_start|narration_done|finalizing`
    - `narrative_delta`: incremental narration text chunks
    - `replay`: idempotency replay hit
    - `final`: full `StepResponse` payload (same shape as `/step`)
    - `error`: stream error payload (`code`, `message`)
    - `done`: stream finished
  - ending step policy: ending generation remains non-stream bundle; stream still emits `phase` + `final`
  - early client disconnects mark the idempotency record as `failed` with `STREAM_ABORTED`; session state stays unchanged

### Telemetry API
- `GET /api/v1/telemetry/runtime`
  - `total_step_requests`
  - `avg_step_latency_ms` / `p95_step_latency_ms`
  - `fallback_rate`
  - `ending_distribution`
  - `llm_unavailable_ratio`

### Debug API
- `GET /api/v1/debug/sessions`
  - query: `story_id?`, `status?`, `limit`, `offset`
  - returns filtered session summaries for dev UI
- `GET /api/v1/debug/sessions/{session_id}/bundle`
  - query:
    - `timeline_limit` (default `50`, range `1..200`)
    - `timeline_offset` (default `0`)
    - `include` (optional, comma separated: `telemetry,versions,latest_step_detail`)
  - default behavior (`include` empty): full bundle with `overview + timeline + telemetry + versions + latest_step_detail`
- `GET /api/v1/debug/sessions/{session_id}/overview`
  - current node + session state snapshot
- `GET /api/v1/debug/sessions/{session_id}/timeline`
  - action log summaries ordered by `step_index`
- `GET /api/v1/debug/sessions/{session_id}/steps/{step_index}`
  - per-step detail:
    - `request_payload_json`
    - `selection_result_json`
    - `state_before` / `state_delta` / `state_after`
    - `llm_trace_json`
    - `classification_json`

## LLM Configuration (Minimal)
Only three env vars are used:

```env
LLM_BASE_URL=https://dashscope-us.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-flash-us
LLM_API_KEY=your_api_key_here
```

Runtime mode is automatic:
- `LLM_API_KEY` empty -> `fake_auto`
- `LLM_API_KEY` set -> `real_auto`

Additional optional runtime env vars:

```env
STORY_NARRATION_LANGUAGE=English
AUTHOR_API_TOKEN=
PLAYER_API_TOKEN=
```

- `STORY_NARRATION_LANGUAGE` controls narration/ending output language prompt.
- `AUTHOR_API_TOKEN` protects story + telemetry APIs when non-empty.
- `AUTHOR_API_TOKEN` also protects debug APIs (`/api/v1/debug/*`) when non-empty.
- `PLAYER_API_TOKEN` protects session APIs when non-empty.
- Headers:
  - `X-Author-Token: <token>` for author/telemetry/debug routes
  - `X-Player-Token: <token>` for runtime routes

## Time Strategy
- Database timestamps are stored as naive UTC for compatibility with current schema.
- Historical naive timestamps are interpreted as UTC.
- API datetime fields are serialized as explicit UTC (`RFC3339` with `Z`).
- Backend code must use unified helpers (`app/utils/time.py`) and should not call `datetime.utcnow()`.

## LLM Call Strategies (Fixed in Code)
- `selection`: non-stream + `response_format.json_schema` (`story_selection_mapping_v3`) + local grammarcheck
- `narration`: `stream=true`; server can forward chunk callbacks to SSE clients
- `ending`: non-stream + `story_ending_bundle_v1` schema

## StoryPack V2.0
The runtime only accepts `schema_version = "2.0"`.

Core additions:
- NPC dual-axis relation state: `affection`, `trust` (both clamp to `[-100, 100]`)
- NPC tier labels: `Hostile`, `Wary`, `Neutral`, `Warm`, `Close`
- Derived relation tier: `relation_tier = min(affection_tier, trust_tier)`
- Choice gate rules (`AND` semantics): `min_affection_tier` / `min_trust_tier`
- Range effects on both choices and fallbacks:
  - formula: `delta = center + intensity_tier * intensity`
  - `intensity_tier` in `{-2,-1,0,1,2}`
  - for fallback, runtime applies a base penalty first:
    - `effective_tier = clamp(base_penalty + llm_tier, -2, 2)`
    - Balanced penalties: `NO_MATCH:-1`, `LOW_CONF:-1`, `OFF_TOPIC:-1`, `INPUT_POLICY:-2`
- Transition endings on choices/fallbacks via `ending_id`
- NPC deterministic backreaction via `npc_reaction_policies` (`tier + source -> effects`)

## Runtime Behavior
- Locked choices are returned in `choices` with:
  - `available=false`
  - `locked_reason={code,message}`
- `POST /step` enforces `X-Idempotency-Key` on every request:
  - prevents accidental double-submit on network retries
  - keeps replay behavior deterministic for the same request key
- Explicit locked choice submit returns `422 CHOICE_LOCKED`
- Explicit invalid choice returns `422 INVALID_CHOICE`
- Free-input path always requires LLM mapping (`target + intensity coefficient`)
- Free-input selection has structured retry up to 3 attempts:
  - retries on LLM/network/schema errors and invalid target ids
  - retry context includes `last_error_code` and `allowed_target_ids`
  - still failing after 3 attempts returns `503 LLM_UNAVAILABLE`
- Free-input selection is fallback-first with confidence gates:
  - `confidence >= high`: execute mapped choice
  - `low <= confidence < high`: downgrade to `LOW_CONF` fallback
  - `< low`: downgrade to `NO_MATCH` fallback
- `INPUT_POLICY` flagged input is runtime-overridden to fallback even if LLM suggests choice
- Free-input LLM/grammar failure is strict fail-fast:
  - `503 LLM_UNAVAILABLE`
  - state and node are not committed
- Action logs include v3 selection diagnostics for replay/debug:
  - `mapping_schema`, `selection_decision_code`, `fallback_reason_code`
  - `raw_intensity_tier`, `effective_intensity_tier`, `fallback_base_penalty`
  - `decision_overridden_by_runtime`, `runtime_override_reason`
- `StepResponse` includes `ending_camp` when a run ends
- Session commit uses optimistic CAS (`sessions.version`) to protect same-session concurrent writes:
  - on conflict -> `409 SESSION_STEP_CONFLICT`
  - DB unique guard `(action_logs.session_id, action_logs.step_index)` is a final duplicate-step safety net

## Fallback/Ending Defaults
- Built-in fallback reasons: `NO_MATCH`, `LOW_CONF`, `INPUT_POLICY`, `OFF_TOPIC`
- Built-in endings: `ending_forced_fail`, `ending_neutral_default`, `ending_success_default`
- Story-defined endings support `camp: player|enemy|world`
- Story overrides defaults by id (story-first, defaults as fallback)
- Forced ending threshold default: `3` consecutive fallbacks
- Fallback narration nudge tier: `soft | neutral | firm`
- Ending returns structured life report (`ending_report`) and persists it in:
  - `state_json.run_state.ending_report`

## Story Audit Gate (Author-Ready)
- `POST /api/v1/stories/audit` returns structured `errors` and `warnings`
- Audit checks include:
  - unreachable nodes from `start_node_id`
  - trap loops (`TRAP_LOOP`) and loops with exits (`LOOP_WITH_EXIT`)
  - choice/fallback completeness and ending link validity
- Publish route enforces audit:
  - has error -> `422 INVALID_STORY_AUDIT`
  - warnings only -> publish succeeds and warnings are returned

## Example StoryPack
- `examples/storypacks/campus_week_v1.json`

## Demo StoryPack: `city_signal_v1`
- File: `examples/storypacks/city_signal_v1.json`
- Story id: `city_signal_v1`
- Theme: urban suspense with gates, fallback coverage, NPC reaction, and multi-ending routes.

### Import Flow (validate -> audit -> create draft -> publish)

Assume server is running at `http://127.0.0.1:8000`.
If `AUTHOR_API_TOKEN` is enabled, add header `X-Author-Token: <token>` to each request.

```bash
API_BASE="http://127.0.0.1:8000"
PACK_FILE="examples/storypacks/city_signal_v1.json"

# 1) Validate
jq -n --argfile pack "$PACK_FILE" '{pack:$pack}' \
| curl -sS -X POST "$API_BASE/api/v1/stories/validate" \
  -H "Content-Type: application/json" \
  -d @-

# 2) Audit
jq -n --argfile pack "$PACK_FILE" '{pack:$pack}' \
| curl -sS -X POST "$API_BASE/api/v1/stories/audit" \
  -H "Content-Type: application/json" \
  -d @-

# 3) Create draft (or update latest draft)
CREATE_RESP=$(
  jq -n --argfile pack "$PACK_FILE" \
    --arg story_id "city_signal_v1" \
    --arg title "City Signal" \
    '{story_id:$story_id,title:$title,pack:$pack}' \
  | curl -sS -X POST "$API_BASE/api/v1/stories" \
    -H "Content-Type: application/json" \
    -d @-
)
echo "$CREATE_RESP" | jq .
VERSION=$(echo "$CREATE_RESP" | jq -r '.version')

# 4) Publish that version
jq -n --argjson version "$VERSION" '{version:$version}' \
| curl -sS -X POST "$API_BASE/api/v1/stories/city_signal_v1/publish" \
  -H "Content-Type: application/json" \
  -d @-
```

### Play / Debug Smoke Path

1. Player UI:
   - Open `http://127.0.0.1:8000/play`
   - Select `city_signal_v1` in dropdown and click `Start Story`
2. Debug UI:
   - Open `http://127.0.0.1:8000/play-dev`
   - Set story id to `city_signal_v1`, then run start/step and inspect timeline + step detail.
