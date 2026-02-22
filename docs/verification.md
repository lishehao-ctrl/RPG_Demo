# Verification

## Core Checks
```bash
python -m compileall app client scripts
pytest -q
python -m pytest -q client/tests
```

## Structure Guardrails
```bash
python -m pytest -q tests/test_architecture_boundaries.py tests/test_docs_index_consistency.py
```

## Authoring (ASF v4)
```bash
python -m pytest -q tests/test_story_authoring_compile.py tests/test_story_authoring_validate_api.py
python -m pytest -q tests/test_story_author_assist_api.py
python -m pytest -q tests/test_story_playability_gate.py
python -m pytest -q tests/test_demo_author_ui.py tests/test_demo_routes.py -k author
```

Hard-cut checks:
1. submit a pre-v4 payload to `/stories/validate-author`, expect `422` with `AUTHOR_V4_REQUIRED`.
2. submit a pre-v4 payload to `/stories/compile-author`, expect `422` with `AUTHOR_V4_REQUIRED`.
3. call `/stories/author-assist` with each v4 task and confirm response contains `suggestions`, `patch_preview`, `warnings`, `provider`, `model`.
4. verify validate response includes `playability.pass`, `playability.blocking_errors`, and metrics.

Manual author checks:
1. Open `/demo/author` and confirm default tab is `Author`; `Debug` tab is hidden.
2. Enable `Show Debug` and confirm `Debug` tab appears and can be switched to.
3. In Author tab, run `Parse All Layers` and verify changes are auto-applied without manual patch click.
4. Click `Undo Last Apply` and confirm the latest assist batch is rolled back.
5. In Debug tab, confirm raw `suggestions` and `patch_preview` are visible for diagnosis.

## Dev Debug Checks
```bash
python -m pytest -q tests/test_session_api.py -k "llm_trace or layer_inspector"
```

Manual checks:
1. Open `/demo/dev` with an active session.
2. Refresh `LLM Debug Trace` and verify data loads.
3. Refresh `Layer Inspector` and verify layered step cards are rendered.
4. Set non-dev env and confirm both debug endpoints return `404 DEBUG_DISABLED`.

## Story Runtime Focus
```bash
python -m pytest -q tests/test_story_engine_integration.py -k "fallback or player_input or narrative"
python -m pytest -q tests/test_llm_prompts.py
```

## Model Config Check
```bash
rg -n "^LLM_MODEL_GENERATE=" .env
```

After server restart, confirm `/demo/dev` shows `model_generate=qwen3-coder-plus`.
