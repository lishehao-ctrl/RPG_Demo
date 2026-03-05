# Agent Collaboration Workflow (Codex Backend + Antigravity Frontend)

This document defines the baseline workflow for dual-agent parallel development in this monorepo.

## 1) Roles and ownership

- **Codex (backend owner)**: `rpg_backend/**`, `alembic/**`, backend tests, runtime/worker behavior, API contracts.
- **Antigravity (frontend owner)**: `frontend/**`, UI state management, view composition, frontend integration tests.
- **Shared**: `contracts/openapi/**` (contract source of truth) and generated frontend SDK artifact.

## 2) Branch policy

- Backend branches: `codex/backend-*`
- Frontend branches: `antigravity/frontend-*`
- No direct push to `main`.
- Cross-domain changes must be explicit in PR summary and reviewed by both sides.

## 3) Backend-first contract gate

When API routes or schemas change:

1. Backend PR updates:
   - backend implementation (`rpg_backend/api/**` as needed),
   - `contracts/openapi/backend.openapi.json`.
2. Backend PR merges to `main`.
3. Frontend branch rebases on latest `main`.
4. Frontend regenerates SDK:
   - `python -m scripts.generate_frontend_sdk`
5. Frontend PR continues on top of merged backend contract.

Frontend should not ship protocol assumptions without merged backend contract updates.

## 4) Standard commands

- Export OpenAPI artifact:
  - `python -m scripts.export_openapi`
- Check OpenAPI artifact sync:
  - `python -m scripts.export_openapi --check`
- Generate frontend SDK artifact:
  - `python -m scripts.generate_frontend_sdk`
- Check frontend SDK sync:
  - `python -m scripts.generate_frontend_sdk --check`

## 5) CI guardrails

- Contract sync workflow runs:
  - OpenAPI artifact sync check
  - Generated SDK sync check
  - Route + contract artifact tests
- A PR that changes API contract but omits artifact updates should fail CI.

## 6) Merge conflict protocol

If frontend is blocked by missing fields/endpoints:

1. Frontend opens an issue with expected request/response shape.
2. Backend implements and updates OpenAPI artifact first.
3. Frontend rebases and consumes regenerated SDK.

Do not resolve backend/frontend contract drift by hand-editing generated SDK files.
