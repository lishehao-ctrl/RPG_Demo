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

## Story Runtime Focused Checks
```bash
pytest -q tests/test_story_pack_api.py tests/test_story_engine_integration.py tests/test_story_runtime_decisions.py tests/test_fallback_narration.py
```

## Cleanup Evidence Scans
```bash
rg -n "input_text|ActionCompiler|modules\\.affection|modules\\.branch|classify_with_fallback|build_classification_prompt|build_narrative_prompt" app tests client
rg -n "if sess\\.story_id|non-story|non story" app tests
rg -n "MAP_|REQUIRES_|PACK_" app tests client docs
rg -n "token_budget|TOKEN_BUDGET_EXCEEDED|BUDGET_SKIPPED|session_token_budget_total|llm_preflight|total_cost|cost_estimate" app tests client
rg -n "\\bclassify\\(|\\bsummarize\\(|llm_model_summarize|llm_model_classify" app tests client docs
rg -n "branch_decision|branch_evaluation|affection_delta|route_type|decision_points|affection_timeline|affection_attribution|missed_routes|what_if" app tests client docs
rg -n "quest_state|QuestStage|QuestStageMilestone|stage_rewards|current_stage_id|recent_events" app tests docs app/modules/demo/static
rg -n "quest\\.milestones|milestones\\s*:\\s*list\\[QuestMilestone\\]" app tests docs
```

Use these raw outputs in PR appendix (no hand-written counts).
