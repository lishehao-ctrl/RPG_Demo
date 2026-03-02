# RPG Backend (Strict Runtime)

Backend-first interactive narrative RPG service with OpenAI-only runtime behavior:
- `openai` provider uses quality-first failfast for LLM route/narration failures.
- Preconditions never hard-block progression.
- When success/partial cannot apply, runtime must execute `fail_forward`.

## Stack
- Python 3.11+
- FastAPI + Pydantic v2
- SQLModel + SQLite
- pytest

## Architecture
Code is split by responsibilities:
- `rpg_backend/domain`: Story Pack DSL schema + linter
- `rpg_backend/generator`: deterministic story generator (`planner/builder/prompt_compiler/service`)
- `rpg_backend/runtime`: Pass A routing + Pass B deterministic resolution + narration composition
- `rpg_backend/llm`: OpenAI provider abstraction (`OpenAIProvider`)
- `rpg_backend/storage`: SQLModel entities + repositories
- `rpg_backend/api`: REST API (stories/sessions)

Runtime architecture source of truth:
- `docs/story_architecture_v3.md`

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run server:

```bash
uvicorn rpg_backend.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Configuration
Environment variables use `APP_` prefix.

- `APP_DATABASE_URL` default: `sqlite:///./app.db`
- `APP_ROUTING_CONFIDENCE_THRESHOLD` default: `0.55`
- `APP_LLM_OPENAI_BASE_URL` required
- `APP_LLM_OPENAI_API_KEY` required
- `APP_LLM_OPENAI_MODEL` optional legacy fallback model
- `APP_LLM_OPENAI_ROUTE_MODEL` optional selection model (fallback chain: `NARRATION -> MODEL`)
- `APP_LLM_OPENAI_NARRATION_MODEL` optional narration model (fallback chain: `ROUTE -> MODEL`)
- `APP_LLM_OPENAI_GENERATOR_MODEL` optional prompt-compiler model (falls back to effective route model)
- `APP_LLM_OPENAI_TIMEOUT_SECONDS` default: `20`
- `APP_LLM_OPENAI_ROUTE_MAX_RETRIES` default: `3` (max 3)
- `APP_LLM_OPENAI_NARRATION_MAX_RETRIES` default: `1`
- `APP_LLM_OPENAI_TEMPERATURE_ROUTE` default: `0.1`
- `APP_LLM_OPENAI_TEMPERATURE_NARRATION` default: `0.4`
- `APP_LLM_OPENAI_GENERATOR_TEMPERATURE` default: `0.15`
- `APP_LLM_OPENAI_GENERATOR_MAX_RETRIES` default: `3` (max 3)

OpenAI model resolution:
- `route_model = APP_LLM_OPENAI_ROUTE_MODEL or APP_LLM_OPENAI_NARRATION_MODEL or APP_LLM_OPENAI_MODEL`
- `narration_model = APP_LLM_OPENAI_NARRATION_MODEL or APP_LLM_OPENAI_ROUTE_MODEL or APP_LLM_OPENAI_MODEL`
- `generator_model = APP_LLM_OPENAI_GENERATOR_MODEL or route_model`
- if both effective models are empty, OpenAI provider initialization fails with `503` on session create/step.
- OpenAI provider calls `POST /v1/chat/completions` (strict Chat Completions-only).

OpenAI provider bootstrap:

```bash
cp .env.llm.example .env
# then fill APP_LLM_OPENAI_BASE_URL / APP_LLM_OPENAI_API_KEY
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

## Story Pack and Linter
Global move IDs (required in every scene):
- `global.clarify`
- `global.look`
- `global.help_me_progress`

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

## API Flow (curl)

### 1) Create draft story

```bash
curl -sS -X POST http://127.0.0.1:8000/stories \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg title 'City Signal Draft' --argjson pack "$(cat sample_data/story_pack_v1.json)" '{title:$title, pack_json:$pack}')"
```

### 2) Publish story version

```bash
curl -sS -X POST http://127.0.0.1:8000/stories/{story_id}/publish \
  -H 'Content-Type: application/json' \
  -d '{}'
```

### 3) Read published raw pack

```bash
curl -sS "http://127.0.0.1:8000/stories/{story_id}?version=1"
```

### 3.5) Generate story

```bash
curl -sS -X POST http://127.0.0.1:8000/stories/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt_text":"A city-wide signal breach where a burned-out systems engineer must stabilize a failing reactor while rival factions compete for control.",
    "seed_text":"A city-wide signal breach",
    "target_minutes":10,
    "npc_count":4,
    "variant_seed":"demo-seed-001",
    "generator_version":"v3.1",
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
- Prompt mode enforces explicit StorySpec field limits (`title<=120`, `premise<=400`, `tone<=120`, `stakes<=300`, etc).
- On schema validation failures, PromptCompiler retries with validation feedback (up to 3 attempts).
- No local truncation is applied; if compile still fails, request returns `422` with `prompt_spec_invalid`.
Generator output now includes:
- `lint_report`
- `generation_attempts`
- `regenerate_count`
- `notes`
- `generation_mode` (`prompt|seed`)
- `spec_hash` / `spec_summary` (prompt mode only)
- `pack_hash` (stable hash of raw `pack_json`)
- `generator_version`
- `variant_seed` (actual seed used; auto-generated when omitted)
- `palette_policy` (`random|balanced|fixed`)

Breaking change:
- `attempts` and `repair_notes` were removed from `/stories/generate` response/detail.

### 4) Create session

```bash
curl -sS -X POST http://127.0.0.1:8000/sessions \
  -H 'Content-Type: application/json' \
  -d '{"story_id":"{story_id}","version":1}'
```

### 5) Step with text input

```bash
curl -sS -X POST http://127.0.0.1:8000/sessions/{session_id}/step \
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
  -H 'Content-Type: application/json' \
  -d '{
    "client_action_id":"step-2",
    "input":{"type":"button","move_id":"global.clarify"},
    "dev_mode":true
  }'
```

### 7) Inspect session state

```bash
curl -sS "http://127.0.0.1:8000/sessions/{session_id}?dev_mode=true"
```

### 8) Simulate a playthrough transcript

```bash
python scripts/simulate_playthrough.py \
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
python scripts/simulate_playthrough.py \
  --pack-file sample_data/story_pack_v1.json \
  --provider openai \
  --strategy mixed \
  --strategy-seed 12345 \
  --pack-hash local-pack-hash \
  --generator-version v3.1 \
  --variant-seed replay-seed-1 \
  --max-steps 20
```

### 9) Evaluate generator quality (manual/nightly)

```bash
python scripts/evaluate_generator.py \
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
python scripts/evaluate_llm_gate.py \
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
python scripts/evaluate_llm_gate.py \
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
python scripts/evaluate_llm_story_generation.py \
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
- prompt mode generation only (`GeneratorService.generate_pack(prompt_text=...)`)
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

## Idempotency Contract
`POST /sessions/{session_id}/step` uses `client_action_id`.

If the same `client_action_id` is submitted again for the same session:
- returns **HTTP 200**
- returns the **exact first response payload**

Step input tolerance contract:
- malformed action shape in valid JSON (missing `input`, missing `move_id`, invalid `input.type`) is normalized and executed with global fallback moves.
- invalid session state still returns system errors (`404`/`409`).
- strict provider (`openai`) may return `503` on LLM runtime failures with detail:
  - `error_code`: `llm_route_failed | llm_route_low_confidence | llm_route_invalid_move | llm_narration_failed`
  - `stage`: `route | narration`
  - `message`: failure detail
  - `provider`: `openai`
- invalid JSON syntax can still return framework-level parse errors.

## Admin Diagnostics (Session Trace + Feedback)
Admin diagnostics endpoints are exposed under `/admin` with no auth in this phase.
Use only in local/internal environments.

### 1) Timeline replay

```bash
curl -sS "http://127.0.0.1:8000/admin/sessions/{session_id}/timeline?limit=200&order=asc"
```

Optional query:
- `event_type=step_started|step_succeeded|step_failed|step_replayed`

Event payload shape:
- `step_started`: `client_action_id`, `turn_index_expected`, normalized `input`, `scene_id_before`, `beat_index_before`, provider/model hints
- `step_succeeded`: `recognized`, `resolution`, `narration_text`, scene/beat transition, `duration_ms`
- `step_failed`: strict failfast diagnostics (`error_code`, `stage`, `message`, `provider`, `duration_ms`)
- `step_replayed`: idempotency replay marker with `session_action_id`

### 2) Feedback marker (good/bad)

```bash
curl -sS -X POST "http://127.0.0.1:8000/admin/sessions/{session_id}/feedback" \
  -H 'Content-Type: application/json' \
  -d '{
    "verdict":"bad",
    "reason_tags":["pacing","choice_clarity"],
    "note":"midgame feels flat",
    "turn_index":6
  }'
```

```bash
curl -sS "http://127.0.0.1:8000/admin/sessions/{session_id}/feedback?limit=50"
```

This lets you attach "not fun" cases directly to session traces for later analysis.

## Tests
Default low-cost test set (no live OpenAI critical tests):

```bash
pytest -q -m "not live_openai_critical"
```

Live OpenAI critical validation (sessions runtime + gate precheck):

```bash
pytest -q -m live_openai_critical -o addopts='-q'
```

Canary tests included:
- `tests/test_canary_runtime_input_tolerance.py`
- `tests/test_canary_fail_forward.py`
- `tests/test_canary_low_confidence_progress.py`
- `tests/test_canary_story_completion.py`

Optional generator evaluation test (skipped by default):

```bash
RUN_GENERATOR_EVAL=1 pytest -q tests/test_generator_eval.py
```

## Playwright Smoke
A script is provided to do a browser smoke check through the Playwright CLI wrapper:

```bash
scripts/playwright_smoke.sh
```

It expects the server to be running at `http://127.0.0.1:8000` and `npx` available.
