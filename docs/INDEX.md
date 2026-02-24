# Documentation Index

This is the single entry point for project documentation.

## Canonical Documents
- [Story Runtime Architecture (v10 Hard Cut)](architecture_story_runtime.md)
- [StoryPack Spec (v10 Strict)](story-pack-spec.md)
- [Story Authoring Spec (ASF v4)](story-authoring-spec.md)
- [Code Structure & Ownership](code-structure.md)
- [LLM Boundary Guide (ZH)](architecture-llm-boundary-zh.md)
  - Chinese boundary matrix for LLM vs deterministic engines
  - Play/Author/Compile deterministic flow diagrams

## Operational References
- [API Surface](api.md)
- [Verification Commands](verification.md)
  - includes UI screenshot capture workflow (`scripts/capture_demo_screenshots.py`)
- [Frontend Handoff Guide](frontend_handoff.md)
  - includes `Stable Selector Contract`
  - includes stable `data-testid` selector contract for `/demo/play` and `/demo/dev`
- [Story Author Mode Guide (ZH)](author-mode-zh.md)
  - Chinese author-facing usage guide for `/demo/author`
- Demo entrypoints:
  - user: `/demo/play`
  - developer: `/demo/dev`
  - author: `/demo/author`
  - story picker data: `GET /stories`

## Scope Notes
- Runtime and docs in this repo follow strict v10 behavior with no historical support paths.
- Story runtime orchestration is centered in `app/modules/session/service.py`, with extracted helpers under `app/modules/session/*`.
- Quest/Goal progress is rule-based stage v1 (linear single-active) and stored in `session.state_json.quest_state`.
- Run lifecycle state (events/endings/timeout) is stored in `session.state_json.run_state`.
