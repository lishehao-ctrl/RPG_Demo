# Story Authoring Spec (ASF v4)

## Purpose
ASF v4 is the only accepted authoring format for author endpoints.

- Author format: creative-first layered writing + systems.
- Runtime format: StoryPack v10 (`nodes`, `choices`, `intents`, `quests`, `events`, `endings`).
- Bridge: deterministic compiler (`ASF v4 -> StoryPack v10`).

## Hard-Cut Policy

- `POST /stories/validate-author` and `POST /stories/compile-author` accept ASF v4 only.
- pre-v4 payloads are rejected with `422`:
  - `detail.code = "AUTHOR_V4_REQUIRED"`
- Runtime story/session APIs are unchanged.

## Endpoints

- `POST /stories/validate-author`
  - input: ASF v4 payload
  - output: `{valid, errors, warnings, compiled_preview, playability}`
- `POST /stories/compile-author`
  - input: ASF v4 payload
  - output: `{pack, diagnostics}`
- `POST /stories/author-assist`
  - input: `{task, locale, context}`
  - output: `{suggestions, patch_preview, warnings, provider, model}`
  - behavior: suggestion-only, never auto-persist

## ASF v4 Top-Level Shape

```json
{
  "format_version": 4,
  "entry_mode": "spark | ingest",
  "source_text": "string | null",
  "meta": {},
  "world": {},
  "characters": {},
  "plot": {},
  "flow": {},
  "action": {},
  "consequence": {},
  "ending": {},
  "systems": {},
  "writer_journal": [],
  "playability_policy": {}
}
```

Notes:

- `flow.scenes/options` remains the only runtime branching source of truth.
- `writer_journal` and `source_text` are metadata for author workflow and traceability.
- compiler writes `author_source_v4` into pack metadata.

## Assist Tasks (v4)

`POST /stories/author-assist` supports:

- `story_ingest`
- `seed_expand`
- `beat_to_scene`
- `scene_deepen`
- `option_weave`
- `consequence_balance`
- `ending_design`
- `consistency_check`

Old task names are rejected with `422 ASSIST_TASK_V4_REQUIRED`.

## Playability Gate

`validate-author` and `compile-author` run structure/reachability/balance checks plus deterministic rollout metrics:

- `ending_reach_rate`
- `stuck_turn_rate`
- `no_progress_rate`
- `branch_coverage`

Blocking errors fail compile through `AUTHOR_COMPILE_FAILED`.
Low branch coverage is warning-only by default.
