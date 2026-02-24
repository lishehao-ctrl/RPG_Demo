# Verification

## Core Checks
```bash
python -m compileall app client scripts
pytest -q
python -m pytest -q client/tests
```

## Architecture PR Minimum Gate
Run this set for any PR that touches story/session architecture, LLM runtime, or author-assist internals.

```bash
python -m compileall app
python -m pytest -q tests/test_architecture_boundaries.py tests/test_docs_index_consistency.py
python -m pytest -q tests/test_story_pack_api.py tests/test_story_authoring_validate_api.py tests/test_story_authoring_compile.py
python -m pytest -q tests/test_story_author_assist_api.py tests/test_llm_adapter_author_assist_structured.py tests/test_llm_adapter_timeout_policy.py
python -m pytest -q tests/test_session_api.py tests/test_story_engine_integration.py tests/test_story_runtime_decisions.py
```

Compatibility hard-cut sanity:
```bash
rg -n "author_source_v3|_project_v4_to_v3_payload|compile_author_story_payload_v3" app docs tests
```

## Structure Guardrails
```bash
python -m pytest -q tests/test_architecture_boundaries.py tests/test_docs_index_consistency.py
```

## Architecture Boundary Minimum Set
Run this set for any PR that touches prompts, adapter, runtime pipeline, or author-assist:

```bash
python -m pytest -q tests/test_architecture_boundaries.py
python -m pytest -q tests/test_story_author_assist_api.py tests/test_story_authoring_validate_api.py tests/test_story_authoring_compile.py
python -m pytest -q tests/test_session_api.py tests/test_story_engine_integration.py
```

## Authoring (ASF v4)
```bash
python -m pytest -q tests/test_story_authoring_compile.py tests/test_story_authoring_validate_api.py
python -m pytest -q tests/test_story_author_assist_api.py
python -m pytest -q tests/test_story_playability_gate.py tests/test_story_playability_fun_metrics.py
python -m pytest -q tests/test_demo_author_ui.py tests/test_demo_routes.py -k author
```

Hard-cut checks:
1. submit a pre-v4 payload to `/stories/validate-author`, expect `422` with `AUTHOR_V4_REQUIRED`.
2. submit a pre-v4 payload to `/stories/compile-author`, expect `422` with `AUTHOR_V4_REQUIRED`.
3. call `/stories/author-assist` with each v4 task under an available model (or test stub) and confirm `200` response contains `suggestions`, `patch_preview`, `warnings`, `model`.
4. simulate model outage and confirm `/stories/author-assist` returns `503` with `ASSIST_LLM_UNAVAILABLE` (retryable hint included).
5. verify validate response includes `playability.pass`, `playability.blocking_errors`, and full metrics (including contrast/dominant/recovery/tension).
6. for `seed_expand/story_ingest/continue_write`, verify warnings include pipeline trace marker:
   - `pipeline_trace: two_stage/<task> expand->build`
7. for `seed_expand/story_ingest/continue_write`, verify NPC merge policy:
   - existing named NPCs are preserved,
   - roster is supplemented to at least 3 NPCs when under-populated,
   - total NPCs stay within hard cap 6.
8. for `/stories/author-assist/stream`, verify stage contract:
   - gap case includes `author.expand.start -> author.cast.start -> author.build.start`,
   - sufficient cast case skips `author.cast.start`.
9. verify parse-generated flow updates also patch `ending.ending_rules` to valid scene references.
10. verify startup blocks when DB contains legacy/non-strict runtime packs:
   - expect `LEGACY_STORYPACKS_BLOCK_STARTUP`.
11. verify runtime load rejects non-strict stored pack with:
   - `RUNTIME_PACK_V10_REQUIRED`.

Manual author checks:
1. Open `/demo/author` and confirm default tab is `Author`; `Debug` tab is hidden.
2. Confirm 3-page flow appears in Author tab: `Compose`, `Shape`, `Build`.
3. In `Compose`, run `Parse All Layers` and verify changes are auto-applied without manual patch click.
   - confirm one click still drives internal two-stage generation (idea expand -> story build) with no extra UI step.
4. In `Compose`, run `Continue Write`, `Trim Content`, `Spice Branch`, `Rebalance Tension` and verify each updates draft.
5. Click `Undo Last Apply` and confirm the latest assist batch is rolled back.
6. Confirm `Story Overview` renders as natural-language paragraph text (not label/value JSON-like rows).
7. In `Shape`, confirm Characters/Action use narrative templates and parse errors show template guidance (not "Invalid JSON").
8. Enable `Show Debug` and confirm raw `suggestions`, `patch_preview`, and `Raw Layer Data` remain available for diagnosis.

Manual author animation E2E (optional, non-CI gate):
```bash
python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local --check-author-animation
```
This script verifies button stage animation transitions and Story Overview first-pass expansion visibility in natural-language form before build completion.

## Dev Debug Checks
```bash
python -m pytest -q tests/test_session_api.py -k "layer_inspector"
```

Manual checks:
1. Open `/demo/dev` with an active session.
2. Refresh `Layer Inspector` and verify layered step cards are rendered with natural-language summaries.
3. Confirm each layer card keeps a collapsible `Raw payload` block for debugging fallback.
4. Set non-dev env and confirm debug endpoint returns `404 DEBUG_DISABLED`.

## Story Runtime Focus
```bash
python -m pytest -q tests/test_story_engine_integration.py -k "fallback or player_input or narrative"
python -m pytest -q tests/test_llm_prompts.py
python -m pytest -q tests/test_prompt_contract_lint.py
python -m pytest -q tests/test_llm_chat_completions_client.py tests/test_doubao_provider.py
```

## LLM Proxy Guardrails
```bash
# Ensure codebase does not call OpenAI Responses API path.
rg -n "/v1/responses" app/modules/llm

# Ensure proxy-safe request policy is covered by tests.
python -m pytest -q tests/test_llm_chat_completions_client.py tests/test_doubao_provider.py
```

## Runtime Pack Hard-Cut Checks
```bash
python -m pytest -q tests/test_story_pack_api.py -k "legacy or startup"
python -m pytest -q tests/test_session_api.py -k "legacy_storypack_shape"
rg -n "author_source_v3" app docs tests
```

## Prompt Baseline + Quality
```bash
python scripts/eval_prompt_baseline.py
python scripts/eval_prompt_quality.py
```

## Model Config Check
```bash
rg -n "^LLM_MODEL_GENERATE=" .env
```

After server restart, confirm `/demo/dev` shows `model_generate=qwen3-coder-plus`.
