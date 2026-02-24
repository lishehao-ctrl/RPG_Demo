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
- Runtime pack persistence is StoryPack v10 strict-only:
  - startup blocks on legacy/non-strict stored packs (`LEGACY_STORYPACKS_BLOCK_STARTUP`)
  - runtime load rejects non-strict stored pack (`RUNTIME_PACK_V10_REQUIRED`)

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
  - two-stage generation is enabled for:
    - `seed_expand`
    - `story_ingest`
    - `continue_write`
    - stage 1: idea expansion (creative blueprint)
    - stage 2: structured story build (`suggestions + patch_preview`)
    - each stage applies strict schema validation + fail-fast retries
  - prompt protocol:
    - backend transport is fixed to:
      - `POST https://api.xiaocaseai.cloud/v1/chat/completions`
    - system message is always injected:
      - `Return STRICT JSON. No markdown. No explanation.`
    - `temperature` is always forced to `0`
    - no `/v1/responses`, no `response_format`, no `json_schema`
    - retries are fail-fast (`0.5s`, `1s`) then raise
  - model failures return `503` (`ASSIST_LLM_UNAVAILABLE` or `ASSIST_INVALID_OUTPUT`) with retry hints.
  - no deterministic assist fallback payload is returned on model failure.
  - context may include incremental controls:
    - `operation: append | trim | rewrite`
    - `target_scope: global | layer | scene | option`
    - `target_scene_key`, `target_option_key`
    - `preserve_existing: bool`

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

## Author Assist Internal Layering (Current)

1. API façade:
- `app/modules/story/author_assist.py`
2. Core task logic:
- `app/modules/story/author_assist_core/service.py`
- `deterministic_tasks.py`, `seed_normalize.py`, `patch_ops.py`, `postprocess.py`
3. LLM orchestration:
- `app/modules/llm/adapter.py` (public façade)
- `app/modules/llm/runtime/*` (protocol/transport/parser/orchestrator)

This split is internal only; `POST /stories/author-assist` external response shape remains unchanged.

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
- `continue_write`
- `trim_content`
- `spice_branch`
- `tension_rebalance`

`seed_expand` generation policy (server-side normalized):
- 4-node tension loop is enforced:
  - `pressure_open`
  - `pressure_escalation`
  - `recovery_window`
  - `decision_gate`
- non-end scenes keep 2-4 options and maintain reachable `go_to` links.
- at least one recovery route appears every two scenes.
- ending trigger sync is enforced after flow rewrites:
  - invalid `ending.ending_rules[*].trigger.scene_key_is` is rewritten to an existing scene key
  - if ending rules are missing, a minimal compile-safe ending is seeded

Old task names are rejected with `422 ASSIST_TASK_V4_REQUIRED`.

## Playability Gate

`validate-author` and `compile-author` run structure/reachability/balance checks plus deterministic rollout metrics:

- `ending_reach_rate`
- `stuck_turn_rate`
- `no_progress_rate`
- `branch_coverage`
- `choice_contrast_score`
- `dominant_strategy_rate`
- `recovery_window_rate`
- `tension_loop_score`

Blocking errors fail compile through `AUTHOR_COMPILE_FAILED`.
Low branch coverage is warning-only by default.

## Architecture Guardrails

1. `authoring` compile/validate path stays deterministic and must not import `app.modules.llm`.
2. `author-assist` stays suggestion-only and must not persist story/session state.
3. Do not reintroduce pre-v4 compatibility projection in author payload handling.
4. For refactor PRs, run `docs/verification.md` -> `Architecture PR Minimum Gate`.
