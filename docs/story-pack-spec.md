# StoryPack Spec (v10 Stage v1 + Run v1)

## Scope
This is the active authoring and validation contract for story packs accepted by `/stories` APIs and executed by story runtime.

## External API Contract
- `GET /stories/{id}` returns `{story_id, version, is_published, pack}`.
- `pack` is raw DB `stories.pack_json`.
- Read path does not normalize or rewrite `pack`.

## Top-Level Fields
- `story_id: str`
- `version: int`
- `title: str`
- `start_node_id: str`
- `nodes: StoryNode[]`
- `characters: list[dict]` (optional)
- `item_defs: ItemDef[]` (optional)
- `npc_defs: NPCDef[]` (optional)
- `status_defs: StatusDef[]` (optional)
- `initial_state: dict` (optional)
- `default_fallback: StoryFallback | null` (optional)
- `fallback_executors: FallbackExecutor[]` (optional)
- `global_fallback_choice_id: str | null` (optional, must reference `fallback_executors[].id`)
- `quests: StoryQuest[]` (optional)
- `events: StoryEvent[]` (optional)
- `endings: StoryEnding[]` (optional)
- `run_config: StoryRunConfig | null` (optional)
- `author_source_v4: dict | null` (optional, author trace metadata)

Hard-cut v10:
- `author_source_v3` is not accepted.

## StoryNode
- `node_id: str`
- `scene_brief: str`
- `choices: StoryChoice[]`
- `intents: StoryIntent[]` (mapping-only)
- `node_fallback_choice_id: str | null` (must reference a visible choice id in node when present)
- `fallback: StoryFallback | null`
- `is_end: bool`

## StoryChoice
- `choice_id: str`
- `display_text: str`
- `action: StoryAction`
- `requires: StoryChoiceRequires | null`
- `effects: StoryChoiceEffects | null`
- `action_effects_v2: StoryActionEffectsV2 | null` (optional; ops-only extension channel)
- `next_node_id: str`
- `is_key_decision: bool`

Hard-cut v10:
- `is_fallback` is not accepted.

## StoryChoiceEffects
Allowed per stat (`energy`, `money`, `knowledge`, `affection`):
- scalar numeric value (`int` or `float`), or
- `null`.

Extended deterministic op channels (all optional):
- `inventory_ops: InventoryOp[]`
- `npc_ops: NPCOp[]`
- `status_ops: StatusOp[]`
- `world_flag_ops: WorldFlagOp[]`

Runtime note:
- scalar deltas and op channels are both deterministic and are applied in the same transition transaction.

## StoryActionEffectsV2
Ops-only extension channel for action-level effects:
- `inventory_ops: InventoryOp[]`
- `npc_ops: NPCOp[]`
- `status_ops: StatusOp[]`
- `world_flag_ops: WorldFlagOp[]`

Runtime note:
- `choice.effects.*_ops` and `choice.action_effects_v2.*_ops` are merged into one deterministic patch stream.

## ItemDef
- `item_id: str`
- `name: str`
- `kind: "stack" | "instance" | "equipment" | "key"`
- `stackable: bool`
- `max_stack: int | null`
- `slot: "weapon" | "armor" | "accessory" | null`
- `tags: list[str]`
- `meta: dict`

## NPCDef
- `npc_id: str`
- `name: str`
- `role: str | null`
- `persona: dict[str, number]`
- `speech_style: list[str]`
- `taboos: list[str]`
- `long_term_goals: list[str]`
- `relation_axes_init: dict[str, number]`

## StatusDef
- `status_id: str`
- `name: str`
- `target: "player" | "npc" | "both"`
- `default_stacks: int`
- `max_stacks: int | null`
- `default_ttl_steps: int | null`
- `meta: dict`

Hard-cut v10:
- list windows (`[min,max]`) are rejected.
- object windows (`{"min":x,"max":y}`) are rejected.

## Fallback Text Variants
Allowed keys only:
- `NO_INPUT`
- `BLOCKED`
- `FALLBACK`
- `DEFAULT`

Hard-cut v10:
- older reason-family keys are not accepted.

## FallbackExecutor
Pack-level fallback template:
- `id: str`
- `label: str | null`
- `action_id: str | null`
- `action_params: dict`
- `effects: StoryChoiceEffects`
- `prereq: StoryChoiceRequires | null`
- `next_node_id: str | null`
- `narration: {skeleton: str | null} | null`

Runtime semantics:
- executor does not need to be present in current node visible choices,
- executor can be selected as fallback execution target,
- executor prereq failure results in degraded execution with no recursive reroute.

## StoryQuest
- `quest_id: str`
- `title: str`
- `description: str | null`
- `auto_activate: bool` (default `true`)
- `stages: QuestStage[]` (at least 1)
- `completion_rewards: StoryChoiceEffects | null`

## QuestStage
- `stage_id: str`
- `title: str`
- `description: str | null`
- `milestones: QuestStageMilestone[]` (at least 1)
- `stage_rewards: StoryChoiceEffects | null`

## QuestStageMilestone
- `milestone_id: str`
- `title: str`
- `description: str | null`
- `when: QuestTrigger`
- `rewards: StoryChoiceEffects | null`

## QuestTrigger
All specified fields are AND-ed:
- `node_id_is: str | null`
- `next_node_id_is: str | null`
- `executed_choice_id_is: str | null`
- `action_id_is: str | null`
- `fallback_used_is: bool | null`
- `state_at_least: dict[str, number]`
- `state_delta_at_least: dict[str, number]`

## StoryRunConfig
- `max_days: int` (default `7`)
- `max_steps: int` (default `24`)
- `default_timeout_outcome: "neutral" | "fail"` (default `"neutral"`)

## StoryEventTrigger
All specified fields are AND-ed:
- `node_id_is: str | null`
- `day_in: list[int] | null`
- `slot_in: list["morning" | "afternoon" | "night"] | null`
- `fallback_used_is: bool | null`
- `state_at_least: dict[str, number]`
- `state_delta_at_least: dict[str, number]`

## StoryEvent
- `event_id: str`
- `title: str`
- `weight: int` (default `1`, min `1`)
- `once_per_run: bool` (default `true`)
- `cooldown_steps: int` (default `2`, min `0`)
- `trigger: StoryEventTrigger`
- `effects: StoryChoiceEffects | null`
- `narration_hint: str | null`

## StoryEndingTrigger
All specified fields are AND-ed:
- `node_id_is: str | null`
- `day_at_least: int | null`
- `day_at_most: int | null`
- `energy_at_most: int | null`
- `money_at_least: int | null`
- `knowledge_at_least: int | null`
- `affection_at_least: int | null`
- `completed_quests_include: list[str]`

## StoryEnding
- `ending_id: str`
- `title: str`
- `priority: int` (default `100`, smaller first)
- `outcome: "success" | "neutral" | "fail"`
- `trigger: StoryEndingTrigger`
- `epilogue: str`

## Structural Validation
Structural validator enforces:
- start node existence,
- dangling next-node checks,
- duplicate id checks,
- duplicate `item_defs/npc_defs/status_defs` ids,
- fallback wiring integrity,
- reserved fallback prefix rules,
- node fallback references and global fallback executor references.
- dangling effect-op references for choice/default/node-fallback/fallback-executor scopes (`item_id`, `npc_id`, `status_id`),
- status target compatibility checks (`status_defs.target` vs `status_ops.target`),
- quest id uniqueness,
- stage id uniqueness within each quest,
- milestone id uniqueness within each stage,
- quest trigger node references (`node_id_is`, `next_node_id_is`) must exist,
- quest trigger executed choice reference (`executed_choice_id_is`) must reference visible choice ids.
- event id uniqueness (`event_id`) pack-wide,
- ending id uniqueness (`ending_id`) pack-wide,
- event trigger `node_id_is` must reference an existing node,
- ending trigger `node_id_is` must reference an existing node.
- strict schema validation rejects unknown top-level keys (including legacy metadata keys).

## Startup Hard-Cut
- On application startup, all stored `stories.pack_json` rows are validated against StoryPack v10 strict schema + structural rules.
- Any invalid or legacy row blocks startup with:
  - `LEGACY_STORYPACKS_BLOCK_STARTUP`
- Runtime load path does not attempt legacy compatibility projection.

## Runtime Routing Summary
1. Input Policy Gate:
- normalize and length-limit free input,
- block injection-like strings and force safe fallback route.
2. Pass0 hard no-input -> direct fallback.
3. Pass1 selection -> visible choice or direct fallback.
4. Pass2 prereq -> possible single reroute to fallback, then degraded if rerouted target fails.
5. Deterministic transition:
- apply action state change,
- apply scalar effects and effect ops (`inventory_ops/npc_ops/status_ops/world_flag_ops`) in one transaction.
6. QuestUpdate phase (after deterministic transition, before narration):
   - updates `state_json.quest_state`,
   - applies milestone/stage/completion rewards once,
   - writes quest progress markers into action log matched rules.
7. EventPhase (after QuestUpdate):
   - evaluates eligible events with deterministic weighted selection,
   - evaluates `trigger.node_id_is` against the current node (pre-transition `story_node_id`),
   - evaluates `day_in` / `slot_in` / state thresholds against post-transition state (`state_after`),
   - seed: `sha256(f"{session_id}:{step_id}:{story_node_id}")`,
   - enforces `once_per_run` and `cooldown_steps`,
   - applies event effects through normal state clamp,
   - writes `type=runtime_event` markers into action log matched rules.
8. EndingPhase (after EventPhase):
   - evaluates configured endings ordered by `(priority ASC, ending_id ASC)`,
   - if none matched, checks timeout by `run_config.max_days` and `run_config.max_steps`,
   - on ending, session is marked ended and ending metadata is written to run state.
9. Memory Compaction:
- compacts NPC short-memory overflow to long-memory refs,
- applies soft/hard state-size pressure trimming.
10. Pass3 narration -> narration generation + fallback narrative safety checks.

## Outward Fallback Reason
Story step outward `fallback_reason` values:
- `NO_INPUT`, `BLOCKED`, `FALLBACK`, or `null`.

## Runtime Quest State (`state_json.quest_state`)
- `active_quests: list[str]`
- `completed_quests: list[str]`
- `quests: dict[quest_id, QuestRuntimeState]`
- `recent_events: list[QuestEvent]` (keeps last 20)
- `event_seq: int`

`QuestRuntimeState`:
- `status: "inactive" | "active" | "completed"`
- `current_stage_index: int | null`
- `current_stage_id: str | null`
- `stages: dict[stage_id, {status, milestones, completed_at}]`
- `completed_at: str | null`

Stage v1 runtime rules:
- exactly one active stage per active quest,
- only current stage milestones are evaluated,
- stage completes when all its milestones are done,
- on stage complete: apply `stage_rewards`,
- if next stage exists: activate next stage,
- if final stage completes: apply `completion_rewards` once and mark quest completed.

## Runtime Inventory State (`state_json.inventory_state`)
- `capacity: int`
- `currency: dict[str, int]`
- `stack_items: dict[item_id, {qty}]`
- `instance_items: dict[instance_id, {item_id, durability, bound, props}]`
- `equipment_slots: {weapon, armor, accessory}`

Model rule:
- mixed inventory model is used: stack for consumables, instance model for equipment/key items.

## Runtime External Status (`state_json.external_status`)
- `player_effects: list[{status_id, stacks, expires_at_step}]`
- `world_flags: dict[str, scalar]`
- `faction_rep: dict[str, int]`
- `timers: dict[str, int]`

## Runtime NPC State (`state_json.npc_state`)
Per `npc_id`:
- `relation: dict[str, int]`
- `mood: dict[str, float]`
- `beliefs: dict[str, float]`
- `active_goals: list[{goal_id, priority, progress, status}]`
- `status_effects: list[{status_id, stacks, expires_at_step}]`
- `short_memory: list[dict]` (hot memory ring)
- `long_memory_refs: list[str]` (cold memory refs)
- `last_seen_step: int`

## Runtime Run State (`state_json.run_state`)
- `step_index: int`
- `triggered_event_ids: list[str]`
- `event_cooldowns: dict[event_id, int]`
- `ending_id: str | null`
- `ending_outcome: "success" | "neutral" | "fail" | null`
- `ended_at_step: int | null`
- `fallback_count: int`

Step response adds ending metadata without breaking old fields:
- `run_ended: bool`
- `ending_id: str | null`
- `ending_outcome: "success" | "neutral" | "fail" | null`
