# Frontend Workspace

This frontend is a `Vite + React + TypeScript` app for a real dual-track product:

- `Author Mode` on `/author/*`
- `Play Mode` on `/play/*`

## Route Summary

- `/login`: authentication gate
- `/author/stories`: run creation + story index
- `/author/runs/:runId`: run shell (events/artifacts/rerun)
- `/author/stories/:storyId/review`: review + draft edit + publish
- `/play/library`: published story library
- `/play/sessions/:sessionId`: live play runtime

## Design Source

This UI continues from the self-authored Figma review file:

- [Ember Command UI Review](https://www.figma.com/design/H5Lw8e3kT7cpV4lzYDGwuP)

Current direction:

- `Author Mode`: thin client over backend workflow state (`/author/runs` + `/author/stories`)
- `Play Mode`: runtime chamber / transcript-first / action deck

## Contract Inputs

- `../frontend_agent_contract.md`
- `src/shared/api/generated/backend-sdk.ts`

## Primary Local Run Path

Use the repo-root dev stack script as the default full-stack entrypoint:

```bash
./scripts/dev_stack.sh up
./scripts/dev_stack.sh ready
./scripts/dev_stack.sh logs frontend
```

This starts migration, backend, and the Vite frontend together.

When you finish local work:

```bash
./scripts/dev_stack.sh down
```

## Frontend-Only Commands

If the full stack is already running and you only need frontend iteration:

```bash
cd frontend
npm install
npm run dev
npm run build
```

The Vite server runs on `http://127.0.0.1:8173`, proxies `/api/*` to `http://127.0.0.1:8000`, and expects local PostgreSQL to be available on `127.0.0.1:8132` via `./scripts/dev_stack.sh up`.

## Manual Verification Path

- Login with the configured admin credentials.
- Enter `Author Mode` on `/author/stories`.
- Generate a draft with a single `raw_brief`.
- Open run shell on `/author/runs/:runId` (or via story resolver).
- Open review workspace on `/author/stories/:storyId/review`.
- Publish the story.
- Move to `Play Mode` on `/play/library`.
- Start a session from the published version.
- In `/play/sessions/:sessionId`, run one button step and one free-text step.
- Refresh the page and confirm the timeline rebuilds from `GET /sessions/{session_id}/history`.

## Current MVP Boundaries

Implemented now:

- author run creation + run diagnostics
- author story index + review workspace
- publish handoff to play
- published play library
- live runtime session with reload-safe history

Not implemented now:

- full visual story editor
- story diffing and branch management
- advanced author operations beyond generate / inspect / publish / handoff to play
