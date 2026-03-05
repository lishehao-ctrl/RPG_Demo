# Frontend Workspace (Antigravity-owned)

This directory is reserved for frontend implementation in the monorepo collaboration flow.

## Contract policy

- Do not guess backend payload fields.
- Consume generated SDK from `frontend/src/shared/api/generated/backend-sdk.ts`.
- Request backend contract changes first, then rebase `main`, then regenerate SDK.

## Ownership

- Frontend agent should only modify files under `frontend/**`.
- Backend agent should avoid editing this directory except generated SDK bootstrap when contract tooling changes.
