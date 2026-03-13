# Runtime Status

## Current Active Runtime

- Backend directly calls Responses API through `ResponsesTransport`.
- Play rail uses one `PlayAgent` abstraction (`interpret_turn`, `render_resolved_turn`).
- Author rail uses one `AuthorAgent` abstraction for overview/outline nodes.
- Provider cursor reuse uses `previous_response_id` persisted in `response_session_cursors`.

## Determinism Boundaries

- Play outcome resolution and effect application remain deterministic in backend runtime.
- Author `plan_beats/materialize/lint/normalize` remain deterministic.

## Observability Contract

- `llm_gateway_mode` / gateway aggregation use `responses` naming.
- stage naming is `interpret_turn` and `render_resolved_turn`.
- readiness health aggregates `backend` and `responses` services.

## Readiness

- `/ready` checks:
  - database check
  - responses config check
  - direct responses probe check (TTL-cached)

## Deployment/Dev Stack

- Active local stack: postgres + backend + frontend (`./scripts/dev_stack.sh up`).
- No worker startup in active scripts/manifests.

