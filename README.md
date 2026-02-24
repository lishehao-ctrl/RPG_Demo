# RPG Demo

## Run Server (Dev)
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e "./client[pretty]"
./scripts/dev.sh
```

Server:
- `http://127.0.0.1:8000`

Demo pages:
- `http://127.0.0.1:8000/demo/play`
- `http://127.0.0.1:8000/demo/dev`
- `http://127.0.0.1:8000/demo/author`

## LLM Runtime Config
Set these in `.env` before starting the server:

```bash
LLM_MODEL_GENERATE=codex
LLM_DOUBAO_API_KEY=<your-api-key>
```

Notes:
- `LLM_PROVIDER_PRIMARY` is removed. Backend provider selection is internal.
- You only need API key + model name (for example `codex` or `gpt-5.1`).
- Runtime mode: `ENV=test` uses built-in fake provider; non-test environments call the proxy endpoint.

LLM proxy policy (hard rule):
- Endpoint is fixed to `POST https://api.xiaocaseai.cloud/v1/chat/completions`.
- Runtime always injects system prompt:
  - `Return STRICT JSON. No markdown. No explanation.`
- Runtime always forces `temperature=0`.
- Runtime does not use `/v1/responses`, `response_format`, or `json_schema`.
- Retry policy is fail-fast with max 2 retries (`0.5s`, `1s`), then raises.

If you change model/API key, restart `./scripts/dev.sh` so runtime picks up the new values.

Breaking API updates in this hard-cut:
- `POST /stories/author-assist` no longer returns `provider`.
- `POST /sessions/{id}/step` no longer returns `cost`.
- `GET /sessions/{id}/debug/llm-trace` has been removed.

## Run Tests
```bash
pytest -q
python -m pytest -q client/tests
```

## Code Structure
- Documentation index: `docs/INDEX.md`
- Module boundaries and ownership: `docs/code-structure.md`
- LLM responsibility boundary (ZH): `docs/architecture-llm-boundary-zh.md`
- Chinese Author Mode guide: `docs/author-mode-zh.md`

Boundary principle:
- LLM is used for narration, choice mapping assistance, and author suggestions.
- Deterministic engines own state transitions, quest/event/ending progression, and compile/validate correctness.

Refactor layout (current backend):
- Story assist internals: `app/modules/story/author_assist_core/*`
- LLM runtime internals: `app/modules/llm/runtime/*`
- Session runtime phase modules: `app/modules/session/story_runtime/phases/*`
- Session runtime dependency assembly: `app/modules/session/runtime_deps.py`
- Session runtime orchestration: `app/modules/session/runtime_orchestrator.py`

Architecture change gate:
- Run `docs/verification.md` section `Architecture PR Minimum Gate` before merge.
- Keep non-whitelist LLM import boundaries green (`tests/test_architecture_boundaries.py`).
- Do not reintroduce historical story compatibility paths.

## UI Route Smoke
```bash
pytest -q tests/test_demo_routes.py
```

## Authoring Workflow (ASF v4 Hard-Cut)
Use the author wizard to create story drafts in ASF v4 and compile to runtime StoryPack:

1. Open `/demo/author`.
2. Stay in `Author` tab for writing-first flow (turn on `Show Debug` only when you need raw diagnostics).
3. Use the 3-page flow:
   - `Compose`: seed/source, parse, continue writing actions.
   - `Shape`: readable narrative templates for Characters/Action, plus structured scene/option edits.
   - `Build`: next steps, playability blocking, validate/compile/save/playtest.
4. Choose entry mode:
   - `Spark` (one-line seed -> expansion),
   - `Ingest` (paste full story text -> RPG projection).
5. Click `Parse All Layers` and other assist buttons; patches are auto-applied by default.
   - If model access is unavailable, the UI now shows a retry hint instead of returning deterministic template content.
   - For `seed_expand`, `story_ingest`, and `continue_write`, the backend runs conditional staged generation:
     1) idea blueprint,
     2) cast blueprint (only when existing NPC count/diversity is insufficient),
     3) structured story build.
   - NPC policy for these tasks is deterministic merge: preserve existing named NPCs, then supplement to target cast size `3-5` (hard cap `6`).
   - If a generated `flow` rewires scene keys, ending triggers are auto-synced to valid `flow.scenes[].scene_key` values.
6. For post-parse iteration use:
   - `Continue Write` (`continue_write`)
   - `Trim Content` (`trim_content`)
   - `Spice Branch` (`spice_branch`)
   - `Rebalance Tension` (`tension_rebalance`)
7. Review `Story Overview` and `Next Steps` in Compose.
   - Writer turn cards and raw layer JSON are now debug-only (`Show Debug` -> `Debug` tab).
8. Use `Undo Last Apply` to revert the latest AI change batch.
9. Validate ASF v4 via `POST /stories/validate-author`.
10. Compile runtime pack via `POST /stories/compile-author`.
11. Save draft through `POST /stories`.
12. Create version-pinned playtest session through `POST /sessions`.

Author API hard-cut policy:
- `validate-author` and `compile-author` accept ASF v4 only.
- pre-v4 payloads return `422` with `detail.code=AUTHOR_V4_REQUIRED`.

Runtime pack hard-cut policy:
- Stored story packs are validated as StoryPack v10 strict on startup.
- Legacy/non-strict packs block startup with `LEGACY_STORYPACKS_BLOCK_STARTUP`.
- Runtime load rejects non-strict packs with `RUNTIME_PACK_V10_REQUIRED`.

Author assist tasks (all auto-apply in UI):
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

Author assist failure behavior:
- `POST /stories/author-assist` returns `503` when model output is unavailable/invalid.
- `detail.code` is either:
  - `ASSIST_LLM_UNAVAILABLE`
  - `ASSIST_INVALID_OUTPUT`
- UI guidance is retry-first; no server-side deterministic assist fallback is returned.

Author assist two-stage tuning (optional `.env` overrides):
- `LLM_AUTHOR_ASSIST_EXPAND_MAX_TOKENS` (default `1400`)
- `LLM_AUTHOR_ASSIST_BUILD_MAX_TOKENS` (default `2048`)
- `LLM_AUTHOR_ASSIST_REPAIR_MAX_TOKENS` (default `900`)
- `LLM_PROMPT_AUTHOR_MAX_CHARS` (default `14000`)
- `LLM_PROMPT_PLAY_MAX_CHARS` (default `7000`)
- `LLM_PROMPT_COMPACTION_LEVEL` (default `aggressive`, options: `safe|aggressive`)

Prompt baseline/quality scripts:
```bash
python scripts/eval_prompt_baseline.py
python scripts/eval_prompt_quality.py
```

## Legacy Note (Previous UI Flow)
Earlier docs or screenshots may still mention suggestion-only patch application. Current behavior is auto-apply + undo-first author workflow.

## Dev Layer Inspector
`/demo/dev` now includes a `Layer Inspector` panel backed by:
- `GET /sessions/{id}/debug/layer-inspector`

The endpoint is dev-only:
- non-dev env returns `404` with `detail.code="DEBUG_DISABLED"`.

## UI Screenshots (Playwright)
```bash
pip install -r requirements-dev-ui.txt
python -m playwright install chromium
python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local
```

Author stage animation + first-pass Story Overview manual E2E (optional, not a CI hard gate):
```bash
python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local --check-author-animation
```
This check validates stage animation transitions and that Story Overview updates into a natural-language paragraph during build stage.
