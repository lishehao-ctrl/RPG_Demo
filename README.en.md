# RPG Demo Rebuild

## What This Is

This is a full-stack interactive narrative demo in a single repo. The product loop is intentionally short:

1. enter an English story seed
2. generate a preview
3. start an author job
4. publish into the library
5. open a story from the library
6. play it through natural-language turns

The project is now pivoting away from the old civic-procedural narrative direction toward relationship drama.

Current active product/refactor docs:

- `specs/relationship_drama_pivot_strategy_20260328.md`
- `specs/backend/2026-03-28-relationship-drama-backend-refactor/SPEC.md`
- `specs/backend/2026-03-28-relationship-drama-runtime-architecture/SPEC.md`
- `specs/frontend/2026-03-28-relationship-drama-ui-refactor/SPEC.md`

## Stack

- Backend: FastAPI + Pydantic + LangGraph
- Frontend: React 19 + TypeScript + Vite
- Storage: SQLite
- Identity: real cookie-session auth

Main backend domains:

- `rpg_backend/author/`
- `rpg_backend/library/`
- `rpg_backend/play/`
- `rpg_backend/benchmark/`

## Current State

- the real `author -> publish -> play` product loop works
- public library, private owned stories, and protected play sessions are wired correctly
- author jobs, play sessions, and author checkpoints survive restart
- deployment should remain single-host / single-backend-process for now

## Local Run

Backend:

```bash
pip install -e ".[dev]"
uvicorn rpg_backend.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Common Validation

Backend tests:

```bash
pytest -q
```

Frontend checks:

```bash
cd frontend
npm run check
```

Real HTTP smoke:

```bash
python tools/http_product_smoke.py --base-url http://127.0.0.1:8000
```

Smoke with benchmark diagnostics:

```bash
python tools/http_product_smoke.py \
  --base-url http://127.0.0.1:8000 \
  --include-benchmark-diagnostics
```

## Deploy

Production domain:

- `https://rpg.shehao.app`

AWS single-host deployment material:

- `deploy/aws_ubuntu/DEPLOY.md`
- `deploy/aws_ubuntu/.env.production.example`
- `deploy/aws_ubuntu/rpg-demo-backend.service`
- `deploy/aws_ubuntu/nginx-rpg-demo.conf`

## Related Docs

- `specs/relationship_drama_pivot_strategy_20260328.md`
- `specs/backend/2026-03-28-relationship-drama-backend-refactor/SPEC.md`
- `specs/backend/2026-03-28-relationship-drama-runtime-architecture/SPEC.md`
- `specs/frontend/2026-03-28-relationship-drama-ui-refactor/SPEC.md`
- `specs/interface_governance_20260319.md`
- `specs/interface_stability_matrix_20260319.md`
- `frontend/specs/FRONTEND_PRODUCT_SPEC.md`
