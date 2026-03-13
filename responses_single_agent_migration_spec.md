# Responses API 单 Agent 迁移 Spec

This file is the single implementation contract for the migration to Responses API + single-agent semantics.

## Current Contract

- Baseline is the current dirty branch state, including already-landed Author workflow deep-cleanup refactors.
- Public API response shapes remain stable for:
  - `POST /sessions`
  - `POST /sessions/{session_id}/step`
  - `POST /author/runs`
- Play runtime remains deterministic for settlement/outcome/effects.
- Author runtime remains LangGraph-orchestrated.

## Target Architecture

- Backend calls Responses API directly via `AsyncOpenAI.responses.create`.
- One shared Responses transport abstraction is used by both product rails.
- Single-agent semantics per rail:
  - Play rail: one `PlayAgent` with two tasks (`interpret_turn`, `render_resolved_turn`).
  - Author rail: one `AuthorAgent` with two tasks (`generate_overview`, `generate_outline`).
- Provider-side KV cache uses `previous_response_id` with persisted cursor channels.
- Worker runtime path is fully removed from active backend/frontend/docs semantics.

## Required Deletions

Completed deletions from active runtime/deploy paths:

- `rpg_backend/llm_worker/*`
- `rpg_backend/llm/worker_provider.py`
- `rpg_backend/llm/worker_client.py`
- `rpg_backend/llm/json_gateway.py`
- `rpg_backend/runtime_chains/*`
- `scripts/call_llm_worker.py`
- `deploy/k8s/rpg-llm-worker-*`
- `deploy/systemd/rpg-llm-worker*`

Additional cleanup completed:

- `rpg_backend/main.py` worker shutdown hook removed.
- `scripts/dev_stack.sh` reduced to postgres + backend + frontend only.
- Worker/route+narration active wording removed from active docs/frontend surfaces.

## Config Contract

Only active LLM config contract:

- `APP_RESPONSES_BASE_URL`
- `APP_RESPONSES_API_KEY`
- `APP_RESPONSES_MODEL`
- `APP_RESPONSES_TIMEOUT_SECONDS` (default `20.0`)
- `APP_RESPONSES_ENABLE_THINKING` (default `false`)

Enforced changes:

- Production bootstrap secret validation now requires `APP_RESPONSES_*` credentials/model.
- Removed active worker and multi-model route/narration/generator config usage.
- `.env.llm.example` updated to responses-only.

Dependency contract:

- Added `openai>=1.0.0,<2.0.0` to `pyproject.toml` for `AsyncOpenAI` transport.

## Data / Persistence Changes

New table added:

- `response_session_cursors`

Schema:

- `id`
- `scope_type`
- `scope_id`
- `channel`
- `model`
- `previous_response_id`
- `updated_at`

Uniqueness:

- `UNIQUE(scope_type, scope_id, channel)`

Channel contract:

- Play Mode: `play_agent`
- Author Mode: `author_overview`, `author_outline`

Behavior contract:

- Read cursor by `(scope_type, scope_id, channel)` and pass as `previous_response_id`.
- On provider cursor-invalid error, clear cursor and retry once without cursor.
- On success, persist returned `response.id`.

Migration:

- Added `alembic/versions/0006_response_session_cursors.py`.
- Migration normalizes legacy local table naming (`responsesessioncursor` -> `response_session_cursors`) when present.

## Backend Refactor Steps

Completed backend refactor modules:

- `rpg_backend/llm/response_parsing.py`
- `rpg_backend/llm/responses_transport.py`
- `rpg_backend/llm/response_sessions.py`
- `rpg_backend/llm/agents.py`

Factory unification:

- `rpg_backend/llm/factory.py` now builds a single `ResponsesAgentBundle` (`play_agent`, `author_agent`, model/mode).

Play rail unification:

- `RuntimeService` + router/narration/step engine now call `PlayAgent`.
- Text input path: `interpret_turn -> deterministic resolution -> render_resolved_turn`.
- Button input path: skip `interpret_turn`, run deterministic resolution + render only.
- Timeline/dev payload moved to single-agent diagnostics:
  - `agent_model`
  - `agent_mode`
  - `response_id`
  - `reasoning_summary` (optional)

Author rail unification:

- LangGraph topology retained.
- `generate_story_overview` and `generate_beat_outline` now call `AuthorAgent` tasks.
- Each graph attempt maps to one real Responses request.
- Structured outputs are prompt-enforced strict JSON and parsed/validated locally.
- `final_lint` failure still routes directly to `workflow_failed`.

Readiness/observability naming:

- Gateway/readiness semantics renamed from `worker` to `responses`.
- Admin observability contracts and aggregation reflect `responses` mode.

## Frontend / Docs Cleanup

Frontend/docs updated to match single-agent responses architecture:

- Updated:
  - `README.md`
  - `docs/architecture.md`
  - `docs/runtime_status.md`
  - `docs/deployment_probes.md`
  - `docs/oncall_sop.md`
  - `frontend/README.md`
  - `frontend/scripts/author_play_release_gate.mjs`
  - `frontend_agent_contract.md`
- Removed active wording for:
  - backend->worker chain
  - route model + narration model split semantics
  - multi-agent current-state claims

## Test Plan

Coverage implemented/aligned for migration:

1. Responses transport/parsing/session behavior
- Response output text extraction
- Reasoning summary extraction
- Usage extraction
- `previous_response_id` passthrough
- `enable_thinking` body passthrough
- Cursor invalidation clear + single fallback retry

2. Play mode
- Text path and button path behavior
- Public response shape stability
- Timeline diagnostics now single-agent
- Session cursor progression through `play_agent`

3. Author mode
- Graph topology stability
- One Responses call per overview/outline attempt
- Retry semantics (`3 attempts / 20s`) preserved
- `final_lint -> workflow_failed` preserved
- Cursor channels for `author_overview` and `author_outline`

4. Drift guard
- No active `WorkerProvider`/`llm_worker` dependency in runtime/docs/frontend
- No active `route_model` / `narration_model` semantics
- No active repair-branch semantics in runtime/docs code path

## Implementation Log

### 2026-03-13 / Stage A: Transport + Agent Boundary

- Added Responses transport/parsing/session modules and shared `PlayAgent`/`AuthorAgent` abstractions.
- Unified LLM factory to one responses bundle and mode.
- Removed worker client/provider/json gateway runtime dependencies.

### 2026-03-13 / Stage B: Play Runtime Unification

- Rewired play routing/narration flows to `PlayAgent` tasks.
- Preserved deterministic settlement contract.
- Migrated step telemetry/timeline to single-agent diagnostics (`agent_*`, `response_id`, `reasoning_summary`).

### 2026-03-13 / Stage C: Author Runtime Unification

- Rewired overview/outline LLM nodes to `AuthorAgent` while preserving LangGraph workflow topology.
- Kept deterministic `plan_beats/materialize/lint/normalize` nodes unchanged.
- Preserved final-lint terminal failure semantics.

### 2026-03-13 / Stage D: Cursor Persistence + Migration

- Added `ResponseSessionCursor` entity/repository and call wrapper with invalid-cursor one-time fallback.
- Added Alembic revision `0006_response_session_cursors` with legacy naming normalization support.

### 2026-03-13 / Stage E: Readiness/Observability + Deletion Cleanup

- Renamed gateway/readiness semantics to `responses` throughout observability APIs/repositories/readiness checks.
- Removed worker deploy scripts/manifests and startup hooks.
- Reduced dev stack to backend + frontend + postgres.

### 2026-03-13 / Stage F: Final Drift Cleanup

- Updated `docs/oncall_sop.md` from worker-centric runbook to responses-centric runbook.
- Updated `docs/db_migration_runbook.md` from backend/worker rollout wording to backend-only + `APP_RESPONSES_*` secret checks.
- Updated worker-startup/worker-route tests to migration-aligned guards.
- Updated alert snapshot test fixtures from worker naming to responses naming.
- Updated docs consistency guard test markers to responses-era security/runtime markers.
- Added missing `openai` dependency declaration in `pyproject.toml`.

## Verification Run

Commands executed and recorded as run:

1. `pytest -q tests/api/test_startup_schema_guard.py tests/llm/test_worker_route_cutover.py tests/test_emit_runtime_alerts.py`
- Result: pass

2. `pytest -q tests/llm/test_response_parsing.py tests/llm/test_responses_transport.py tests/llm/test_response_sessions.py tests/llm/test_agents.py`
- Result: pass

3. `pytest -q tests/api/test_sessions_api.py tests/runtime/test_runtime_openai_strict.py tests/runtime/test_router_context.py tests/test_sample_story_pacing.py`
- Result: pass

4. `pytest -q tests/api/test_admin_sessions_api.py tests/api/test_readiness_api.py`
- Result: pass

5. `pytest -q tests/test_author_workflow_architecture.py tests/test_author_workflow_beat_generation.py tests/test_author_workflow_validators.py tests/api/test_author_runs_api.py`
- Result: pass

6. `pytest -q tests/storage/test_migrations.py`
- Result: pass

7. `rg -n "WorkerProvider" rpg_backend frontend docs README.md scripts --glob '!docs/archive/**' || true`
- Result: no matches

8. `rg -n "llm_worker" rpg_backend frontend docs README.md scripts --glob '!docs/archive/**' || true`
- Result: no matches

9. `rg -n "route_model" rpg_backend frontend docs README.md scripts --glob '!docs/archive/**' || true`
- Result: no matches

10. `rg -n "narration_model" rpg_backend frontend docs README.md scripts --glob '!docs/archive/**' || true`
- Result: no matches

11. `rg -n "repair_pack" rpg_backend frontend docs README.md scripts --glob '!docs/archive/**' || true`
- Result: no matches

12. `npm run build` (cwd: `frontend`)
- Result: pass (Vite production build completed)

13. `PGPASSWORD=rpg_local dropdb --if-exists -h 127.0.0.1 -p 8132 -U rpg_local rpg_test && PGPASSWORD=rpg_local createdb -h 127.0.0.1 -p 8132 -U rpg_local rpg_test`
- Result: failed (`dropdb` command not found in environment)

14. `which psql || true`
- Result: `psql not found`

15. `pytest -q tests/test_docs_consistency.py`
- Result: pass

## Remaining Debt

- Environment tooling gap: this execution environment does not include Postgres CLI (`dropdb`/`psql`), so explicit manual `rpg_test` DB reset could not be performed here.
- Mitigation in this run: migration correctness was validated via `tests/storage/test_migrations.py` and all targeted suites passed on current DB test fixture setup.
