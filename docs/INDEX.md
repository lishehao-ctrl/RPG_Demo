# Documentation Index

This is the single entry point for project documentation.

## Canonical Documents
- [Story Runtime Architecture (v10 Hard Cut)](architecture_story_runtime.md)
- [StoryPack Spec (v10 Strict)](story-pack-spec.md)

## Operational References
- [API Surface](api.md)
- [Verification Commands](verification.md)

## Scope Notes
- Runtime and docs in this repo follow strict v10 behavior with no historical support paths.
- Story resolver ownership remains in `app/modules/session/service.py`.
- Quest/Goal progress is rule-based stage v1 (linear single-active) and stored in `session.state_json.quest_state`.
