# Runtime Architecture V2

## Core Principles
- Deterministic-first: state transitions are rule/data driven
- `sessions.state_json` is the runtime source of truth
- LLM only maps free-input and generates narration text
- LLM failure is fail-fast: step rollback, no state commit

## Time Governance
- Current DB schema stores timestamps as naive UTC for compatibility.
- Historical naive timestamps are interpreted as UTC.
- API datetime outputs are explicit UTC (`RFC3339` with `Z`).
- Runtime and story services use a unified time helper (`app/utils/time.py`).
- Direct `datetime.utcnow()` usage is forbidden by tests.

## Story Model Highlights
- Hard-cut schema: `schema_version = "2.0"`
- Node-first graph execution
- NPC dual-axis runtime state:
  - `npc_state[npc_id].affection`
  - `npc_state[npc_id].trust`
  - derived tiers (`Hostile/Wary/Neutral/Warm/Close`)
  - derived `relation_tier = min(affection_tier, trust_tier)`
- Gate rules are conjunction (`AND`) across all gate items
- Transition-level ending links are supported on both choices and fallbacks (`ending_id`)
- NPC backreaction is deterministic via `npc_reaction_policies` (tier + source match)

## Step Pipeline
1. Normalize input.
2. Evaluate current node choices with gate status.
3. Resolve execution target:
   - explicit choice: validate id + availability
   - free-input: LLM structured mapping (`target_type`, `target_id`, `intensity_tier`)
   - free-input selection retries up to 3 attempts when mapping call/schema fails or target is not allowed
4. Apply deterministic range effects:
   - `delta = center + intensity_tier * intensity`
5. Apply optional NPC backreaction effects (`intensity_tier=0`) and merge delta.
6. Update run-state counters and fallback metadata.
7. Resolve ending priority:
   - transition `ending_id` > forced fallback guard
8. Generate narration:
   - normal/fallback: stream text
   - ending: structured ending bundle (`narrative_text + ending_report`)
9. Commit transaction (`sessions`, `action_logs`, idempotency):
   - `POST /step` requires `X-Idempotency-Key`
   - session commit uses optimistic CAS (`WHERE sessions.version = expected_version`)
   - success bumps `sessions.version` by 1
   - CAS miss returns `409 SESSION_STEP_CONFLICT`
   - DB unique guard `(action_logs.session_id, action_logs.step_index)` is final duplicate-step protection

## Choice Availability Contract
`GET /sessions/{id}` and `POST /step` both return choices including locked entries:
- `available: bool`
- `locked_reason: {code, message} | null`

Locked submit behavior:
- explicit invalid id -> `422 INVALID_CHOICE`
- explicit locked id -> `422 CHOICE_LOCKED`

## Fallback / Ending Guard
- Fallbacks and choices both require `range_effects`
- `consecutive_fallback_count` increments on fallback, resets on normal choice
- Default forced ending threshold is 3
- Fallback nudge tier policy:
  - `firm`: `INPUT_POLICY` or consecutive fallback >= 3
  - `neutral`: `LOW_CONF` or consecutive fallback == 2
  - `soft`: others

## Observability
`action_logs` captures:
- selection result (`intensity_tier`, gate failure snapshot)
- classification metadata (`range_formula`, input policy flag, schema id)
- channel call modes (`selection/non_stream_schema`, `narration/stream_text`, `ending/non_stream_schema`)
- selection retry telemetry (`selection_retry_count`, `selection_retry_errors`, `selection_final_attempt`)
- reaction telemetry (`reaction_npc_ids`, `reaction_hint_applied`)
- concurrency telemetry:
  - `session_version_expected`
  - `session_version_committed`
  - `cas_conflict`
  - `conflict_stage` (`session_update` or `action_log_unique`)

## Story Audit And Publish Gate
- `/api/v1/stories/audit` returns machine-readable issues:
  - `UNREACHABLE_NODE`
  - `TRAP_LOOP`
  - `LOOP_WITH_EXIT`
  - choice/fallback completeness and ending link issues
- `/api/v1/stories/{story_id}/publish` runs audit before publish:
  - errors block publish with `422 INVALID_STORY_AUDIT`
  - warnings are returned while publish continues
