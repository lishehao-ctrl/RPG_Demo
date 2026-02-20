# Frontend Handoff Guide

## Positioning
This repository keeps gameplay logic in backend runtime.  
Frontend clients (internal demo or outsourced app) should be thin:
- collect input (`choice_id` or `player_input`),
- render response payloads,
- never re-implement mapping/gating/fallback/event/ending rules.

## Stable Endpoints
- `GET /stories`
- `POST /sessions`
- `GET /sessions/{id}`
- `POST /sessions/{id}/step`
- `POST /sessions/{id}/snapshot`
- `POST /sessions/{id}/rollback`
- `POST /sessions/{id}/end`
- `GET /sessions/{id}/replay`

## Internal Demo Variants
- `GET /demo/play`: user-facing lightweight play view.
- `GET /demo/dev`: developer debugging view with full diagnostics.
- `GET /demo/bootstrap`: shared frontend bootstrap config.

`/demo/play` flow:
1. fetch `GET /stories` (published + playable),
2. let player choose a story,
3. create session via `POST /sessions`,
4. enter gameplay loop.

## User UI Presentation Rules (`/demo/play`)
Use these rules for player-facing UI. Keep debug-heavy details in `/demo/dev`.

1. Header:
- show story title + short subtitle,
- show current time pill from `day + slot` (for example `Day 2 • Afternoon`),
- hide `phase`, `session_id`, token totals.

2. Core stats:
- energy: card + progress bar (`0-100`) with thresholds:
  - `<=25`: danger
  - `26-60`: warning
  - `>60`: healthy
- money: formatted number + tier label:
  - `<20`: tight
  - `20-100`: stable
  - `>100`: comfortable
- knowledge: number + progress bar relative to `999`, tier label:
  - `0-9`: novice
  - `10-29`: developing
  - `30+`: advanced
- affection: value + bidirectional bar (`-100..100`) + tone label.

3. Choice rendering:
- primary text: `choice.text` only,
- type badge mapping:
  - `study -> Study`
  - `work -> Work`
  - `rest -> Rest`
  - `date -> Social`
  - `gift -> Gift`
  - default -> `Action`
- locked choices: keep visible, set disabled.
- locked reason mapping:
  - `BLOCKED_MIN_MONEY -> Need more money`
  - `BLOCKED_MIN_ENERGY -> Need more energy`
  - `BLOCKED_MIN_AFFECTION -> Relationship not high enough`
  - `BLOCKED_DAY_AT_LEAST -> Available on later days`
  - `BLOCKED_SLOT_IN -> Not available at this time of day`
  - `FALLBACK_CONFIG_INVALID -> Temporarily unavailable`
  - fallback/default -> `Unavailable for now`

4. Quest summary:
- show only:
  - active quests (current stage + done/total)
  - completed quests
  - recent 2-3 events
- do not render raw quest JSON object keys.

5. Run snapshot:
- show:
  - step index
  - fallback count
  - ending state (`In progress` when empty)
  - triggered event count
- hide raw arrays/maps (`event_cooldowns`, `triggered_event_ids` raw content).

6. Replay:
- use collapsed drawer by default (`View Run Summary`),
- render only short summary blocks:
  - story path
  - key decisions
  - run summary
- do not render raw JSON.

7. Error copy (player-facing):
- hide backend codes/stack style output,
- map `LLM_UNAVAILABLE` to:
  - `Narration is temporarily unavailable. This step was not applied.`
- for retryable uncertain state, show actionable retry hint.

## Input Contract (`POST /sessions/{id}/step`)
- allowed fields only:
  - `choice_id: string | null`
  - `player_input: string | null`
- both provided -> `422 INPUT_CONFLICT`
- both omitted -> valid request, runtime handles as `NO_INPUT` fallback
- free-input conservative rescue:
  - when LLM selector says fallback, backend still runs deterministic intent/rule matching.
  - mapping only applies when confidence is `>= story_map_min_confidence` (default `0.60`).
  - ambiguous/low-confidence text still falls back to guided mainline behavior.
- required client behavior in production:
  - generate and send `X-Idempotency-Key` for every step action
  - keep the same key when retrying the same action after timeout/network failures
  - never reuse a key for a different payload
- narrative chain exhaustion returns `503 LLM_UNAVAILABLE`; this step is not applied.

## Response Contract (`StepResponse`)
Core fields:
- `story_node_id`
- `attempted_choice_id`
- `executed_choice_id`
- `resolved_choice_id`
- `fallback_used`
- `fallback_reason`
- `mapping_confidence`
- `narrative_text`
- `choices`
- `cost.tokens_in`
- `cost.tokens_out`
- `cost.provider`

Run-ending additive fields:
- `run_ended: bool`
- `ending_id: string | null`
- `ending_outcome: "success" | "neutral" | "fail" | null`

## State Rendering Contract (`GET /sessions/{id}`)
Frontend should read from:
- `current_node_id` as story node string id (not UUID contract),
- `current_node.id` as the same story node string id,
- `state_json` core stats (`energy`, `money`, `knowledge`, `affection`, `day`, `slot`)
- `state_json.quest_state` (active/completed quests, stage progress, recent quest events)
- `state_json.run_state`:
  - `step_index`
  - `triggered_event_ids`
  - `event_cooldowns`
  - `ending_id`
  - `ending_outcome`
  - `ended_at_step`
  - `fallback_count`

## Replay Contract (`GET /sessions/{id}/replay`)
Stable keys:
- `session_id`
- `total_steps`
- `key_decisions`
- `fallback_summary`
- `story_path`
- `state_timeline`
- `run_summary`

`run_summary` keys:
- `ending_id`
- `ending_outcome`
- `total_steps`
- `triggered_events_count`
- `fallback_rate`

## Integration Rules For Outsourced Frontend
1. Treat backend as single source of truth for game progression.
2. Do not infer availability from local rules; render `choices[].is_available` and `unavailable_reason`.
3. Locked choices should stay visible but disabled in UI.
4. After successful step, render step payload first; refresh session state without overwriting returned narrative/choices.
5. If `run_ended=true`, lock input UI and show ending metadata.
6. Keep request payload strict to avoid `422` from unknown fields.
7. Use replay endpoint for post-run summary screens.
8. Keep one idempotency key per user action and reuse the same key for every retry of that action.
9. Retry strategy for step:
   - on transport errors: retry with backoff and the same key
   - on `409 REQUEST_IN_PROGRESS`: retry with backoff and the same key
   - on `409 IDEMPOTENCY_KEY_REUSED`: treat as client bug and stop retry
   - on `503 LLM_UNAVAILABLE`: stop retry and tell user the step was not applied
10. If retries are exhausted with uncertain status, keep pending action state and continue retrying with the same key.
11. Treat fallback responses (`fallback_used=true`) as normal game progress, not fatal errors.
