# StoryPack Spec (v10 Stage v1)

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
- `initial_state: dict` (optional)
- `default_fallback: StoryFallback | null` (optional)
- `fallback_executors: FallbackExecutor[]` (optional)
- `global_fallback_choice_id: str | null` (optional, must reference `fallback_executors[].id`)
- `quests: StoryQuest[]` (optional)

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
- `next_node_id: str`
- `is_key_decision: bool`

Hard-cut v10:
- `is_fallback` is not accepted.

## StoryChoiceEffects
Allowed per stat (`energy`, `money`, `knowledge`, `affection`):
- scalar numeric value (`int` or `float`), or
- `null`.

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
- legacy reason-family keys are not accepted.

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

## Structural Validation
Structural validator enforces:
- start node existence,
- dangling next-node checks,
- duplicate id checks,
- fallback wiring integrity,
- reserved fallback prefix rules,
- node fallback references and global fallback executor references.
- quest id uniqueness,
- stage id uniqueness within each quest,
- milestone id uniqueness within each stage,
- quest trigger node references (`node_id_is`, `next_node_id_is`) must exist,
- quest trigger executed choice reference (`executed_choice_id_is`) must reference visible choice ids.

## Runtime Routing Summary
1. Pass0 hard no-input -> direct fallback.
2. Pass1 selection -> visible choice or direct fallback.
3. Pass2 prereq -> possible single reroute to fallback, then degraded if rerouted target fails.
4. QuestUpdate phase (after Pass2 state transition, before Pass3 narration):
   - updates `state_json.quest_state`,
   - applies milestone/stage/completion rewards once,
   - writes quest progress markers into action log matched rules.
5. Pass3 narration -> narration generation + fallback narrative safety checks.

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
