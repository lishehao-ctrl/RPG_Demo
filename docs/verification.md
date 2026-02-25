# Verification

## Core Checks
```bash
python -m compileall app scripts tests
pytest -q
python -m pytest -q client/tests
```

## API and Route Checks
```bash
python -m pytest -q tests/test_demo_routes.py tests/test_story_pack_api.py
python -m pytest -q tests/test_session_api.py tests/test_session_step_integration.py tests/test_story_engine_integration.py
```

Hard-cut route assertions:
1. `GET /demo/author` is not available (`404`).
2. `POST /stories` is not available (`404/405`).
3. `POST /stories/{story_id}/publish` is not available (`404/405`).
4. `POST /stories/validate` remains available.
5. `GET /stories` and `GET /stories/{story_id}` remain available.

## Architecture and Prompt Checks
```bash
python -m pytest -q tests/test_architecture_boundaries.py tests/test_docs_index_consistency.py
python -m pytest -q tests/test_llm_prompts.py tests/test_prompt_contract_lint.py
```

## UI Screenshot Smoke
```bash
python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local
```

## Offline Story Seed
```bash
python scripts/seed.py --story-file examples/storypacks/campus_week_v1.json --publish
```
