# Runtime Status Matrix

This file maps `docs/architecture.md` sections to current implementation status.

## Implemented
- Accept-All runtime loop (Pass A + Pass B) with deterministic outcome resolution.
- `fail_forward` mandatory linter validation.
- Global fallback routing with `global.help_me_progress`/`global.clarify`.
- Session idempotency by `client_action_id` replay.
- Story draft/publish/get APIs.
- Session create/get/step APIs.
- Sample story pack and canary tests.
- Deterministic story generator (`/stories/generate`) with lint + bounded regenerate attempts.

## Placeholder
- OpenAI LLM provider is a placeholder and not enabled in offline-first mode.

## Planned
- LLM-backed generator variant (pluggable, deterministic generator remains default).
- Stronger narration leak guards and telemetry expansion.
