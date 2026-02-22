# Frontend Handoff Guide

## Positioning
Gameplay logic stays in backend runtime.
Frontend clients should remain thin:
- collect input (`choice_id` or `player_input`),
- render backend payloads,
- do not re-implement mapping/gating/fallback/event/ending logic.

## Stable Endpoints
- `GET /stories`
- `POST /sessions`
- `GET /sessions/{id}`
- `POST /sessions/{id}/step`
- `POST /sessions/{id}/snapshot`
- `POST /sessions/{id}/rollback`
- `POST /sessions/{id}/end`
- `GET /sessions/{id}/replay`

## Internal Demo Variants
- `GET /demo/play`: player-facing UI.
- `GET /demo/dev`: developer diagnostics UI.
- `GET /demo/author`: ASF v4 authoring wizard.
- `GET /demo/bootstrap`: shared frontend bootstrap config.

## Stable Selector Contract
Automation and screenshot tooling should target `data-testid` markers.

Play selectors:
- `data-testid="play-shell"`
- `data-testid="play-story-select"`
- `data-testid="play-main"`
- `data-testid="play-stats-panel"`
- `data-testid="play-quest-panel"`
- `data-testid="play-run-panel"`
- `data-testid="play-impact-panel"`
- `data-testid="play-replay-drawer"`
- `data-testid="play-busy-indicator"`

Dev selectors:
- `data-testid="dev-shell"`
- `data-testid="dev-session-panel"`
- `data-testid="dev-pending-panel"`
- `data-testid="dev-llm-trace-panel"`
- `data-testid="dev-layer-inspector-panel"`
- `data-testid="dev-state-panel"`
- `data-testid="dev-timeline-panel"`
- `data-testid="dev-replay-panel"`

Author selectors:
- `data-testid="author-shell"`
- `data-testid="author-tab-author"`
- `data-testid="author-tab-debug"`
- `data-testid="author-debug-toggle"`
- `data-testid="author-main-flow"`
- `data-testid="author-next-steps"`
- `data-testid="author-debug-panel"`
- `data-testid="author-stepper"`
- `data-testid="author-step-world"`
- `data-testid="author-entry-spark"`
- `data-testid="author-entry-ingest"`
- `data-testid="author-seed-input"`
- `data-testid="author-source-input"`
- `data-testid="author-auto-apply-hint"`
- `data-testid="author-step-characters"`
- `data-testid="author-step-plot"`
- `data-testid="author-step-scenes"`
- `data-testid="author-step-action"`
- `data-testid="author-step-consequence"`
- `data-testid="author-step-ending"`
- `data-testid="author-step-review"`
- `data-testid="author-global-brief"`
- `data-testid="author-layer-intent-panel"`
- `data-testid="author-assist-panel"`
- `data-testid="author-writer-turn-feed"`
- `data-testid="author-turn-card"`
- `data-testid="author-playability-panel"`
- `data-testid="author-playability-blocking"`
- `data-testid="author-playability-metrics"`
- `data-testid="author-llm-feedback"`
- `data-testid="author-patch-preview"`
- `data-testid="author-form"`
- `data-testid="author-validate-panel"`
- `data-testid="author-compile-preview"`
- `data-testid="author-playtest-panel"`

Compatibility markers retained:
- `data-testid="author-step-advanced"`

## Author Workflow (ASF v4)
1. Choose `Spark` or `Ingest` entry.
2. Click `Parse All Layers`; assist patches are auto-applied in UI.
3. Continue with assist actions; all v4 assist tasks auto-apply by default.
4. Review `Writer Turn Feed` and `Next Steps` on Author tab.
5. Use `Undo Last Apply` to rollback the latest assist batch.
6. Open `Show Debug` only when you need raw suggestions/patches/diagnostics.
7. Validate (with playability gate) -> Compile -> Save -> Playtest.

## Dev Layer Inspector
`/demo/dev` includes Layer Inspector panel powered by:
- `GET /sessions/{id}/debug/layer-inspector`

Panel intent:
- show each step as layered snapshots,
- highlight fallback/mismatch/event-heavy turns,
- provide raw refs (`action_log_id`, `llm_step_id`) for backend trace correlation.

Guardrail:
- endpoint is available only when `ENV=dev`, otherwise `404 DEBUG_DISABLED`.
