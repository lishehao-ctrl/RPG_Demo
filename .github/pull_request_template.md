## Summary
- What changed:
- Why:

## Ownership / Boundaries
- [ ] This PR only changes one ownership domain (`rpg_backend/**` or `frontend/**`), or explicitly documents cross-domain intent.
- [ ] I confirmed no accidental edits in unrelated ownership paths.

## Contract / SDK Sync (backend-first gate)
- [ ] If this PR changes `rpg_backend/api/**` or `rpg_backend/api/schemas.py`, I updated `contracts/openapi/backend.openapi.json`.
- [ ] If `contracts/openapi/backend.openapi.json` changed, I regenerated `frontend/src/shared/api/generated/backend-sdk.ts`.
- [ ] I did not hand-edit generated SDK files.

## Merge Order
- [ ] This PR follows backend-first merge order when frontend depends on new/changed APIs.
- [ ] Frontend changes are rebased on latest `main` after backend contract merge (if applicable).

## Validation
- [ ] `python -m scripts.export_openapi --check`
- [ ] `python -m scripts.generate_frontend_sdk --check`
- [ ] `PYTHONPATH=. python -m pytest -q tests/test_contract_artifacts_sync.py tests/api/test_route_contract_snapshot.py`
- [ ] `PYTHONPATH=. python -m pytest -q -m "not live_openai_critical"` (or explain why not run)
