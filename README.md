# RPG Backend (Strict Runtime)

Backend-first interactive narrative RPG service with OpenAI-only runtime behavior:
- `openai` provider uses quality-first failfast for LLM route/narration failures.
- Preconditions never hard-block progression.
- When success/partial cannot apply, runtime must execute `fail_forward`.
- Story DSL is strategy-aware:
  - every scene enforces a strategy triangle (`fast_dirty`, `steady_slow`, `political_safe_resource_heavy`)
  - fixed pressure tracks (`public_trust`, `resource_stress`, `coordination_noise`) are repaid in late beats
  - NPC red lines are explicit and surfaced as stance updates during play.

## Stack
- Python 3.11+
- FastAPI + Pydantic v2
- SQLModel + PostgreSQL (SQLite remains supported for local dev only)
- pytest

## Architecture
Code is split by responsibilities:
- `rpg_backend/domain`: Story Pack DSL schema + linter
- `rpg_backend/generator`: deterministic story generator (`pipeline/candidate_executor/result_builder/errors` + `planner/builder/prompt_compiler`)
- `rpg_backend/runtime`: Pass A routing + Pass B deterministic resolution + narration composition
- `rpg_backend/llm`: worker transport abstraction (`WorkerProvider`)
- `rpg_backend/storage`: SQLModel entities + migration guard (`engine/migrations/models`)
- `rpg_backend/infrastructure/repositories`: persistence adapters only (`*_async.py`); they no longer own commit/rollback
- `rpg_backend/api`: REST API (`/stories|/sessions|/admin`) + route registry/paths (`router_registry.py`, `route_paths.py`)
- `rpg_backend/application`: orchestration + transaction ownership (`story_authoring`, `play_sessions`, `session_step`, `admin_console`, `readiness`)
- `rpg_backend/observability/readiness_core.py`: shared readiness core used by backend + worker (payload builder/config validator/async TTL probe cache)

Internal import policy:
- use explicit module imports (for example `rpg_backend.generator.pipeline`) instead of wrapper/facade paths.
- do not import `rpg_backend.storage.repositories.*` (removed; no compatibility path).
- do not import `rpg_backend.runtime.session_step.*` (removed; use `rpg_backend.application.session_step.*`).

Route path policy:
- backend business routes and probe paths must come from `rpg_backend.api.route_paths`.
- worker task routes must come from `rpg_backend.llm_worker.route_paths`.
- tests/scripts should import the same constants/helpers (no ad-hoc hardcoded route literals).
- `LEGACY_V2_*` route constants are removed from production code; `/v2/*` probes live in tests only.

Dual-agent monorepo collaboration:
- frontend workspace lives under `frontend/` (Antigravity-owned), backend remains under `rpg_backend/` (Codex-owned).
- backend/route schema changes must update `contracts/openapi/backend.openapi.json` first.
- frontend consumes generated SDK from `frontend/src/shared/api/generated/backend-sdk.ts` (no manual protocol guessing).
- detailed workflow: `docs/agent_collab_workflow.md`.

Runtime architecture source of truth:
- `docs/architecture.md`
- `docs/runtime_status.md`
- Prompt authoring review baseline:
  - `docs/prompt_authoring_structure.md`

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cd frontend && npm install && cd ..
./scripts/dev_stack.sh up
```

Common local dev commands:

```bash
./scripts/dev_stack.sh status
./scripts/dev_stack.sh ready
./scripts/dev_stack.sh logs backend
./scripts/dev_stack.sh resetdb
./scripts/dev_stack.sh down
```

Notes:
- `./scripts/dev_stack.sh up` runs `python scripts/db_migrate.py upgrade head` automatically before starting worker, backend, and frontend.
- If you change `.env` admin bootstrap credentials, run `./scripts/dev_stack.sh restart` or `./scripts/dev_stack.sh resetdb` so backend restarts with the current config.
- `resetdb` is for local SQLite only; it refuses to run against non-local or non-SQLite database URLs.

Readiness check (DB + LLM config + cached LLM probe):

```bash
./scripts/dev_stack.sh ready
curl http://127.0.0.1:8000/ready
```

Force-refresh the LLM readiness probe (bypass cache):

```bash
curl "http://127.0.0.1:8000/ready?refresh=true"
```

## Configuration
Environment variables use `APP_` prefix.

- `APP_DATABASE_URL` default: `sqlite:///./app.db`
- `APP_DB_ASYNC_POOL_SIZE` default: `20`
- `APP_DB_ASYNC_MAX_OVERFLOW` default: `20`
- `APP_DB_ASYNC_POOL_TIMEOUT_SECONDS` default: `30`
- `APP_ROUTING_CONFIDENCE_THRESHOLD` default: `0.55`
- `APP_LLM_OPENAI_BASE_URL` required
- `APP_LLM_OPENAI_API_KEY` required
- `APP_LLM_OPENAI_MODEL` optional global fallback model
- `APP_LLM_OPENAI_ROUTE_MODEL` optional route model (falls back to `APP_LLM_OPENAI_MODEL`)
- `APP_LLM_OPENAI_NARRATION_MODEL` optional narration model (falls back to `APP_LLM_OPENAI_MODEL`)
- `APP_LLM_OPENAI_GENERATOR_MODEL` optional generator model (falls back to `APP_LLM_OPENAI_MODEL`)
- `APP_LLM_OPENAI_TIMEOUT_SECONDS` default: `20`
- `APP_LLM_OPENAI_ROUTE_MAX_RETRIES` default: `3` (max 3)
- `APP_LLM_OPENAI_NARRATION_MAX_RETRIES` default: `1`
- `APP_LLM_OPENAI_TEMPERATURE_ROUTE` default: `0.1`
- `APP_LLM_OPENAI_TEMPERATURE_NARRATION` default: `0.4`
- `APP_LLM_OPENAI_GENERATOR_TEMPERATURE` default: `0.15`
- `APP_LLM_OPENAI_GENERATOR_MAX_RETRIES` default: `3` (max 3)
- `APP_GENERATOR_CANDIDATE_PARALLELISM` default: `1` (per-attempt candidate fanout during story generation)
- `APP_LLM_WORKER_BASE_URL` required (backend only talks to worker)
- `APP_LLM_WORKER_TIMEOUT_SECONDS` default: `20`
- `APP_LLM_WORKER_CONNECT_TIMEOUT_SECONDS` default: `5`
- `APP_LLM_WORKER_MAX_CONNECTIONS` default: `100`
- `APP_LLM_WORKER_MAX_KEEPALIVE_CONNECTIONS` default: `20`
- `APP_LLM_WORKER_HTTP2_ENABLED` default: `false`
- `APP_LLM_WORKER_UPSTREAM_API_FORMAT` default: `chat_completions` (`chat_completions|responses`)
- `APP_LLM_WORKER_MODEL_LIMITS_JSON` default: `{}` (per-model rpm/tpm bucket overrides)
- `APP_LLM_WORKER_DEFAULT_RPM` default: `300`
- `APP_LLM_WORKER_DEFAULT_TPM` default: `600000`
- `APP_LLM_WORKER_QUEUE_MAX_SIZE` default: `1024`
- `APP_LLM_WORKER_QUEUE_WAIT_TIMEOUT_SECONDS` default: `8`
- `APP_LLM_WORKER_QUEUE_WEIGHTS_JSON` default: `{"route_intent":5,"render_narration":3,"json_object":2}`
- `APP_LLM_WORKER_EXECUTOR_CONCURRENCY` default: `16`
- `APP_LLM_WORKER_TOKEN_EST_ROUTE_OUTPUT` default: `96`
- `APP_LLM_WORKER_TOKEN_EST_NARRATION_OUTPUT` default: `192`
- `APP_LLM_WORKER_TOKEN_EST_JSON_OUTPUT` default: `256`
- `APP_LLM_WORKER_EXECUTOR_CONCURRENCY` is the single worker execution concurrency control
- `APP_OBS_LOG_LEVEL` default: `INFO`
- `APP_OBS_REQUEST_ID_HEADER` default: `X-Request-ID`
- `APP_OBS_REDACT_INPUT_TEXT` default: `true`
- `APP_OBS_ALERT_WEBHOOK_URL` optional webhook endpoint for runtime alert pushes
- `APP_OBS_ALERT_WINDOW_SECONDS` default: `300`
- `APP_OBS_ALERT_BUCKET_MIN_COUNT` default: `3`
- `APP_OBS_ALERT_BUCKET_MIN_SHARE` default: `0.10`
- `APP_OBS_ALERT_GLOBAL_ERROR_RATE` default: `0.05`
- `APP_OBS_ALERT_COOLDOWN_SECONDS` default: `900`
- `APP_OBS_ALERT_HTTP_5XX_RATE` default: `0.05`
- `APP_OBS_ALERT_HTTP_5XX_MIN_COUNT` default: `10`
- `APP_OBS_ALERT_READY_FAIL_STREAK` default: `2`
- `APP_OBS_ALERT_WORKER_FAIL_RATE` default: `0.05`
- `APP_OBS_ALERT_WORKER_FAIL_MIN_COUNT` default: `20`
- `APP_OBS_ALERT_LLM_CALL_P95_MS` default: `3000`
- `APP_OBS_ALERT_LLM_CALL_MIN_COUNT` default: `30`
- `APP_READY_LLM_PROBE_ENABLED` default: `true`
- `APP_READY_LLM_PROBE_CACHE_TTL_SECONDS` default: `30`
- `APP_READY_LLM_PROBE_TIMEOUT_SECONDS` default: `5`

Production DB policy:
- production/staging should use external PostgreSQL via `APP_DATABASE_URL` (for example `postgresql+psycopg://...`).
- backend/worker startup is strict on schema revision and will fail when DB revision is not at Alembic head.
- runtime hot paths use async SQLAlchemy/SQLModel sessions (`AsyncSession`) for API, worker quota, readiness, and observability writes.

Production secret requirements (`APP_ENV=prod`):
- `APP_DATABASE_URL` must be non-sqlite.
- `APP_LLM_OPENAI_BASE_URL`, `APP_LLM_OPENAI_API_KEY`, and at least one model key must be set.
- `APP_OBS_ALERT_WEBHOOK_URL` must be set.
- `APP_AUTH_JWT_SECRET` must be set (not default dev value).
- `APP_ADMIN_BOOTSTRAP_EMAIL`, `APP_ADMIN_BOOTSTRAP_PASSWORD` must be set.
- `APP_INTERNAL_WORKER_TOKEN` must be set.

## Database Migration And Rollback

Manual migration commands:

```bash
python scripts/db_migrate.py current
python scripts/db_migrate.py heads
python scripts/db_migrate.py upgrade head
python scripts/db_migrate.py downgrade <revision>
```

Kubernetes helper wrappers:

```bash
./scripts/k8s/k8s_db_migrate_manual.sh head
./scripts/k8s/k8s_verify_rollout.sh
./scripts/k8s/k8s_rollback_last.sh
```

Release order:
1. run migration (`upgrade head`)
2. rollout backend/worker
3. verify `/health` + `/ready`
4. rollback app (and downgrade DB only if explicitly required)

OpenAI model resolution:
- `route_model = APP_LLM_OPENAI_ROUTE_MODEL or APP_LLM_OPENAI_MODEL`
- `narration_model = APP_LLM_OPENAI_NARRATION_MODEL or APP_LLM_OPENAI_MODEL`
- `generator_model = APP_LLM_OPENAI_GENERATOR_MODEL or APP_LLM_OPENAI_MODEL`
- when `APP_LLM_OPENAI_MODEL` is set, any unset specialized model inherits it automatically.
- when `APP_LLM_OPENAI_MODEL` is empty, set route, narration, and generator models explicitly for full author + play coverage.
- backend never calls upstream LLM directly; worker handles upstream protocol (`chat_completions` or `responses`).

LLM worker bootstrap:

```bash
cp .env.llm.example .env
# then fill APP_LLM_OPENAI_BASE_URL / APP_LLM_OPENAI_API_KEY
# and backend worker target:
# APP_LLM_WORKER_BASE_URL=http://127.0.0.1:8100
# APP_INTERNAL_WORKER_TOKEN=<shared-secret>
# and at least one model path:
# - single model: APP_LLM_OPENAI_MODEL
# - route only: APP_LLM_OPENAI_ROUTE_MODEL
# - split models: APP_LLM_OPENAI_ROUTE_MODEL + APP_LLM_OPENAI_NARRATION_MODEL
```

Minimal OpenAI-compatible probe (JSON mode):

```bash
curl -sS "${APP_LLM_OPENAI_BASE_URL%/}/v1/chat/completions" \
  -H "Authorization: Bearer ${APP_LLM_OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${APP_LLM_OPENAI_ROUTE_MODEL:-${APP_LLM_OPENAI_NARRATION_MODEL:-$APP_LLM_OPENAI_MODEL}}\",
    \"temperature\": 0.1,
    \"response_format\": {\"type\": \"json_object\"},
    \"messages\": [
      {\"role\": \"system\", \"content\": \"Return JSON only with key ok.\"},
      {\"role\": \"user\", \"content\": \"Return exactly: {\\\"ok\\\":true}\"}
    ]
  }"
```

Failure modes are gate-controlled:
- if provider config is invalid, session create/step returns `503`.
- if OpenAI route fails (including low confidence or invalid move), step returns `503` with structured detail.
- if OpenAI narration fails, step returns `503` with structured detail.
- each successful step includes `recognized.route_source` (`llm`, `button`, `button_fallback`) for observability.
- text routing suppresses `global.help_me_progress` unless player intent is explicit help/stuck language.

Readiness endpoint contract:
- `/health` is a lightweight liveness probe and always returns `200 {"status":"ok"}` when process is up.
- `/ready` is a strict readiness probe:
  - checks DB connectivity (`SELECT 1`)
  - checks worker config completeness
  - probes worker `/ready` (worker performs upstream probe with cache)
- `/ready` returns:
  - `200` with `status=ready` when all checks pass
  - `503` with `status=not_ready` and detailed check diagnostics when any critical check fails
- backend and worker readiness share one implementation core for config checks + probe cache semantics.
- backend readiness checks are async-only (`run_readiness_checks_async`); sync compatibility wrappers are removed.
- LLM readiness probe is cached in-process by TTL (`APP_READY_LLM_PROBE_CACHE_TTL_SECONDS`) to control token/latency overhead.
- Deployment probe templates (Kubernetes + systemd process manager):
  - [docs/deployment_probes.md](/Users/lishehao/Desktop/Project/RPG_Demo/docs/deployment_probes.md)
  - Kubernetes manifests:
    - `deploy/k8s/rpg-backend-deployment.yaml`
    - `deploy/k8s/rpg-backend-configmap.yaml`
    - `deploy/k8s/rpg-backend-secret.example.yaml`
    - `deploy/k8s/rpg-llm-worker-deployment.yaml`
    - `deploy/k8s/rpg-llm-worker-service.yaml`
    - `deploy/k8s/rpg-llm-worker-hpa.yaml`
    - `deploy/k8s/rpg-observability-alerts-cronjob.yaml`
  - systemd units:
    - `deploy/systemd/rpg-backend.service`
    - `deploy/systemd/rpg-backend-readiness.service`
    - `deploy/systemd/rpg-backend-readiness.timer`
    - `deploy/systemd/rpg-llm-worker.service`
    - `deploy/systemd/rpg-llm-worker-readiness.service`
    - `deploy/systemd/rpg-llm-worker-readiness.timer`
    - `deploy/systemd/rpg-alert-emitter.service`
    - `deploy/systemd/rpg-alert-emitter.timer`

LLM worker mode:
- start worker: `uvicorn rpg_backend.llm_worker.main:app --host 0.0.0.0 --port 8100`
- backend target: set `APP_LLM_WORKER_BASE_URL=http://127.0.0.1:8100`
- worker task API (hard cut): `POST /internal/llm/tasks/route-intent`, `POST /internal/llm/tasks/render-narration`, `POST /internal/llm/tasks/json-object`
- worker task API requires header: `X-Internal-Worker-Token: ${APP_INTERNAL_WORKER_TOKEN}`
- worker probes stay unversioned: `GET /health`, `GET /ready`
- legacy `/v2/llm/tasks/*` is removed (no alias/redirect compatibility)
- worker debug CLI: `python scripts/call_llm_worker.py --task probe`

## Story Pack and Linter
Global move IDs (required in every scene):
- `global.clarify`
- `global.look`
- `global.help_me_progress`

StoryPack DSL (hard break, no backward compatibility):
- each move must include `strategy_style`.
- each pack must include `npc_profiles[]` with `{name, red_line, conflict_tags}`.
- each scene must include at least one move from each strategy style (triangle hard constraint).
- `inspect_relic` is banned and fails lint.

Sample pack:
- `sample_data/story_pack_v1.json`
- 4 beats
- 15 scenes
- 4 NPCs, each appears at least twice
- branch converges within 1 step (`sc2 -> sc3/sc4 -> sc5`)

Run linter:

```bash
python scripts/lint_story_pack.py sample_data/story_pack_v1.json
```

Regenerate status:
- Generator uses `build -> lint -> regenerate`.
- When lint fails, it regenerates the whole pack with derived seeds (max 3 regenerates / 4 total attempts).
- Prompt mode regenerates by rerunning `PromptCompiler + build + lint` each attempt.
- Internal implementation split:
  - `GeneratorPipeline`: validation + compile/plan + regenerate orchestration
  - `candidate_executor`: candidate parallel execution and winner/best selection
  - `result_builder`: attempt history and response assembly
  - `errors`: centralized `GeneratorBuildError` construction

## Author / Play Product Shape

The frontend is now split into two independent product rails:

- `Author Mode`: `/author/stories`, `/author/stories/:storyId`
- `Play Mode`: `/play/library`, `/play/sessions/:sessionId`

Author generates and publishes stories into the DB. Play consumes only published versions to start sessions.

## API Flow (curl)

All business/admin routes require Bearer token.
Login first:

```bash
AUTH_TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${APP_ADMIN_BOOTSTRAP_EMAIL}\",\"password\":\"${APP_ADMIN_BOOTSTRAP_PASSWORD}\"}" | jq -r '.access_token')
AUTH_HEADER="Authorization: Bearer ${AUTH_TOKEN}"
```

### 1) Create draft story

```bash
curl -sS -X POST http://127.0.0.1:8000/stories \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg title 'City Signal Draft' --argjson pack "$(cat sample_data/story_pack_v1.json)" '{title:$title, pack_json:$pack}')"
```

### 2) Publish story version

```bash
curl -sS -X POST http://127.0.0.1:8000/stories/{story_id}/publish \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### 3) List story supply for Author / Play

```bash
curl -sS "http://127.0.0.1:8000/stories" \
  -H "${AUTH_HEADER}"
```

### 4) Read draft detail

```bash
curl -sS "http://127.0.0.1:8000/stories/{story_id}/draft" \
  -H "${AUTH_HEADER}"
```

### 5) Read published raw pack

```bash
curl -sS "http://127.0.0.1:8000/stories/{story_id}?version=1" \
  -H "${AUTH_HEADER}"
```

### 5.5) Generate story

```bash
curl -sS -X POST http://127.0.0.1:8000/stories/generate \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt_text":"A city-wide signal breach where a burned-out systems engineer must stabilize a failing reactor while rival factions compete for control.",
    "seed_text":"A city-wide signal breach",
    "target_minutes":10,
    "npc_count":4,
    "variant_seed":"demo-seed-001",
    "candidate_parallelism":3,
    "generator_version":"v3.3",
    "palette_policy":"random",
    "publish":false
  }'
```

`publish=false` still creates a draft story and returns `story_id`; `version` stays `null`.
Set `publish=true` to create and publish in one request.
Generation mode selection:
- if `prompt_text` is provided (non-empty), generator runs in `prompt` mode.
- otherwise it runs in `seed` mode.
Prompt compile behavior (strict):
- Prompt mode uses a two-stage compile contract:
  - stage 1: outline (`StorySpecOutline`) with strict compact limits and unique beat titles
  - stage 2: full `StorySpec`
  - stage 3: one feedback-guided regeneration if stage 2 validation fails
- total compile budget is max 3 calls.
- no local truncation is applied; failures remain strict (`prompt_outline_invalid` / `prompt_spec_invalid`).
`/stories/generate` returns structured diagnostics under `generation`:
- `generation.mode` (`prompt|seed`)
- `generation.generator_version`, `generation.variant_seed`, `generation.palette_policy`
- `generation.attempts`, `generation.regenerate_count`, `generation.candidate_parallelism`
- `generation.compile.spec_hash` / `generation.compile.spec_summary` (prompt mode only)
- `generation.lint.errors` / `generation.lint.warnings`
- `generation.attempt_history[]` with winner candidate trace per attempt
- top-level `pack_hash` remains the stable hash for raw `pack_json`

Error responses are unified as:
- `{ "error": { "code", "message", "retryable", "request_id", "details" } }`

### 4) Create session

```bash
curl -sS -X POST http://127.0.0.1:8000/sessions \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d '{"story_id":"{story_id}","version":1}'
```

### 5) Step with text input

```bash
curl -sS -X POST http://127.0.0.1:8000/sessions/{session_id}/step \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d '{
    "client_action_id":"step-1",
    "input":{"type":"text","text":"@@@ random words"},
    "dev_mode":false
  }'
```

### 6) Step with button input

```bash
curl -sS -X POST http://127.0.0.1:8000/sessions/{session_id}/step \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d '{
    "client_action_id":"step-2",
    "input":{"type":"button","move_id":"global.clarify"},
    "dev_mode":true
  }'
```

### 7) Inspect session state

```bash
curl -sS "http://127.0.0.1:8000/sessions/{session_id}?dev_mode=true" \
  -H "${AUTH_HEADER}"
```

### 8) Simulate a playthrough transcript

```bash
python scripts/eval/simulate_playthrough.py \
  --provider openai \
  --base-url http://127.0.0.1:8000 \
  --story-id {story_id} \
  --version 1 \
  --max-steps 20 \
  --output output/transcript.json
```

Transcript entries include:
- `scene_id`
- `recognized`
- `resolution`
- `narration_text`
- `beat_progress`

You can also run local raw-pack simulation without API:

```bash
python scripts/eval/simulate_playthrough.py \
  --pack-file sample_data/story_pack_v1.json \
  --provider openai \
  --strategy mixed \
  --strategy-seed 12345 \
  --pack-hash local-pack-hash \
  --generator-version v3.2 \
  --variant-seed replay-seed-1 \
  --max-steps 20
```

### 9) Evaluate generator quality (manual/nightly)

```bash
python scripts/eval/evaluate_generator.py \
  --seed-text "A city-wide signal breach" \
  --runs 10 \
  --strategies 5 \
  --variant-seed "nightly-seed" \
  --palette-policy balanced \
  --target-minutes 10 \
  --npc-count 4 \
  --output reports/generator_eval.json
```

This writes aggregate metrics:
- `completion_rate`
- `avg_steps`
- `meaningful_accept_rate`
- `palette_diversity`

For replay:
- each run stores pack snapshots under `reports/packs/{pack_hash}.json`
- report includes `pack_hash`, `generator_version`, `variant_seed`, `strategy_seed`, `transcript_digest`

### 10) LLM gate evaluation (openai-only, strict)

```bash
python scripts/eval/evaluate_llm_gate.py \
  --pack-file sample_data/story_pack_v1.json \
  --runs 50 \
  --strategy mixed \
  --output reports/llm_gate_eval.json
```

Gate expectations:
- `completion_rate == 1.0`
- `meaningful_accept_rate >= 0.90`
- `llm_route_success_rate >= 0.80`
- `step_error_rate == 0.0`

Additional observability metrics:
- `llm_route_success_rate`
- `step_error_rate`

Connectivity precheck:
- before full evaluation, the script resolves the OpenAI host and runs one minimal route probe.
- if precheck fails, the script exits non-zero and writes `precheck` diagnostics in the report (`dns_unreachable` / `connect_error` / `auth_error` / etc).
- this prevents network/config failures from appearing as a false green gate.
- `precheck.error_type=unsupported_chat_completions_api` means your endpoint does not support chat completions API; switch to a compatible endpoint.

Restricted environment option:
- default is strict fail-fast.
- if you are intentionally running inside a network-restricted sandbox, add `--allow-precheck-fail`.
- this marks `gate.evaluation_status` as `inconclusive` and exits 0 for diagnostics-only runs.

Example (restricted sandbox):

```bash
python scripts/eval/evaluate_llm_gate.py \
  --pack-file sample_data/story_pack_v1.json \
  --runs 50 \
  --strategy mixed \
  --allow-precheck-fail \
  --output reports/llm_gate_eval.json
```

Gate status field:
- `gate.evaluation_status = passed | failed | inconclusive`
- `gate.passed = true` only when fully evaluated and all gate thresholds are satisfied.

### 11) Full Eval: LLM Prompt -> Story Pack (Hard Gate)

Run full prompt-driven story generation evaluation:

```bash
python scripts/eval/evaluate_llm_story_generation.py \
  --suite-file eval_data/prompt_suite_v1.json \
  --runs-per-prompt 3 \
  --strategies mixed,text_noise,button_random \
  --max-steps 20 \
  --output reports/llm_story_generation_eval.json \
  --packs-dir reports/packs_llm \
  --artifacts-dir reports/llm_story_eval_artifacts \
  --strict true
```

What it evaluates:
- prompt mode generation only (`GeneratorPipeline.run(prompt_text=...)`)
- playability replay using `provider=openai` (strict runtime behavior)
- subjective quality via LLM Judge (chat completions JSON mode)

Hard gate thresholds:
- `generation_success_rate == 1.0`
- `pack_lint_success_rate == 1.0`
- `completion_rate == 1.0`
- `avg_steps in [14, 16]`
- `meaningful_accept_rate >= 0.90`
- `llm_route_success_rate >= 0.80`
- `step_error_rate == 0.0`
- `judge_overall_avg >= 7.5`
- `judge_prompt_fidelity_avg >= 7.0`
- `case_overall_score_min >= 6.0`

Additional diagnostics (observe/alert, not hard gate yet):
- `global_help_route_rate`
- `non_global_text_route_rate`
- `strategy_triangle_coverage_rate`
- `pressure_recoil_trigger_rate`
- `npc_stance_mentions_per_run_avg`
- `duplicate_beat_title_run_count`
- `banned_move_hit_count`
- `fun_score_avg`
- `fun_score_case_min`
- `judge_playability_avg`
- `judge_choice_impact_avg`
- `judge_tension_curve_avg`

Outputs:
- report: `reports/llm_story_generation_eval.json`
- generated packs: `reports/packs_llm/{pack_hash}.json`
- transcript summaries: `reports/llm_story_eval_artifacts/{case_id}/run{n}_{strategy}.json`
- report diagnostics include:
  - `metrics.generation_failure_breakdown` (by `error_code`)
  - `metrics.prompt_spec_invalid_field_counts` (field-level counts such as `premise/stakes/tone/title`)

Precheck behavior:
- fail-fast before full run: DNS resolution + minimal `PromptCompiler.compile` probe
- precheck failure marks gate failed and (under `--strict true`) returns non-zero exit code
- if `prompt_spec_invalid` appears frequently, inspect `prompt_spec_invalid_field_counts` first.

### 12) Fun Focus Eval (12x2, gate unchanged)

Run fun-priority readout while keeping the same full hard gate:

```bash
python scripts/eval/evaluate_llm_story_generation.py \
  --profile fun_focus \
  --output reports/llm_story_generation_eval_fun_12x2.json
```

`fun_focus` profile defaults:
- `suite_file=eval_data/prompt_suite_fun_v1.json` (fixed 12 prompts)
- `runs_per_prompt=2`
- `strategies=mixed`
- `max_steps=20`
- `strict=true`

Fun score formula:
- `fun_score = 0.40*overall + 0.25*playability + 0.25*choice_impact + 0.10*tension_curve`

Report additions:
- `metrics.fun_score_avg`
- `metrics.fun_score_case_min`
- `metrics.judge_playability_avg`
- `metrics.judge_choice_impact_avg`
- `metrics.judge_tension_curve_avg`
- `fun_focus.formula`
- `fun_focus.threshold_hints` (diagnostic only)
- `fun_focus.warnings`

Important:
- this profile changes reading focus, not pass/fail semantics.
- full gate and exit-code behavior remain unchanged.

## Idempotency Contract
`POST /sessions/{session_id}/step` uses `client_action_id`.

If the same `client_action_id` is submitted again for the same session:
- returns **HTTP 200**
- returns the **exact first response payload**

Step input tolerance contract:
- malformed action shape in valid JSON (missing `input`, missing `move_id`, invalid `input.type`) is normalized and executed with global fallback moves.
- successful step payload is strict typed:
  - `recognized`: `{interpreted_intent, move_id, confidence, route_source, llm_duration_ms?, llm_gateway_mode?}`
  - `resolution`: `{result, costs_summary, consequences_summary}`
  - `ui`: `{moves:[{move_id,label,risk_hint}], input_hint}`
- `debug` field is returned only when `dev_mode=true`; omitted otherwise.
- invalid session state still returns system errors (`404`/`409`).
- concurrent write conflict (different action racing on stale turn) returns `409` with retry detail:
  - `error_code`: `session_conflict_retry`
  - `message`: `session advanced by another action; retry with new client_action_id`
  - `expected_turn_index` / `actual_turn_index`
  - `retryable`: `true`
- strict provider (`openai`) may return `503` on LLM runtime failures with detail:
  - `error_code`: `llm_route_failed | llm_route_low_confidence | llm_route_invalid_move | llm_narration_failed`
  - `stage`: `route | narration`
  - `message`: failure detail
  - `provider`: `openai`
- invalid JSON syntax can still return framework-level parse errors.
- every API response includes `X-Request-ID` for trace correlation.

## Admin Diagnostics (Session Trace + Feedback)
Admin diagnostics endpoints are exposed under `/admin` and require Bearer auth.
Use only in local/internal environments.

### 0) Admin user info

```bash
curl -sS "http://127.0.0.1:8000/admin/users?limit=100" \
  -H "${AUTH_HEADER}"
```

```bash
curl -sS "http://127.0.0.1:8000/admin/users/{user_id}" \
  -H "${AUTH_HEADER}"
```

### 1) Timeline replay

```bash
curl -sS "http://127.0.0.1:8000/admin/sessions/{session_id}/timeline?limit=200&order=asc" \
  -H "${AUTH_HEADER}"
```

Optional query:
- `event_type=step_started|step_succeeded|step_failed|step_replayed|step_conflicted`

Event payload shape:
- `step_started`: `client_action_id`, `turn_index_expected`, normalized `input`, `scene_id_before`, `beat_index_before`, provider/model hints, `request_id`
- `step_succeeded`: `recognized`, `resolution`, `narration_text`, scene/beat transition, `duration_ms`, `request_id`
- `step_failed`: strict failfast diagnostics (`error_code`, `stage`, `message`, `provider`, `duration_ms`, `request_id`)
- `step_replayed`: idempotency replay marker with `session_action_id`
- `step_conflicted`: optimistic CAS write conflict marker (`expected_turn_index`, `actual_turn_index`, `request_id`)

### 2) Feedback marker (good/bad)

```bash
curl -sS -X POST "http://127.0.0.1:8000/admin/sessions/{session_id}/feedback" \
  -H "${AUTH_HEADER}" \
  -H 'Content-Type: application/json' \
  -d '{
    "verdict":"bad",
    "reason_tags":["pacing","choice_clarity"],
    "note":"midgame feels flat",
    "turn_index":6
  }'
```

```bash
curl -sS "http://127.0.0.1:8000/admin/sessions/{session_id}/feedback?limit=50" \
  -H "${AUTH_HEADER}"
```

This lets you attach "not fun" cases directly to session traces for later analysis.

### 3) Runtime error aggregation (5m buckets)

```bash
curl -sS "http://127.0.0.1:8000/admin/observability/runtime-errors?window_seconds=300&limit=20" \
  -H "${AUTH_HEADER}"
```

Optional filters:
- `stage=route|narration`
- `error_code=<value>`

Response contains:
- global window summary: `started_total`, `failed_total`, `step_error_rate`
- top buckets keyed by `error_code + stage + model`
- per-bucket samples: `sample_session_ids`, `sample_request_ids`

### 4) Cron alert emitter (webhook + cooldown dedupe)

Dry run (recommended first):

```bash
python scripts/emit_runtime_alerts.py --window-seconds 300 --limit 20 --dry-run
```

Webhook mode:

```bash
python scripts/emit_runtime_alerts.py --window-seconds 300 --limit 20
```

Suggested crontab (every minute):

```bash
* * * * * cd /path/to/RPG_Demo && /path/to/.venv/bin/python scripts/emit_runtime_alerts.py --window-seconds 300 --limit 20
```

Alert signals emitted via single webhook channel:
- `http_5xx_rate_high` (critical)
- `backend_ready_unhealthy` (critical)
- `worker_failure_rate_high` (warning)
- `llm_call_p95_high` (warning)

Each alert includes:
- `severity`, `signal`, `value`, `threshold`, `window_seconds`, `samples`, `runbook_hint`

Oncall runbook:
- `docs/oncall_sop.md`

### 5) HTTP health aggregation

```bash
curl -sS "http://127.0.0.1:8000/admin/observability/http-health?window_seconds=300" \
  -H "${AUTH_HEADER}"
```

Optional query:
- `service=backend|worker`
- `path_prefix=/sessions`
- `exclude_paths=/health,/ready`

Response includes:
- `window_started_at`, `window_ended_at`
- `total_requests`, `failed_5xx`, `error_rate`, `p95_ms`, `top_5xx_paths`

### 6) LLM call health aggregation

```bash
curl -sS "http://127.0.0.1:8000/admin/observability/llm-call-health?window_seconds=300" \
  -H "${AUTH_HEADER}"
```

Optional query:
- `stage=route|narration|json`
- `gateway_mode=worker|unknown`

Response includes:
- `window_started_at`, `window_ended_at`
- `by_stage` fixed keys: `route`, `narration`, `json`, `unknown`
- `by_gateway_mode` fixed keys: `worker`, `unknown`

### 7) Readiness health aggregation

```bash
curl -sS "http://127.0.0.1:8000/admin/observability/readiness-health?window_seconds=300" \
  -H "${AUTH_HEADER}"
```

Response includes:
- `window_started_at`, `window_ended_at`
- backend/worker fail counts in window
- backend/worker consecutive fail streaks
- last failure records (`service`, `error_code`, `request_id`, `created_at`)

## Tests
Default low-cost test set (no live OpenAI critical tests):

```bash
pytest -q -m "not live_openai_critical"
```

Contract sync checks (backend-first gate):

```bash
python -m scripts.export_openapi --check
python -m scripts.generate_frontend_sdk --check
PYTHONPATH=. python -m pytest -q tests/test_contract_artifacts_sync.py tests/api/test_route_contract_snapshot.py
```

Live OpenAI critical validation (sessions runtime + gate precheck):

```bash
PYTHONPATH=. python -m pytest -q -m live_openai_critical -o addopts='-q -rs'
```

Live test notes:
- `tests/live/conftest.py` auto-loads repository `.env` into process environment for live marker tests.
- Required env keys for non-skip live runs: `APP_LLM_OPENAI_BASE_URL`, `APP_LLM_OPENAI_API_KEY`, and one model key from `APP_LLM_OPENAI_ROUTE_MODEL | APP_LLM_OPENAI_NARRATION_MODEL | APP_LLM_OPENAI_MODEL`.
- If live tests fail with `dns_unreachable` or `llm_route_failed`, verify upstream reachability first:

```bash
curl -X POST "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions" \
  -H "Authorization: Bearer ${APP_LLM_OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-flash-us",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 10
  }'
```

Codex sandbox network behavior:
- In Codex CLI sessions, sandboxed command execution can run with restricted outbound network by default.
- In restricted mode, DNS resolution to upstream LLM hosts may fail even when `.env` and API key are correct.
- When DNS/connect errors appear only in sandbox, rerun the same live command with external network permission (outside sandbox restrictions).

Canary tests included:
- `tests/test_canary_runtime_input_tolerance.py`
- `tests/test_canary_fail_forward.py`
- `tests/test_canary_low_confidence_progress.py`
- `tests/test_canary_story_completion.py`

Optional generator evaluation test (skipped by default):

```bash
RUN_GENERATOR_EVAL=1 pytest -q tests/test_generator_eval.py
```

## Browser Release Gate
Use the real browser release gate instead of the removed legacy smoke wrapper:

```bash
./scripts/dev_stack.sh up
python scripts/release/run_author_play_release_gate.py
```

For browser-only iteration or debugging, the Playwright runner remains available at:

```bash
node frontend/scripts/author_play_release_gate.mjs --help
```
