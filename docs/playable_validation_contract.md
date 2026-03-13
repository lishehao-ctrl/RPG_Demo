# Playable Validation Contract

This repository now treats validation as a **playable-first** gate.

`review_ready` means:

- the story pack is structurally valid
- the runtime can load it
- the player can move through scenes
- fail-forward behavior exists
- at least one ending is reachable

It does **not** mean the story is polished, balanced, or especially good.

---

## Mental Model

Validation is split into two layers:

1. Author workflow intermediate checks
2. Final playable pack checks

The first protects generation while the story is being built.
The second protects runtime safety before `review_ready` and publish.

---

## Workflow Contract

Author workflow is a single playable-first path:

1. `generate_story_overview`
2. `plan_beats`
3. `generate_beat`
4. `beat_lint`
5. `assemble_story_pack`
6. `normalize_story_pack`
7. `final_lint`
8. `review_ready`

Retry and timeout policy is unified across this workflow:

- max `3` attempts per branch path
- `20s` timeout per node attempt

If `final_lint` fails, the run goes directly to `workflow_failed`.

---

## Final Pack: Hard Errors

A story pack fails validation if any of these are true:

- `StoryPack` schema validation fails
- duplicate `scene.id`
- duplicate `move.id`
- duplicate `beat.id`
- duplicate `npc_profile.name`
- a beat entry scene does not exist
- a scene points to an unknown beat
- a scene has fewer than 2 or more than 3 global moves
- a scene contains non-global `always_available_moves`
- a scene references a missing move
- an exit condition points to a missing scene
- an exit condition is missing its required `key`
- a move has duplicate outcome ids
- a move does not contain `fail_forward`
- a move outcome points to a missing scene
- a banned move id appears
- some scenes are unreachable from the entry scene
- no terminal scene exists
- the entry scene cannot reach any terminal scene

These rules live in:

- `rpg_backend/domain/linter.py`
- `rpg_backend/domain/pack_schema.py`

---

## Final Pack: Warnings Only

These do not block `review_ready` or publish:

- duplicate beat titles
- `npc_profiles` and `npcs` not perfectly aligned
- a scene missing one or more strategy styles
- total beat step budget lower than scene count
- an NPC appearing fewer than 2 times

These are quality signals, not runtime blockers.

---

## Author Workflow: Intermediate Beat Checks

During generation, each beat draft still has stricter internal checks.
This protects the pipeline before assembly.

A beat draft must satisfy:

- blueprint identity fields still match
  - `beat_id`
  - `title`
  - `objective`
  - `conflict`
  - `required_event`
  - `entry_scene_id`
- NPCs must come from the overview roster
- scene ids and move ids must not collide with prior beats
- `required_event` must not collide with prior beats
- `entry_scene_id` must exist inside the beat
- each scene must use the fixed global `always_available_moves`
- each scene must reference only local moves
- scene exit links must stay inside the beat
- each move must include both `success` and `fail_forward`
- outcome ids must be unique
- outcome next-scene links must stay inside the beat

These checks live in:

- `rpg_backend/generator/author_workflow_validators.py`

Note:

- beat-time strategy-style coverage is still enforced during generation
- pack-time strategy-style coverage is only a warning

This is intentional: we keep generation guardrails tighter than the final playable gate.

---

## Move Freedom Boundary

Moves are now split into:

- surface
- execution

The LLM is allowed to define the move surface:

- `label`
- `intents`
- `synonyms`
- `roleplay_examples`

The backend still owns execution:

- `strategy_style`
- template selection
- `resolution_policy`
- `outcomes`
- `effects`
- `fail_forward`
- scene transitions

So the player sees more expressive actions, but runtime behavior stays deterministic.

---

## What `review_ready` Means Now

`review_ready` means:

- this story is playable
- it is safe to publish into runtime
- quality warnings may still exist

Examples of stories that can be `review_ready`:

- a story where one NPC only appears once
- a story with repetitive beat titles
- a story whose local move surfaces are a little bland

Examples of stories that cannot be `review_ready`:

- a story with unreachable scenes
- a story with no `fail_forward`
- a story that cannot reach an ending
- a story that references missing moves or scenes

---

## Practical Rule

Use this sentence when reasoning about the system:

`review_ready = playable, not polished`
