# RPG Demo Agent Guide

## Project Purpose
- Build a stable, testable **LLM executable narrative** FastAPI demo.
- Keep the runtime observable and debuggable:
- token/cost visibility via `StepResponse.cost` and `llm_usage_logs`
- replayability via `/sessions/{id}/end` + `/sessions/{id}/replay`
- snapshot + rollback via `/sessions/{id}/snapshot` + `/sessions/{id}/rollback`
- concurrency-safe budget handling via atomic `UPDATE ... WHERE token_budget_remaining >= ...` patterns in step flow

## Non-Goals (Current Scope)
- No large refactors.
- Do not redesign response schemas or endpoint shapes.
- Do not replace the existing non-story (free-form) happy path.
- Do not bypass migrations for schema changes.

## Invariants / Must Not Break
- Tests-first: add or update tests before changing behavior-critical paths.
- Preserve existing API contract compatibility (`/sessions`, `/sessions/{id}`, `/sessions/{id}/step`, `/stories/*`, replay/snapshot endpoints).
- Preserve non-story step flow behavior and budget semantics.
- Keep token budget accounting deterministic per step:
- reserve preflight budget first
- log LLM usage with a single `step_id` across classify/generate
- settle to actual usage with guarded update
- Keep replay generation deterministic and idempotent (same session state -> same report JSON).
- Any DB schema change must include an Alembic migration and pass migration smoke tests.

## Run Server / Tests
- Start API:
- `uvicorn app.main:app --reload`
- Required test commands:
- `python -m pytest -q`
- `python -m pytest -q client/tests`

## Architecture Map (Where To Change Code)
- App bootstrap / router wiring:
- `app/main.py`
- Session API + core runtime:
- `app/modules/session/router.py`
- `app/modules/session/schemas.py`
- `app/modules/session/service.py`
- Action compiler (player input -> whitelist/fallback):
- `app/modules/session/action_compiler.py`
- LLM runtime, usage logging, provider fallback:
- `app/modules/llm/adapter.py`
- `app/modules/llm/prompts.py`
- `app/modules/llm/providers/fake.py`
- Replay report generation:
- `app/modules/replay/engine.py`
- Narrative emotion/policy injection:
- `app/modules/narrative/emotion_state.py`
- `app/modules/narrative/behavior_policy.py`
- `app/modules/narrative/prompt_builder.py`
- Story Pack API (validate/store/fetch/publish):
- `app/modules/story/router.py`
- Data models + DB session:
- `app/db/models.py`
- `app/db/session.py`
- Migrations:
- `app/db/migrations/versions/0001_init.py`
- `app/db/migrations/versions/0002_step_id_accounting.py`
- `app/db/migrations/versions/0003_action_compiler_logging.py`
- `app/db/migrations/versions/0004_stories_table.py`
- `app/db/migrations/versions/0005_story_runtime_fields.py`
- High-signal tests:
- `tests/test_session_api.py`
- `tests/test_llm_integration.py`
- `tests/test_story_pack_api.py`
- `tests/test_story_engine_integration.py`
- `tests/test_replay_engine.py`
- `tests/test_session_step_integration.py`
- `tests/test_migrations.py`

## Token/Isolation, Compiler Logging, Replay Highlights (Observed)
- Token/accounting:
- preflight reserve and hard-stop on low budget in `step_session`
- step-scoped usage via `LLMUsageLog.step_id`
- `_sum_step_tokens(session_id, step_id)` isolates usage for final cost settlement
- action compiler + logging:
- `ActionCompiler` only allows `{study, work, rest, date, gift}`
- invalid/unmapped/low-confidence input uses deterministic fallback (`clarify` or safe fallback action)
- `ActionLog` stores `user_raw_input`, `proposed_action`, `final_action`, `fallback_used`, `fallback_reasons`, `action_confidence`, `key_decision`
- replay highlights:
- replay includes `key_decisions`, `fallback_summary`, and `story_path` (story runs)
- report is upserted once per session and remains stable across repeated `/end` + `/replay`
- emotion/policy injection:
- session step computes `emotion_state` and `behavior_policy` and injects both into the narrative prompt payload

## DB / Migration Rules
- Always add forward/backward migration files under `app/db/migrations/versions/` for schema updates.
- Keep model + migration alignment (`app/db/models.py` must match Alembic head).
- Verify with:
- `python -m alembic upgrade head`
- `python -m pytest -q tests/test_migrations.py`

## Current Planned Next Task: Story Runtime Wiring Checklist
- Goal: sessions pinned to `story_id` / `story_version` / `current_node_id`; step uses story node choices; LLM generates narration only.
- Checklist (based on current code/tests):
- [x] Story Pack CRUD + validation + publish flow exists (`/stories/validate`, `/stories`, `/stories/{story_id}`, `/stories/{story_id}/publish`).
- [x] Session creation can pin story pack (`story_id`, optional version, published-latest fallback).
- [x] Story step enforces node-local choice validity and advances session `current_node_id`.
- [x] `player_input` can be compiled to story action and mapped to node choice; fallback asks client to choose valid options.
- [x] Story path + key decisions are captured into replay via `ActionLog`.
- [x] Story-mode response contract is explicit: keep existing `node_id` behavior and add `story_node_id` for StoryPack node tracking.
- [x] Story-mode cost uses step-scoped `llm_usage_logs` when narration provider runs; budget-skip fallback returns zero-cost `{provider:"none", tokens_in:0, tokens_out:0, total_cost:0}` and logs `LLM_SKIPPED_BUDGET`.
