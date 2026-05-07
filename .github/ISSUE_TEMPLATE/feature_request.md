---
name: Feature request
about: Suggest a new mechanism, integration, or UX improvement
title: '[feat] '
labels: enhancement
assignees: ''
---

## The problem

<!-- What player or contributor frustration does this solve? Be
specific. "It feels off" isn't actionable; "after turn 6 the player
can't tell which NPC is broken" is. -->

## Proposed direction

<!-- One paragraph. Don't over-design — the maintainers may have
context about subtle invariants that change the right shape. -->

## Alternatives considered

<!-- Other ways to solve this problem you ruled out, and why. -->

## Scope check

- [ ] This requires changes to `narrative/contracts.py` (new types)
- [ ] This requires changes to `narrative/engine.py` (prompt or scheduler)
- [ ] This requires a database migration (`narrative/repository.py`)
- [ ] This is purely frontend (`frontend2/`)
- [ ] Not sure yet

If multiple boxes are checked, please open a discussion before
sending a PR — the cross-layer pieces are subtle.
