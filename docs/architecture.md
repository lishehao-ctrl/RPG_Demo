# Architecture

## System Shape

The backend is the only active server-side runtime component. It calls the upstream Responses API directly with `AsyncOpenAI.responses.create`.

Active abstractions:

- `ResponsesTransport`
- `PlayAgent`
- `AuthorAgent`
- `ResponseSessionStore` (provider cursor persistence)

Removed from active path:

- internal LLM worker service
- worker provider/client/gateway transport
- route/narration split chains as the primary play abstraction

## Play Mode

Play Mode is single-agent at the LLM boundary and deterministic for resolution:

1. text input: `interpret_turn` (PlayAgent)
2. backend deterministic resolution/outcome/effects
3. `render_resolved_turn` (PlayAgent)

Button input skips interpretation and directly renders resolved output.

Public API shape is unchanged. Admin/dev timeline fields are single-agent:

- `agent_model`
- `agent_mode` (`responses`)
- `response_id` (per call)
- `reasoning_summary` (debug only)

## Author Mode

Author Mode keeps LangGraph topology:

- `generate_story_overview`
- `plan_beats`
- `generate_beat_outline`
- `materialize_beat`
- `beat_lint`
- `assemble_story_pack`
- `normalize_story_pack`
- `final_lint`
- `review_ready | workflow_failed`

LLM nodes (`generate_story_overview`, `generate_beat_outline`) both use `AuthorAgent` + Responses transport.

Deterministic nodes remain deterministic:

- `plan_beats`
- `materialize`
- `lint`
- `normalize`

`final_lint` failure still routes directly to `workflow_failed` (no repair branch).

## Cursor Persistence

Provider cursor reuse is persisted in table `response_session_cursors`:

- key: `(scope_type, scope_id, channel)`
- fields: `model`, `previous_response_id`, `updated_at`

Channels:

- Play: `play_agent`
- Author: `author_overview`, `author_outline`

Cursor invalidation behavior:

- on invalid/expired cursor error, clear stored cursor
- retry once without `previous_response_id`
- save latest `response.id` on success

## Config Contract

Only active LLM config:

- `APP_RESPONSES_BASE_URL`
- `APP_RESPONSES_API_KEY`
- `APP_RESPONSES_MODEL`
- `APP_RESPONSES_TIMEOUT_SECONDS` (`20.0`)
- `APP_RESPONSES_ENABLE_THINKING` (`false`)

No active multi-model route/narration/generator split.

## Observability

Gateway naming is standardized to `responses`.

- LLM call health by gateway mode: `responses | unknown`
- readiness health aggregation: `backend` + `responses`
- runtime stages: `interpret_turn`, `render_resolved_turn`
