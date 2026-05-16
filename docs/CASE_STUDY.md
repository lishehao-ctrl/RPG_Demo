# Tiny Stories Case Study

## Problem

Most LLM story demos stop at generated prose. Tiny Stories explores a more
product-shaped question: can open-ended generation become a playable,
inspectable runtime with state, roles, replay, and evaluation hooks?

## Product Loop

1. A player types one premise.
2. The compiler turns it into cast, role cards, hidden goals, leverage, failure
   conditions, and an opening scene.
3. The player runs a bounded 8-20 turn session with choices, free-form actions,
   advisor help, inventory shifts, and consequence tracking.
4. The ending compiler turns the actual run history into a label, passage,
   highlights, alternate branches, and a shareable replay.
5. A reviewer can open the inspector path to see the state machine behind the UI.

## Why It Is More Than A Chatbot

| Mechanism | Product effect | Engineering surface |
| --- | --- | --- |
| Template/session split | Many players can fork the same story shell and compare endings. | `rpg_backend/narrative/repository.py` |
| Player role contract | The user plays a strategic character with public and private goals. | `PlayerRole`, `PlayerGoal`, `starting_assets` |
| Deterministic turn scaffolding | The model writes inside a paced game frame. | `rpg_backend/narrative/engine.py` |
| Advisor side-channel | Help is contextual but cannot silently alter story state. | `ask_advisor`, advisor message table |
| Replay and fork CTA | A finished run becomes shareable and replayable. | `PublicReplayResponse.template_id` |
| Reviewer mode | Admissions/recruiting reviewers can inspect runtime decisions quickly. | `frontend2/src/pages/portfolio/` |

## Safety And Operations

- Authoring and write routes require a real session; anonymous visitors can still
  browse, fork, and play public stories.
- Public deployments can disable expensive legacy authoring endpoints with
  `APP_PUBLIC_DEMO_AUTHORING_ENABLED=false`.
- LLM calls pass through per-IP and per-user/default-actor daily quotas.
- Migration code archives incompatible rows before removing them from active
  tables; startup should not silently delete user data.
- Product metrics emit structured log events for sessions started, sessions
  completed, advisor usage, and replay views.

## Current Limits

This is a portfolio-grade AI product system, not a validated consumer game.
Repeat-play demand, organic sharing, and retention have not been proven. The
next validation step is a small real-user playtest and the report template in
`docs/playtest_report.md`.
