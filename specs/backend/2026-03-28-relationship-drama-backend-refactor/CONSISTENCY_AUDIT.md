# Relationship Drama Consistency Audit

This document freezes the current consistency spine and classifies each live touchpoint as:

- `keep`
- `re-scope`
- `delete`

The rule is:

- no new civic-specific logic should be added
- `relationship_drama` becomes the primary target path

## 1. Seed and Brief Normalization

### `rpg_backend/author/compiler/brief.py`
- status: `keep`
- reason:
  - still useful for turning raw seed text into compact structured prose fields
- re-scope:
  - feed it the normalized/re-written seed packet instead of the raw product seed when available

### `rpg_backend/author/seed_normalization.py`
- status: `keep`
- reason:
  - canonical entry point for shell routing, relationship hook, secret hook, and rewritten seed

## 2. Theme / Shell Routing

### `rpg_backend/story_profiles.py`
- status: `re-scope`
- reason:
  - currently optimized for retired civic shell families
- target:
  - only keep as legacy compatibility routing
  - new author/play logic should prefer `story_shell_id`

### `rpg_backend/author/compiler/router.py`
- status: `re-scope`
- reason:
  - still used to map preview/bundle generation strategies
- target:
  - shell-based defaults should become primary
  - old theme decisions become compatibility fallback

## 3. Author Workflow Decomposition

### `rpg_backend/author/workflow.py`
- status: `keep`
- reason:
  - staged workflow skeleton, checkpointing, and serial merge shape are valuable
- re-scope:
  - normalize seed before focus_brief
  - shell defaults should drive strategy selection
  - later fan-out should happen here

### `rpg_backend/author/jobs.py`
- status: `keep`
- reason:
  - long-running job orchestration, persistence, diagnostics, and publish path are core assets
- re-scope:
  - preview/job creation should route through normalized seed semantics

## 4. Structured Generation + Retry

### `rpg_backend/author/generation/*`
- status: `keep`
- reason:
  - structured generation, retries, and result wrapping still solve the right engineering problem
- re-scope:
  - prompts, schemas, and quality expectations should become relationship-drama-native

### shared transport / LLM gateway
- status: `keep`
- reason:
  - transport, retries, traces, and usage capture are architecture assets

## 5. Compiler / Normalizer Passes

### `rpg_backend/author/compiler/*`
- status: `re-scope`
- reason:
  - compiler passes are useful, but current semantics are civic-heavy
- target:
  - keep bundle assembly
  - replace beat / route / ending meaning

### `rpg_backend/play/compiler.py`
- status: `keep`
- reason:
  - single translation step from author bundle to play plan remains correct
- re-scope:
  - emit `relationship_drama` as primary mode when normalized seed is present

## 6. Quality / Repair Passes

### `rpg_backend/author/quality/*`
- status: `re-scope`
- reason:
  - validation layer is good, but many reasons still speak the old domain
- target:
  - collapse into shell / cast / relationship / reveal / beat coherence validators

### `rpg_backend/play/closeout_judge.py`
- status: `re-scope`
- reason:
  - judge layer is worth keeping, but current labels and reasoning target civic outcomes

## 7. Context Lock / Snapshot Invariants

### context-lock / snapshot-stage annotations in author flow
- status: `keep`
- reason:
  - these are one of the strongest consistency assets already in the repo
- re-scope:
  - invariants should point at shell / beat / target-set / secret dependencies

## 8. Play Runtime

### `rpg_backend/play/service.py`
- status: `keep`
- reason:
  - session lifecycle, persistence, traces, and diagnostics are core architecture
- re-scope:
  - `relationship_drama` path becomes primary

### `rpg_backend/play/runtime.py`
- status: `re-scope`
- reason:
  - current file mixes general runtime helpers with civic-specific semantics
- target:
  - relationship runtime branch should dominate
  - civic helpers should shrink toward legacy-only use

### `rpg_backend/play/relationship_runtime.py`
- status: `keep`
- reason:
  - this is the consolidation target for the new runtime semantics

## 9. Benchmark / Judge / Trace Validation

### `rpg_backend/benchmark/*`
- status: `keep`
- reason:
  - diagnostics route shape and summary structure are core assets

### benchmark runners under `tools/play_benchmarks/*`
- status: `keep`
- reason:
  - real artifact generation and trace summarization are critical advantages
- re-scope:
  - personas and judge dimensions should be rewritten for relationship drama

## 10. Character / Portrait / Retrieval

### `rpg_backend/roster/*`
- status: `keep`
- reason:
  - strongest candidate base for character IP registry

### `rpg_backend/portraits/*`
- status: `keep`
- reason:
  - portrait generation and asset tracking should become registry support, not runtime dependency

### `rpg_backend/character_knowledge/*`
- status: `re-scope`
- reason:
  - should evolve into graph/knowledge retrieval for characters, relationships, secrets, and dramatic events

## Legacy Areas To Delete Gradually

These should not be expanded and should be removed once migration checkpoints pass:

- civic shell-specific prompt assumptions
- public-pressure-first beat semantics
- old affordance tags as primary gameplay language
- closeout/profile guidance that only makes sense for institutional crisis stories
