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
LLM_PROVIDER_PRIMARY=alibaba_qwen
LLM_MODEL_GENERATE=qwen3-coder-plus
LLM_DOUBAO_BASE_URL=https://api.xiaocaseai.com/v1
LLM_DOUBAO_API_KEY=<your-api-key>
```

If you change model/base URL, restart `./scripts/dev.sh` so runtime picks up the new values.

## Run Tests
```bash
pytest -q
python -m pytest -q client/tests
```

## Code Structure
- Documentation index: `docs/INDEX.md`
- Module boundaries and ownership: `docs/code-structure.md`

## UI Route Smoke
```bash
pytest -q tests/test_demo_routes.py
```

## Authoring Workflow (ASF v4 Hard-Cut)
Use the author wizard to create story drafts in ASF v4 and compile to runtime StoryPack:

1. Open `/demo/author`.
2. Stay in `Author` tab for writing-first flow (turn on `Show Debug` only when you need raw diagnostics).
3. Choose entry mode:
   - `Spark` (one-line seed -> expansion),
   - `Ingest` (paste full story text -> RPG projection).
4. Click `Parse All Layers` and other assist buttons; patches are auto-applied by default.
5. Review `Writer Turn Feed` and `Next Steps`.
6. Use `Undo Last Apply` to revert the latest AI change batch.
7. Iterate through the structured editor only when you want fine-grained control (`World -> ... -> Review`).
8. Validate ASF v4 via `POST /stories/validate-author`.
9. Compile runtime pack via `POST /stories/compile-author`.
10. Save draft through `POST /stories`.
11. Create version-pinned playtest session through `POST /sessions`.

Author API hard-cut policy:
- `validate-author` and `compile-author` accept ASF v4 only.
- pre-v4 payloads return `422` with `detail.code=AUTHOR_V4_REQUIRED`.

Author assist tasks (all auto-apply in UI):
- `story_ingest`
- `seed_expand`
- `beat_to_scene`
- `scene_deepen`
- `option_weave`
- `consequence_balance`
- `ending_design`
- `consistency_check`

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
