# Relationship Drama Runtime + Graph Architecture Spec

## Purpose

Translate the high-level pivot from civic procedural thriller to:

- `都市情感悬疑`
- `轻乙女`
- `关系博弈叙事`

into a backend runtime architecture that is concrete enough to implement.

This document answers three questions:

1. `当前 beat / turn engine 哪些可以保留？`
2. `新的 beat schema 和 state schema 应该长什么样？`
3. `Graph RAG 应该插在哪一层，而不是把系统带偏？`

## Core Decision

Do **not** replace the entire play engine.

Keep:

- session lifecycle
- turn loop
- persistence
- history
- turn traces
- benchmark / judge / trace diagnostics

Replace:

- story semantics
- beat semantics
- state semantics
- interpret/judge/render schemas

Recommended architecture:

`Graph RAG in the back, drama beat engine in the middle, turn engine in the front.`

That means:

- Graph picks and composes character/secret/relationship material
- Beat engine decides the dramatic structure of an episode/route
- Turn engine handles each player move and updates relationship state

## What To Keep From The Current Engine

These are reusable and should remain the foundation:

- `PlaySessionService`
- `PlaySessionState` persistence pattern
- `PlaySessionSnapshot`
- `PlaySessionHistoryEntry`
- `PlayTurnTrace`
- `interpret -> ending judge -> pyrrhic critic -> render` as a multi-stage pipeline pattern
- benchmark collection and summary architecture

These are solving real runtime problems independent of genre:

- resumability
- state progression
- replayability
- observability
- evaluation

## What To Replace

Treat the following as genre-bound and refactor aggressively:

- `affordance_tag`
- `axis_values`
- `stance_values`
- `flag_values`
- `truths`
- `events`
- `route_unlock_rules`
- current `closeout_profile` / `runtime_policy_profile` semantics
- civic-pressure-oriented beat hints

## Recommended High-Level Runtime Model

The new model should be:

- `Story shell`
  - 豪门 / 娱乐圈 / 职场 / 校园 / 都市异能
- `Relationship cast`
  - protagonist + 3-5 strong targets
- `Relationship graph`
  - attraction, trust, suspicion, debt, alliance, betrayal risk
- `Drama beat ladder`
  - 4-6 dramatic segments
- `Turn loop`
  - each user action changes relationship state and pushes beat heat

## Beat Schema

### Why keep beats at all

Do not remove beats.

Without beats, Graph RAG can give rich material but not reliable pacing.

You still need a structure that answers:

- what phase of the route is this
- what kind of scene should happen now
- what emotional move is expected here
- how close are we to the next reveal or break

### New beat meaning

A beat is no longer:

- a civic escalation stage
- a task/procedure phase

A beat is now:

- a dramatic segment in a route
- an emotional and narrative milestone

### Recommended beat ladder

Use a compact 5-beat default ladder:

1. `hook`
   - first encounter / destabilizing premise
   - attraction or hostility becomes visible
2. `misread`
   - misunderstanding, wrong alliance, hidden motive
3. `pressure`
   - public/private conflict, jealousy, rumor, forced choice
4. `reveal`
   - secret exposure, confession, betrayal, route split
5. `lock`
   - ending direction becomes irreversible

This should be configurable per story shell, but the default should stay small and legible.

### New beat object

Recommended replacement for current beat runtime semantics:

- `beat_id`
- `phase`
  - `hook | misread | pressure | reveal | lock`
- `title`
- `scene_goal`
- `emotional_goal`
- `required_heat`
- `required_secret_ids`
- `focus_character_ids`
- `rival_character_ids`
- `preferred_move_families`
- `blocked_move_families`
- `reveal_candidates`
- `fallback_scene_prompt`

The important shift is:

- from procedural intent
- to emotional + dramatic intent

## Turn State Schema

### Keep the shape, replace the meaning

The engine should still carry a single persisted session state object.

But the state values should be rewritten around relationship drama.

### Global state

Recommended global values:

- `scene_heat`
  - how emotionally volatile the current route is
- `public_image`
  - how the outside world currently reads the protagonist
- `secret_exposure`
  - how much hidden truth has become unstable or visible
- `route_lock`
  - how strongly the story is drifting toward one target/ending

### Per-target relationship state

For each target character:

- `affection`
- `trust`
- `tension`
- `suspicion`
- `dependency`

Do not force all of these into user-facing bars on day one, but keep the backend ready for them.

### Session memory state

Track:

- `known_secret_ids`
- `public_event_ids`
- `private_scene_ids`
- `promise_ids`
- `betrayal_ids`

These replace current truth/event semantics with relationship-native memory.

### Suggested visible UI-facing state

The snapshot should expose the subset that the UI needs most:

- `亲密`
- `信任`
- `危险`
- `秘密暴露`
- `当前站队`

This can remain derived from richer backend state.

## Turn Interpretation Schema

### Current problem

The current affordance model is actionable, but its labels are from the old domain.

### New move families

Replace or remap the core action families to relationship-native moves:

- `flirt`
- `probe_secret`
- `comfort`
- `deflect`
- `accuse`
- `ally_with`
- `betray`
- `public_reveal`
- `private_confession`
- `jealousy_trigger`

Optional shell-specific additions:

- `leverage_status`
- `ignite_rumor`
- `stage_managed_scene`

### New interpret result

The turn interpretation draft should answer:

- `move_family`
- `target_character_ids`
- `intimacy_risk`
  - `low | medium | high`
- `scene_frame`
  - `private | semi_public | public`
- `intent_summary`

Do not center the result around civic/procedural execution frames.

## Render Model

Render should output:

- scene narration
- relationship impact summary
- updated suggested next moves

The rendering model should strongly prefer:

- emotional specificity
- target differentiation
- visible consequences in relationship state

The render repair layer should focus on:

- removing generic soap-drama repetition
- keeping characters distinct
- restoring second-person or direct player placement when lost

## Ending / Route Judgment

### Keep the judge layer

Do not remove the judge.

The judge is valuable because relationship drama needs controlled ending classification too.

### Replace ending families

Recommended public ending families:

- `route_lock`
  - strongest intended route fulfillment
- `bittersweet`
  - emotional success with cost
- `breakdown`
  - trust collapse / betrayal / route failure
- `open_loop`
  - unresolved but charged continuation

### New judge inputs

The judge should use:

- relationship state totals
- key secret exposure
- betrayal count
- route lock strength
- scene heat trajectory

instead of the current civic-pressure framing.

## Graph RAG Role

### What Graph RAG should do

Graph RAG should power:

- cast selection
- relationship assembly
- secret selection
- shell-consistent dramatic event retrieval
- visual asset retrieval

### What Graph RAG should not do

It should **not** replace:

- beat pacing
- route structure
- turn loop
- ending classification

### Why

Graph retrieval gives good material but weak pacing by itself.

If you let retrieval drive the whole story, the likely failure modes are:

- drift
- over-branching
- repetitive scene logic
- weak escalation rhythm

## Graph Schema

Recommended graph node types:

- `character`
- `relationship`
- `secret`
- `dramatic_event`
- `story_shell`
- `visual_asset`

### Character node

- `character_id`
- `display_name`
- `archetype`
- `role_tags`
- `public_persona`
- `hidden_wound`
- `desire_vector`
- `danger_vector`
- `visual_asset_ids`

### Relationship edge

- `source_character_id`
- `target_character_id`
- `relation_type`
  - `attraction | alliance | debt | jealousy | rivalry | past_romance | leverage`
- `intensity`
- `instability`

### Secret node

- `secret_id`
- `owner_character_ids`
- `secret_type`
  - `identity | betrayal | contract | family | scandal | evidence`
- `reveal_risk`
- `public_damage_level`

### Dramatic event node

- `event_id`
- `event_type`
  - `engagement_announcement | rumor_spike | ex_returns | will_revealed | video_leak | confrontation_dinner`
- `required_roles`
- `compatible_shells`
- `secret_dependencies`
- `visual_tags`

### Story shell node

- `shell_id`
  - `wealth_families | entertainment_scandal | office_power | campus_status | urban_supernatural`
- `tone_profile`
- `default_event_ids`
- `allowed_archetypes`

### Visual asset node

- `asset_id`
- `character_id`
- `asset_kind`
  - `hero | portrait | dressup | scandal_card | message_card`
- `style_tags`
- `reference_image_path`

## Story Generation Flow With Graph

Recommended runtime composition flow:

1. `seed normalization`
   - user prompt is mapped into one supported story shell
2. `shell selection`
   - choose the closest allowed shell
3. `cast assembly`
   - retrieve protagonist-compatible target set from graph
4. `relationship graph assembly`
   - retrieve core ties / rivalries / debts / attraction edges
5. `secret package assembly`
   - retrieve 1-3 secrets suitable for this shell
6. `beat ladder generation`
   - generate or template the 4-6 beats from shell + cast + secrets
7. `play session start`
   - use assembled cast/state/beat structure

The critical rule:

`Seed chooses shell first, not cast first.`

This keeps product coherence.

## Handling Difficult / Weird Seed Prompts

Do not accept every seed literally.

Use a 3-way routing model:

### 1. Direct fit

Prompt clearly matches supported shells:

- accept directly

### 2. Soft fit

Prompt is weird but adaptable:

- rewrite into platform shell
- preserve emotional hook, discard irrelevant worldbuilding

### 3. Out of range

Prompt does not fit the product:

- reject gently
- offer 2-3 nearby route templates instead

### Backend requirement

The backend should produce a normalized seed packet:

- `accepted_shell`
- `protagonist_hook`
- `relationship_hook`
- `secret_hook`
- `rewritten_seed`
- `rewrite_reason`

This should become part of preview/debug diagnostics.

## Incremental Implementation Order

### Phase 1

- keep current play engine shell
- replace state schema and move families
- add new beat phase ladder

### Phase 2

- replace story-shell routing
- add graph-based cast/secret retrieval

### Phase 3

- retune judge metrics and benchmark personas
- add visual asset retrieval integration

### Phase 4

- optimize graph ranking / fallback / shell rewrite logic

## Acceptance Criteria

1. Turn engine and persistence remain intact.
2. Beat semantics are replaced with relationship-drama phases.
3. Session state is relationship-native, not civic-native.
4. Graph RAG is used for cast/secret/event retrieval, not as a total story engine.
5. Weird seeds are normalized into supported shells instead of exploding product scope.
6. Benchmark remains operational after the semantic swap.
