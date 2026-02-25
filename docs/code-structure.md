# Code Structure & Ownership

## Runtime Path (kept)
1. Story packs (v10 strict) are read from DB via `GET /stories*`.
2. Session state and step execution run through `app/modules/session/*`.
3. LLM is used only in play runtime path (selection + narration), never for deterministic state transitions.

## Story Modules
- `app/modules/story/router.py`: HTTP layer for validate/list/get.
- `app/modules/story/schemas.py`: StoryPack and API schemas.
- `app/modules/story/service_api.py`: validation helpers for runtime pack checks.
- `app/modules/story/validation.py`: structural rules.

## Session Modules
- `app/modules/session/service.py`: orchestration entry.
- `app/modules/session/runtime_deps.py`: dependency assembly.
- `app/modules/session/runtime_orchestrator.py`: runtime step orchestration.
- `app/modules/session/story_runtime/phases/*`: deterministic step phases.

## Demo Modules
- `app/modules/demo/router.py`: `/demo/play`, `/demo/dev`, `/demo/bootstrap`.
- `app/modules/demo/static/play.*`: player UI.
- `app/modules/demo/static/dev.*`: developer diagnostics UI.

Author UI and Author API modules were removed in the hard-cut cleanup.
