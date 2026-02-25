# Story Runtime Architecture (v10 Hard Cut)

## Scope
This document describes the active story-mode runtime in:
- `app/modules/session/service.py`
- `app/modules/session/story_runtime/pipeline.py`
- `app/modules/session/story_runtime/decisions.py`
- `app/modules/session/story_runtime/models.py`

## Contract Locks
- Endpoint paths are unchanged.
- `StepResponse` is story-pointer first:
  - includes `story_node_id`
  - excludes legacy synthetic `node_id`
  - includes optional run-ending fields `run_ended`, `ending_id`, `ending_outcome`
- Story step returns `200` for all non-inactive requests.
- Only inactive sessions return `409` with `SESSION_NOT_ACTIVE`.
- Session APIs run in single-tenant anonymous mode (no auth dependency).
- Sessions are story-only (`POST /sessions` requires `story_id`).
- Step input contract is strict:
  - allowed fields: `choice_id`, `player_input`
  - dual-input conflict (`choice_id` + `player_input`) is `422 INPUT_CONFLICT`
  - unknown fields are rejected with `422`
- `GET /stories/{id}` returns `{story_id, version, is_published, pack}` with raw DB `pack_json` in `pack`.
- `GET /stories` provides story picker data (`published_only/playable_only` filters).
- Resolver ownership remains in `app/modules/session/service.py`.
- Session runtime pointer truth is `sessions.story_node_id` (string StoryPack node id).

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

1. Input Policy Gate:
- for free-input requests, normalize whitespace and apply max-length cap,
- block injection-like patterns and route directly to safe fallback selection.

2. Pass0 hard no-input:
- no `choice_id` and empty `player_input` route directly to fallback target.

3. Pass1 selection:
- button `choice_id` is deterministic selection,
- free input uses selector + deterministic mapping,
- invisible intents are mapping-only aliases that resolve to visible choice ids,
- unusable mapping becomes direct fallback.

4. Pass2 prereq + fallback routing:
- evaluate selected target prereq,
- if initial visible target fails, reroute once to fallback target,
- if rerouted target fails, degrade (`no action`, `effects=0`, `stay`) and do not reroute again.

5. Deterministic transition:
- apply base action transition,
- apply scalar stat effects,
- apply deterministic effect-op patch stream:
  - `inventory_ops`
  - `npc_ops`
  - `status_ops`
  - `world_flag_ops`
- run NPC memory compaction under configured soft/hard size pressure thresholds.

6. QuestUpdate phase:
- runs after Pass2 state transition and before Pass3 narration,
- evaluates rule-based quest triggers using step event (`from node`, `to node`, `executed choice`, `action_id`, `fallback_used`, `state_after`, `state_delta`),
- updates `state_json.quest_state` (`active_quests`, stage pointers, stage milestone flags, completion flags, `recent_events`, `event_seq`),
- applies milestone/stage/completion rewards once,
- evaluates only the current active stage for each active quest (linear single-active stage flow),
- appends `type=quest_progress` entries into `ActionLog.matched_rules`.

7. EventPhase:
- runs after QuestUpdate and before ending resolution,
- builds deterministic event seed from `session_id`, `step_id`, and `story_node_id`,
- picks one eligible event by weighted draw,
- enforces `once_per_run` + `cooldown_steps`,
- applies event effects into state through existing normalize/clamp path,
- appends `type=runtime_event` entries into `ActionLog.matched_rules`.

8. EndingPhase:
- runs after EventPhase and before narration,
- evaluates configured endings ordered by `(priority ASC, ending_id ASC)`,
- if no ending matches, applies timeout ending policy from `run_config`:
  - `day > max_days`, or
  - `step_index >= max_steps`,
- writes ending metadata into `state_json.run_state` and marks session ended.

9. Pass3 narration:
- generate narration and optionally polish fallback text.
- LLM runtime is generate-only for both selection and narration paths.
- token usage is logged for statistics (`tokens_in`, `tokens_out`, provider), but no budget enforcement is applied.
- narration prompt payload includes:
  - quest summary (`active_quests` titles + recent quest events),
  - selected runtime event summary (`event_id`, title, hint, effects),
  - ending summary (`run_ended`, `ending_id`, outcome, epilogue).

## Quest Stage v1
Quest runtime uses stage-based progression:
- one active stage per active quest (`current_stage_id`, `current_stage_index`),
- all milestones in the active stage must complete before stage completion,
- stage completion emits `stage_completed`, applies `stage_rewards`, then activates the next stage (emits `stage_activated`) if one exists,
- final stage completion emits `quest_completed` and applies `completion_rewards`,
- `recent_events` keeps only the latest 20 entries.

## Run State
`state_json.run_state` is the runtime-only progress channel for non-quest run lifecycle:
- `step_index`
- `triggered_event_ids`
- `event_cooldowns`
- `ending_id`
- `ending_outcome`
- `ended_at_step`
- `fallback_count`

## Extended Runtime State
- `state_json.inventory_state`:
  - mixed inventory model (`stack_items` + `instance_items` + `equipment_slots` + `currency` + `capacity`)
- `state_json.external_status`:
  - `player_effects`, `world_flags`, `faction_rep`, `timers`
- `state_json.npc_state`:
  - relation/mood/belief/goals/status plus hot/cold memory split (`short_memory`, `long_memory_refs`)

Session creation seeds missing NPC runtime entries from `npc_defs` while preserving explicitly provided `initial_state.npc_state` entries.

## Step Observability
`ActionLog.classification.layer_debug` includes operational fields for runtime tuning:
- `selection_latency_ms`
- `narration_latency_ms`
- `fallback_reason`
- `inventory_mutation_count`
- `npc_mutation_count`
- `short_memory_compacted_count`
- `state_json_size_bytes`
- `prompt_context_npc_count`
- `llm_retry_count`

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
- Replay payload is story-runtime only and contains:
  - `session_id`
  - `total_steps`
  - `key_decisions`
  - `fallback_summary`
  - `story_path`
  - `state_timeline`
  - `run_summary`:
    - `ending_id`
    - `ending_outcome`
    - `total_steps`
    - `triggered_events_count`
    - `fallback_rate`

## Fallback Narration and Leak Safety
Fallback text source order:
1. fallback executor skeleton (if present),
2. pack fallback `text_variants` by neutral reason bucket,
3. service built-in deterministic fallback sentence.

Player-visible narrative is guarded against internal marker leakage and internal field names (for example `__fallback__`, `next_node_id`, `choice_id`, `intent_id`, `confidence`, `delta_scale`).

System-generated polish additionally blocks error-style phrases (`invalid choice`, `parse error`, `unknown choice`, `unknown action`, `unknown input`).
