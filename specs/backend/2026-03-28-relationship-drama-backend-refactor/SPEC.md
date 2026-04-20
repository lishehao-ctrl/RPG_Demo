# Relationship Drama Backend Refactor Spec

## Purpose

Rebuild the product semantics of RPG_Demo around:

- `轻乙女`
- `都市情感悬疑`
- `关系博弈叙事`

This pass treats the current product domain as disposable, but keeps the backend architecture skeleton:

- auth
- author preview / jobs / copilot
- published story library
- play sessions
- benchmark diagnostics

The goal is **not** to preserve current civic-procedural story content.  
The goal is to preserve the system shape while replacing the narrative domain, runtime semantics, and evaluation targets.

## Fixed Decisions

- This is a **backend-first product refactor**, not a prompt tweak.
- Current civic / dossier / mandate / public-pressure semantics are out of scope to preserve.
- Current top-level route groups stay:
  - `/auth/*`
  - `/author/*`
  - `/stories*`
  - `/play/*`
  - `/benchmark/*`
- Storage and execution topology stay for now:
  - FastAPI
  - single-host / single-process
  - SQLite-backed runtime state
  - cookie-session auth
- Existing DB data is **not** compatibility-protected.
  - old preview/job/story/session data may be dropped or rebuilt
  - local reset is allowed and preferred over compatibility shims
- Benchmark and evaluation remain first-class product infrastructure.

## Architecture To Keep

Keep these structural ideas intact:

- `story seed -> preview -> author job -> publish -> play`
- long-running author jobs with resumable checkpoints
- play sessions with persisted state + history + turn traces
- copilot as an editing surface on top of generated drafts
- benchmark routes and artifact-producing runners

Keep these module boundaries unless a stronger simplification appears during implementation:

- `rpg_backend/author/*`
- `rpg_backend/library/*`
- `rpg_backend/play/*`
- `rpg_backend/benchmark/*`
- `rpg_backend/main.py`

## Product Domain To Replace

### Old direction to remove

Do not preserve these as organizing concepts:

- civic pressure
- legitimacy
- ration / harbor / archive / referendum profile families
- dossier / mandate / public-record primary framing
- public-order closeout heuristics

### New direction to implement

The backend should now generate and run stories as:

- `都市情感悬疑互动叙事`
- protagonist-centered
- 3-5 strong relationship targets
- secrets, misread intentions, factional social pressure, betrayals, route reversals

Core player fantasy:

- choose who to trust
- choose who to get close to
- choose who to expose
- choose which relationship line to deepen or rupture

## New Authoring Domain Model

The author pipeline should generate a `relationship-drama bundle` instead of the current civic story bundle.

### Story seed / spark

Seeds should be about:

- protagonist identity hook
- situation hook
- relationship triangle / quartet
- buried secret
- social environment

Allowed shells:

- workplace
- campus
- entertainment industry
- wealthy family / inheritance
- urban supernatural

The shell is secondary. Relationship tension is primary.

### Preview output

Preview should answer these questions clearly:

- who is the protagonist
- what is the central emotional situation
- who are the 3-5 key targets
- what makes each target different
- what is the hidden tension / secret / risk
- what kind of route fantasy this story promises

Preview should no longer foreground:

- institutional topology
- civic tension labels
- procedural structure as the main attraction

### Author bundle

The canonical generated draft should contain at minimum:

- `protagonist profile`
  - public identity
  - hidden vulnerability
  - route-facing desire
- `target cast`
  - 3-5 strong leads
  - role in the social web
  - attraction hook
  - hidden agenda / secret
  - breaking point
- `relationship graph`
  - who wants what from whom
  - current alignment / hostility / history
- `route beats`
  - key scene ladder for tension escalation
- `ending matrix`
  - what conditions lead to each route ending
- `play framing`
  - scene tone
  - choice texture
  - state variables to expose at runtime

## New Runtime Semantics

### Replace current play metrics

Current play state should stop centering civic/public-system values.

New runtime should use:

- `global`
  - `heat`
  - `public_image`
  - `secret_exposure`
- `per-target relationship state`
  - `affection`
  - `trust`
  - `tension`
  - `suspicion`

These should be first-class runtime values, not prompt-only ideas.

### Turn interpretation

The play interpreter should classify turns in terms of relationship action, not civic action.

Expected action families should be rebuilt around:

- `flirt`
- `probe_secret`
- `deflect`
- `comfort`
- `accuse`
- `ally_with`
- `betray`
- `public_reveal`
- `private_confession`
- `jealousy_trigger`

The exact labels can differ, but the domain must be relationship-native.

### Suggested actions

Suggested actions should read like scene moves in a drama route:

- test someone's loyalty
- push for a private answer
- cover for someone
- confront a lie
- escalate closeness
- expose a secret in public

They should no longer feel like civic policy actions.

### Ending system

Replace the current ending interpretation taxonomy.

New public-facing ending families:

- `route_lock`
  - emotionally satisfying route success
- `bittersweet`
  - connection or truth gained with visible emotional cost
- `breakdown`
  - betrayal, collapse, or route failure
- `open_loop`
  - unresolved but still charged continuation outcome

Keep the judge architecture, but retune the semantics fully.

## Copilot Refactor

Copilot should become a `剧情导演 / 编剧室` backend surface.

Supported edit intents should prioritize:

- change chemistry pacing
- reframe a target's secret
- add or remove romantic tension
- rebalance triangle / rivalry pressure
- rewrite a scene into a stronger emotional beat
- change route ending tendency
- sharpen dialogue voice

Copilot must remain:

- structured
- previewable
- reversible

Do not regress it into free-form text overwrite.

## Library Semantics

The published story library should now behave like a `route / season shelf`.

Library card data should foreground:

- hook
- tone
- relationship configuration
- target count
- route promise

It should de-emphasize:

- civic topology
- procedural category labels

## Benchmark / Evaluation Refactor

Keep `LLM-as-a-Judge + Trace-based Evaluation`, but retune the rubric.

### Judge dimensions

Replace current quality focus with relationship-drama dimensions:

- `chemistry`
- `choice_tension`
- `route_clarity`
- `secret_payoff`
- `scene_heat`
- `voice_distinctness`
- `emotional_coherence`

### Trace focus

Trace analysis should prioritize:

- repeated scene patterns
- stale relationship deltas
- secret reveal timing failures
- route drift
- flattening of chemistry / tension over turns
- target differentiation failures

### Benchmark personas

Personas should be rebuilt around dramatic play styles, not civic strategy styles.

Recommended v1 persona set:

- `chaotic_flirt`
- `careful_observer`
- `jealous_rival`
- `soft_confessor`
- `truth_hunter`

These may replace the current benchmark personas entirely.

## Data / Migration Rules

- No compatibility patching for old generated stories or old sessions.
- Reset local author/play SQLite state when needed.
- Existing published stories may be treated as legacy and excluded from the new product surface.
- New benchmark artifacts should be recorded under a new phase/label family to avoid mixing old civic metrics with new relationship metrics.

## Acceptance Criteria

1. Existing route topology remains recognizable: auth, author, stories, play, benchmark.
2. Preview, author bundle, library, and play runtime all speak the new relationship-drama language consistently.
3. Play state exposes relationship-native variables instead of civic-native variables.
4. Copilot edits relationship pacing / secrets / scene beats structurally.
5. Benchmark judge rubric and trace summaries are retuned to the new product goal.
6. Old civic-specific assumptions are removed from story profiling and play guidance.
7. Local reset + fresh author -> publish -> play flow works end to end.

## Validation

- unit tests for new story profile routing / runtime state semantics
- API tests for preview, author job, library detail, play session
- benchmark runner smoke using new personas
- one real local author -> publish -> play smoke on fresh SQLite state
