# Play Feedback Backlog

## Status

This document started as the initial play-quality backlog snapshot on `2026-03-19`.

It is still useful as historical context, but several items are now completed or partially completed.

Completed or materially addressed:

- Priority 0: stronger visible axis / stance responsiveness
- Priority 1: hidden success and cost ledgers
- Priority 4: protagonist identity payload in play snapshot
- Priority 5: opening framing improvements
- Priority 6: additive frontend-facing play feedback fields

Partially addressed:

- Priority 2: reduced forced pyrrhic reliance through improved closeout handling
- Priority 3: ending reliability improved substantially, though benchmark coverage should remain active

Current active direction has moved from “make feedback exist” to:

- maintain interface discipline
- preserve benchmark credibility
- continue small-step play-quality improvements only when formal compare artifacts show real benefit

## Context

This backlog is derived from:

- `artifacts/benchmarks/subagent_playtest_7stories_20260319_063125.json`
- `artifacts/benchmarks/subagent_playtest_7stories_20260319_063125.md`
- `artifacts/benchmarks/subagent_playtest_7stories_20260319_063125_agent_report.md`

The benchmark shows:

- author generation is currently stable enough to stop being the main bottleneck
- play-mode mechanical credibility is now the dominant issue

Quant baseline from the 7-story run:

- `preview/author theme mismatch = 0`
- `story_frame_source = generated 7/7`
- `beat_plan_source = generated 7/7`
- `ending_source = generated 7/7`
- play ending distribution: `pyrrhic=6`, `unfinished=1`
- play unfinished rate: `0.143`

## Priority 0: Feedback Must Match Fiction

### Problem

The most consistent player complaint is that narration describes major public consequences, but visible feedback stays flat.

Common failures observed:

- `Public Panic`-like pressure bars do not move enough
- NPC stance bars remain at `0` after direct pressure, alliance-building, or exposure
- pyrrhic endings feel asserted by prose rather than earned by state

### Why It Matters

This is the current credibility bottleneck.
Players read the system as narratively alive but mechanically untrustworthy.

### Fix

- Increase deterministic axis and stance responsiveness.
- Guarantee every semantically valid turn produces:
  - at least one visible axis delta
  - and at least one relationship / stance consequence when NPCs are directly involved
- Make public-facing actions affect public-facing pressure bars more aggressively.

### Acceptance

- No playthrough where all stance bars remain flat after repeated direct NPC-targeted moves
- No playthrough where public-chaos fiction leaves the main public-pressure bar unchanged throughout

## Priority 1: Add Success and Cost Ledgers

### Problem

The runtime still infers too much from raw bars and sparse flags.
That makes `mixed` over-available and makes `pyrrhic` difficult to justify structurally.

### Fix

Add hidden durable ledgers in play state:

- success:
  - `proof_progress`
  - `coalition_progress`
  - `order_progress`
  - `settlement_progress`
- cost:
  - `public_cost`
  - `relationship_cost`
  - `procedural_cost`
  - `coercion_cost`

Update them deterministically from:

- affordance tag
- risk level
- off-route
- targeted NPCs
- truth/event unlocks
- beat milestone kind

### Acceptance

- Every accepted turn writes at least one ledger bucket
- `pyrrhic` can be explained as `success high + cost high`
- `mixed` can be explained as `success high + cost low`

## Priority 2: Reduce `turn_cap_force:pyrrhic`

### Problem

Several stories still finish through deterministic force rather than a cleaner judge-backed path.

Observed in the 7-story run:

- `blackout_ombudsman`
- `succession_courthouse`
- `curfew_market`

### Fix

- Open a `soft closeout window` before hard turn cap
- Prefer judge-backed `pyrrhic` whenever collapse does not dominate
- Let ledger evidence drive pyrrhic acceptance earlier

### Acceptance

- `turn_cap_force:pyrrhic <= 1 / 7`
- `judge:pyrrhic + judge_relaxed:pyrrhic >= 3 / 7`

## Priority 3: Eliminate `unfinished`

### Problem

`harbor_quarantine` still produced `unfinished` in scripted benchmark runs, even though one agent playthrough completed it.

### Interpretation

The system remains too sensitive to exact turn phrasing / action mix.

### Fix

- Use the new ledgers and soft closeout window to let near-complete stories resolve more reliably
- Ensure the final authored beat or late closeout window can always produce one legal ending unless collapse is blocked and success is genuinely absent

### Acceptance

- `unfinished_rate = 0` on the 7-story scripted benchmark

## Priority 4: Clarify Protagonist Identity

### Problem

At least one player report highlighted confusion about who the player actually is, especially when a cast NPC overlaps the protagonist role.

### Fix

- Add a pinned protagonist identity card in play:
  - `title`
  - `mandate`
  - `identity_summary`
- Make sure authored cast members do not read like duplicate protagonists

### Acceptance

- No agent report mentions “unclear who I am”

## Priority 5: Improve Opening Framing

### Problem

At least one agent called out the opening narration as templated and awkward.

### Fix

- Strengthen opening narration compiler
- Use protagonist identity and first beat pressure framing directly
- Avoid generic “you step into…” style intros when stronger domain language is available

### Acceptance

- Opening narration should specify:
  - who the player is
  - what the immediate mandate is
  - what the first pressure point is

## Priority 6: Frontend-Facing Feedback Additions

### Problem

Current frontend-visible feedback is too sparse to explain the simulation.

### Fix

Additive-only response fields:

- `protagonist`
- `feedback.ledgers.success`
- `feedback.ledgers.cost`
- `feedback.last_turn_axis_deltas`
- `feedback.last_turn_stance_deltas`
- `feedback.last_turn_tags`
- `feedback.last_turn_consequences`

Keep existing fields unchanged.

### Acceptance

- Frontend can show:
  - pinned protagonist card
  - recent turn consequence summary
  - explicit evidence of success/cost accumulation

## Suggested Execution Order

This ordering is now historical.

Current recommended order for new quality work is:

1. define the product-safe contract impact first
2. make a single focused runtime or compiler change
3. run formal benchmark compare on fixed seeds
4. only promote the candidate if compare passes and key metrics improve or hold

## Success Criteria

The pass is successful when:

- players feel the mechanics support the prose
- `unfinished_rate = 0`
- forced pyrrhic outcomes become rare
- at least 5/7 stories show obvious stance movement under direct social play
- no theme drift returns
