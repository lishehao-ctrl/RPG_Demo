# Author / Play Stability Suite

This suite validates the real DB-backed RPG product from multiple angles:

- author generation stability
- publish handoff stability
- play session stability
- route selection stability
- branch coverage and terminal coverage
- judged fun / quality proxy metrics

## Entry points

- suite cases: `eval_data/author_play_stability_suite_v1.json`
- system runner: `scripts/run_author_play_stability.py`
- browser runner: `frontend/scripts/author_play_release_gate.mjs`
- release orchestrator: `scripts/run_author_play_release_gate.py`
- branch analysis: `scripts/branch_coverage.py`
- simulation engine: `scripts/simulate_playthrough.py`

## What it runs

Per game:

1. generate draft through real `/stories/generate`
2. fetch draft detail through `/stories/{story_id}/draft`
3. publish to `/stories/{story_id}/publish`
4. run an API-level author->play smoke chain
5. run multiple simulated playthrough strategies
6. compute branch / scene / terminal coverage
7. run `StoryQualityJudge` on generated transcripts

Default suite size:

- 3 games
- 2 prompt cases
- 1 seed case

## Output layout

- `reports/author_play_release/summary.json`
- `reports/author_play_release/browser_report.json`
- `reports/author_play_release/screenshots/`
- `reports/author_play_stability/summary.json`
- `reports/author_play_stability/per_game/<case_id>/generated_response.json`
- `reports/author_play_stability/per_game/<case_id>/draft.json`
- `reports/author_play_stability/per_game/<case_id>/system_result.json`

## Run

Start the local stack from the repo root:

```bash
./scripts/dev_stack.sh up
./scripts/dev_stack.sh ready
```

Then run the full release gate:

```bash
python scripts/run_author_play_release_gate.py
```

If you only want the system layer without the browser layer:

```bash
python scripts/run_author_play_stability.py
```

Useful tuning knobs:

```bash
python scripts/run_author_play_stability.py --max-steps 20 --branch-hunter-max-runs 6
```

When you need raw process logs during a long run:

```bash
./scripts/dev_stack.sh logs backend
./scripts/dev_stack.sh logs worker
./scripts/dev_stack.sh logs frontend
```

## Pass criteria

A game is treated as passing when all of the following hold:

- generation succeeds
- publish succeeds
- API-level play flow succeeds
- scene coverage >= 0.90
- conditional edge coverage = 1.0
- terminal edge coverage = 1.0
- completion rate = 1.0
- meaningful accept rate >= 0.90
- llm route success rate >= 0.80
- step error rate = 0.0
- judge overall avg >= 7.5
- judge prompt fidelity avg >= 7.0
- fun score avg >= 7.5
- fun score case min >= 6.5

## Notes

- `branch_hunter` prioritizes uncovered branch-trigger moves.
- `style_balanced` rotates strategy styles to reduce coverage bias.
- The suite is intentionally heavier than the normal smoke tests; it is designed for stability and quality assessment, not for quick CI feedback.
