Read this first:
- `/Users/lishehao/Desktop/Project/RPG_Demo/specs/backend/2026-03-16-author-stability-refactor/SPEC.md`

Implement the backend-only pass described there.

Requirements:
- derive your own execution plan from the spec
- keep `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/main.py` API behavior compatible
- extract compiler and quality responsibilities out of `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py`
- add structured source telemetry and quality reasons for `story_frame`, `beat_plan`, `route_affordance`, and `ending`
- add or update focused tests
- run targeted validation plus a 5-run full-generation A/B test
- update this file when done:
  `/Users/lishehao/Desktop/Project/RPG_Demo/specs/backend/2026-03-16-author-stability-refactor/OUTPUT.md`
- keep frontend untouched

Do not:
- broaden scope into frontend or play runtime
- replace deterministic compiler work with larger prompt restriction lists
- change public response shapes unless the spec explicitly requires backend state telemetry
- stop after analysis

When finished:
- update `OUTPUT.md`
- reply in Chinese with a short summary of what changed
