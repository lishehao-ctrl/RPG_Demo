# Verification

## Compile Check
```bash
python -m compileall app
```

## Test Suite
```bash
pytest -q
pytest -q client/tests
```

## Seed + Demo Smoke
```bash
python scripts/seed.py
pytest -q tests/test_demo_routes.py tests/test_seed_script.py
```

## Story Runtime Focused Checks
```bash
pytest -q tests/test_story_pack_api.py tests/test_story_engine_integration.py tests/test_story_runtime_decisions.py tests/test_fallback_narration.py tests/test_event_engine.py tests/test_ending_engine.py
```

## Balance Simulation (Playable Gate)
```bash
python scripts/simulate_runs.py --story-id campus_week_v1 --runs 200 --policy balanced --seed 42 --assert-profile playable_v1
python scripts/simulate_runs.py --story-id campus_week_v1 --runs 300 --policy random --seed 42 --assert-profile playable_v1 --assert-runs-min 200
```

## Cleanup Evidence Scans
```bash
rg -n "modules\\.auth|/auth/|google_|jwt_|X-User-Id|AUTH_TOKEN|DEFAULT_USER_ID|get_current_user" app tests client README.md docs --glob '!docs/verification.md'
rg -n "\\buser_id\\b" app/modules/session app/db/models.py tests/test_session_api.py docs/api.md
rg -n "input_text|ActionCompiler|modules\\.affection|modules\\.branch|classify_with_fallback|build_classification_prompt|build_narrative_prompt" app tests client
rg -n "if sess\\.story_id|non-story|non story" app tests
rg -n "MAP_|REQUIRES_|PACK_" app tests client docs
rg -n "token_budget|TOKEN_BUDGET_EXCEEDED|BUDGET_SKIPPED|session_token_budget_total|llm_preflight|total_cost|cost_estimate" app tests client
rg -n "\\bclassify\\(|\\bsummarize\\(|llm_model_summarize|llm_model_classify" app tests client docs
rg -n "branch_decision|branch_evaluation|affection_delta|route_type|decision_points|affection_timeline|affection_attribution|missed_routes|what_if" app tests client docs
rg -n "quest_state|QuestStage|QuestStageMilestone|stage_rewards|current_stage_id|recent_events" app tests docs app/modules/demo/static
rg -n "quest\\.milestones|milestones\\s*:\\s*list\\[QuestMilestone\\]" app tests docs
rg -n "StoryEvent|StoryEnding|StoryRunConfig|run_config|events|endings" app/modules/story app/modules/session tests docs
rg -n "run_state|run_ended|ending_outcome|run_summary|triggered_events_count|fallback_rate" app tests docs app/modules/demo/static
rg -n "simulate_runs|campus_week_v1" scripts examples docs README.md
rg -n "/demo/dev|/demo/play|/demo/bootstrap|LLM_UNAVAILABLE|REQUEST_IN_PROGRESS|X-Idempotency-Key" app docs tests app/modules/demo/static
rg -n "story_node_id|current_node_id: str|GET /stories|STORY_INVALID_FOR_PUBLISH|story picker" app docs tests app/modules/demo/static
rg -n "id=\\\"playPhase\\\"|id=\\\"sessionId\\\"|id=\\\"tokenTotals\\\"" app/modules/demo/static/index.play.html
rg -n "BLOCKED_MIN_MONEY|BLOCKED_MIN_ENERGY|BLOCKED_MIN_AFFECTION|BLOCKED_DAY_AT_LEAST|BLOCKED_SLOT_IN|FALLBACK_CONFIG_INVALID" app/modules/demo/static/play.js docs/frontend_handoff.md
rg -n "User\\(|Branch\\(|class User|class Branch" scripts/seed.py
```

Use these raw outputs in PR appendix (no hand-written counts).
