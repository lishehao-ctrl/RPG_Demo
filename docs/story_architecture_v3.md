# Story Architecture v3 (Source of Truth)

This document is the canonical specification for the interactive narrative runtime and story generation model.

## Goals
- 8-12 minutes per playthrough.
- 14-16 turns as runtime pacing target.
- Accept-All input handling: button and free-text inputs always execute a move.

## Core Structure
Story packs follow:
- Beat -> Scene -> Move -> Outcome

## Beat
- 3-5 beats per story.
- Required fields:
  - `id`
  - `title`
  - `step_budget` (recommended 3-4)
  - `required_events`
  - `npc_quota`
  - `entry_scene_id`
- Aggregate `step_budget` should align with 14-16 turns.

## Scene
- Each scene belongs to one beat.
- `scene_seed` is short structured context (situation, objective, conflict), not long prose.
- `present_npcs`: typically 1-2 in-scene NPCs.
- `enabled_moves`: 3-5 visible moves, never above 6.
- `always_available_moves`: 2-3 global moves; must include at least two from:
  - `global.clarify`
  - `global.look`
  - `global.help_me_progress`
- Branches should reconverge within 1-2 steps.

## Move
- Move is an executable action interface, not a static choice label.
- Free-text routes to moves through `intents` and `synonyms`.
- Move supports argument schema via `args_schema`.
- Move has deterministic `resolution_policy`.
- Every move must include:
  - `success`
  - `fail_forward`
- `partial` is recommended.

## Outcome
- `result`: `success | partial | fail_forward`
- `effects`: deterministic state deltas.
- `next_scene_id`: optional and may reconverge.
- `narration_slots`:
  - `npc_reaction`
  - `world_shift`
  - `clue_delta`
  - `cost_delta`
  - `next_hook`
- Every step must produce at least one perceivable change.
- `fail_forward` must never stall; it must advance progression (progress delta or event trigger).

## Runtime Two-Pass
### Pass A: Intent Routing
- Button: direct move invocation.
- Free-text: provider route result with `move_id`, `args`, `confidence`, `interpreted_intent`.
- Low confidence or invalid routing must fallback to global moves and still progress.

### Pass B: Outcome Resolution
- Deterministic outcome selection.
- Preconditions choose outcome; they never reject execution.
- If success/partial preconditions fail, select fail_forward.
- Apply effects, update progress, transition scene.

### Narration
- Provider only renders text from slots.
- Enforce `Echo + Commit + Hook` shape.
- Never leak internal fields, IDs, or debug markers.

## Story Generator Pipeline
Generation flow:
1. Seed/Prompt -> BeatPlan
2. BeatPlan -> Scenes
3. Scenes -> Moves/Outcomes
4. Lint
5. Regenerate whole pack when lint fails (max 3 regenerates / 4 total attempts)
6. Return draft pack, optional publish

## Quality Gates
- Linter must validate schema/reference/invariants.
- Every move has fail_forward.
- Every scene has global moves.
- Reachability from entry scenes.
- At least one terminal path.
- Pacing compatible with 14-16 turns.
