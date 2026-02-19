# Story Runtime Architecture (v10 Hard Cut)

## Scope
This document describes the active story-mode runtime in:
- `app/modules/session/service.py`
- `app/modules/session/story_runtime/pipeline.py`
- `app/modules/session/story_runtime/decisions.py`
- `app/modules/session/story_runtime/models.py`

## Contract Locks
- Endpoint paths are unchanged.
- `StepResponse` schema is unchanged.
- Story step returns `200` for all non-inactive requests.
- Only inactive sessions return `409` with `SESSION_NOT_ACTIVE`.
- Sessions are story-only (`POST /sessions` requires `story_id`).
- Step input contract is strict:
  - allowed fields: `choice_id`, `player_input`
  - dual-input conflict (`choice_id` + `player_input`) is `422 INPUT_CONFLICT`
  - unknown fields are rejected with `422`
- `GET /stories/{id}` returns `{story_id, version, is_published, pack}` with raw DB `pack_json` in `pack`.
- Resolver ownership remains in `app/modules/session/service.py`.

## Runtime Model
Internal runtime candidates use one model:
- `CandidateChoice.kind`: `VISIBLE | INVISIBLE_INTENT | FALLBACK_EXECUTOR`

Execution semantics:
- `VISIBLE` is executable node choice.
- `INVISIBLE_INTENT` is mapping-only; it aliases to visible choice execution.
- `FALLBACK_EXECUTOR` is executable fallback target.

## Typed Prereq Evaluation
`app/modules/session/story_choice_gating.py` provides:
- `eval_prereq(ctx, prereq_spec) -> {allowed, kind, details}`
- `kind in {OK, BLOCKED, INVALID_SPEC}`

The runtime uses this typed result for pass routing and degraded execution decisions.

## Step Pipeline
`run_story_runtime_pipeline(...)` is phase-based:

1. Pass0 hard no-input:
- no `choice_id` and empty `player_input` route directly to fallback target.

2. Pass1 selection:
- button `choice_id` is deterministic selection,
- free input uses selector + deterministic mapping,
- invisible intents are mapping-only aliases that resolve to visible choice ids,
- unusable mapping becomes direct fallback.

3. Pass2 prereq + fallback routing:
- evaluate selected target prereq,
- if initial visible target fails, reroute once to fallback target,
- if rerouted target fails, degrade (`no action`, `effects=0`, `stay`) and do not reroute again.

4. QuestUpdate phase:
- runs after Pass2 state transition and before Pass3 narration,
- evaluates rule-based quest triggers using step event (`from node`, `to node`, `executed choice`, `action_id`, `fallback_used`, `state_after`, `state_delta`),
- updates `state_json.quest_state` (`active_quests`, stage pointers, stage milestone flags, completion flags, `recent_events`, `event_seq`),
- applies milestone/stage/completion rewards once,
- evaluates only the current active stage for each active quest (linear single-active stage flow),
- appends `type=quest_progress` entries into `ActionLog.matched_rules`.

5. Pass3 narration:
- generate narration and optionally polish fallback text.
- LLM runtime is generate-only for both selection and narration paths.
- token usage is logged for statistics (`tokens_in`, `tokens_out`, provider), but no budget enforcement is applied.
- narration prompt payload includes a compact quest summary (`active_quests` titles + recent quest events).

## Quest Stage v1
Quest runtime uses stage-based progression:
- one active stage per active quest (`current_stage_id`, `current_stage_index`),
- all milestones in the active stage must complete before stage completion,
- stage completion emits `stage_completed`, applies `stage_rewards`, then activates the next stage (emits `stage_activated`) if one exists,
- final stage completion emits `quest_completed` and applies `completion_rewards`,
- `recent_events` keeps only the latest 20 entries.

## using_fallback and reroute_used
`using_fallback` is true when final executed target differs from initially selected visible choice, or no visible selection happened.

`reroute_used` is true only when runtime transitions from an initially selected visible target to fallback target due to prereq failure.

## Outward Fallback Reason Policy
- `fallback_reason = null` for non-fallback path.
- fallback path returns neutral outward values:
  - `NO_INPUT`
  - `BLOCKED`
  - `FALLBACK`

Detailed internals remain in action logs (`fallback_reasons`, `matched_rules`).

## Replay Contract
- Replay payload keeps `missed_routes` and `what_if` keys for stable response shape.
- In the current story-only runtime, branch-trace derivation is removed, so both are returned as empty lists.

## Fallback Narration and Leak Safety
Fallback text source order:
1. fallback executor skeleton (if present),
2. pack fallback `text_variants` by neutral reason bucket,
3. service built-in deterministic fallback sentence.

Player-visible narrative is guarded against internal marker leakage and internal field names (for example `__fallback__`, `next_node_id`, `choice_id`, `intent_id`, `confidence`, `delta_scale`).

System-generated polish additionally blocks error-style phrases (`invalid choice`, `parse error`, `unknown choice`, `unknown action`, `unknown input`).
