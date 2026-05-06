# Architecture

This document explains the 9 mechanisms + 1 post-game system that make
up the Tiny Stories narrative engine, in the order they actually fire.
Read it linearly — each mechanism builds on the previous.

The reference for every claim here is `rpg_backend/narrative/engine.py`.
If a behavior in this doc disagrees with the prompt strings or scheduler
functions in that file, **the file is the truth** — file an issue.

---

## 0. Two-stage architecture

Every session has two phases:

| Phase | Trigger | LLM calls | Mechanisms |
|---|---|---|---|
| **Opening generation** | template creation | 1 | cast / player roles / failure conditions / inter-NPC leverage network |
| **Per-turn play** | each `advance_turn` | 1-3 | NPC scheduling / twist / consequences / inventory / role / diary / oracle |
| **Finalize** | session reaches budget OR judge_failure trips | 3 (parallel-ish) | ending / highlights / branches |

The opening output is **persisted as a Template** that can be re-played
by the same or different players. A single template seeds many sessions.

---

## 1. Opening — `generate_opening`

Single LLM call with `_OPENING_SYSTEM_PROMPT`. Produces:

- **`title`** — story title
- **`advisor_persona`** — physically-separated friend who can be reached by phone
- **`cast`** (3-5 NPCs) — each has:
  - `hidden_objective` — what they really want (gauntlet only)
  - `leverage_over_player` — what they hold over the player
  - `leverages_over_other_npcs` — N×N political network (≥ 4 edges per 3-NPC cast, ≥ 6 for 4-NPC; sparse-network retry kicks in)
- **`player_role_options`** (3-5 cards) — each is a different identity the player can wear:
  - `public_persona` (what NPCs see)
  - `hidden_objective` (only player + LLM see)
  - `leverages_over_npcs` (counter-cards)
  - `starting_assets` (concrete items the player walks in holding)
- **`player_goals`** + **`failure_conditions`** (gauntlet only)
- **`opening_passage`** + 3 starting `options`

### Why this shape

The mechanism stack below all depends on these structured fields. Without
`hidden_objective` per NPC, the engine can't schedule "active push" turns;
without `leverages_over_other_npcs`, the reversal twist has nothing to
ignite; without `player_role_options`, repeat-play has no axis of variation.

---

## 2. Per-turn pipeline — `advance_turn`

Single LLM call with `_TURN_SYSTEM_PROMPT`, but the user_payload going
into that call is assembled by a sequence of deterministic schedulers
that each contribute one structured field:

```
advance_turn(history, player_action, player_diary, ...)
   │
   ├─ stage_phase = _stage_for(turn_index, turn_budget)
   │     hook → pressure → reversal → climax → pre_finale
   │
   ├─ npc_agenda  = _pick_npc_agenda(stage_phase, cast, history)
   │     gauntlet only. picks 0-2 NPCs that should ACTIVELY push their
   │     hidden_objective this turn (probe / pressure / leverage / reveal /
   │     betray / ally). Stale NPCs (no recent non-steady shift) get
   │     priority so airtime distributes.
   │
   ├─ twist_directive = _pick_twist_directive(stage_phase, cast, role)
   │     reversal stage only. forces a structural inflection: secret
   │     inter-leverage revealed / betrayal realignment / persona crack /
   │     hidden NPC arrival / external event intrusion.
   │
   ├─ current_inventory = compute_current_inventory(starting_assets, history)
   │     walk-on-read: starting_assets + Σ(narrator.inventory_delta).
   │     Single source of truth, never desyncs from message stream.
   │
   ├─ recent_consequences = _summarize_recent_consequences(history, cast)
   │     {last_player_action, npc_pulse_trend per NPC over last 4 beats,
   │      unused_leverage NPCs whose card hasn't fired yet}
   │
   └─ player_role + player_diary + player_goals threaded as-is
        ↓
   LLM (with _TURN_SYSTEM_PROMPT) returns:
   {
     passage,
     options[3] with [intent tag] prefix,
     npc_pulse[] (each with shift + reason),
     inventory_delta (optional)
   }
```

Every input field has a corresponding rules section in the prompt. The
prompt is the contract between scheduler outputs and LLM behavior — if
the LLM ignores a signal, the fix is almost always in the prompt section.

---

## 3. Game-over judging — `judge_failure`

Runs after every turn in gauntlet mode. Cheap LLM call (≤400 tokens)
that reads the last 5 messages + the failure_conditions list, returns:

```json
{ "triggered": bool, "matched_condition_label": str, "reason": str }
```

Conservative bias: returns `triggered: false` when unsure. Spec target
is 80%+ of cautious players never trigger. When `triggered: true`, the
service skips standard finale and calls `synthesize_early_ending` which
forces an ending label from the collapsed-tier pool: `失控 / 反噬 / 破碎 / 沉沦`.

---

## 4. Player resources — diary + oracle

Two ways the player extends their own agency beyond pick-an-option:

### `player_diary` (free)
Optional inner monologue submitted alongside the action. NPCs cannot
read it. The LLM uses it to calibrate inner-state register of the
narration (the "演 vs 真" gap). Persisted on player message; visible
on scrollback as a private record of psychological journey.

### `ask_advisor_oracle` (pays 1 turn from session.turn_budget)
A separate LLM call (`_ORACLE_SYSTEM_PROMPT`) where the advisor sees
**privileged info** — full cast incl. hidden_objective + leverage + NPC
pulse trend + failure_conditions + current_inventory. Has to give a
mood-appropriate vague-but-useful hint without leaking field names
verbatim ("我读出来" not "她的 hidden_objective 是…"), and must hand
the decision back to the player at the end.

The cost is real: `repository.decrement_turn_budget()` runs only after
the LLM call succeeds, so failed oracle calls are free.

---

## 5. Finalize — three post-game LLM calls

When session reaches `turn_budget` (or judge_failure trips), three
separate calls run in sequence. All three are non-fatal — empty results
on failure don't block the ending screen.

### `synthesize_ending` (or `synthesize_early_ending`)
Generates the closing passage (400-600 chars), label from the closed
15-ending pool, and a first-person subtitle (≤ 25 chars, screenshot-
friendly). Off-pool labels get snapped to the closest match via
`_normalize_ending_label`.

### `synthesize_highlights` (5 cards)
LLM picks 5 pivotal narrator beats from the run, each with:
- `beat_ord` — ord of the actual beat
- `headline` (≤ 30 chars, screenshot-friendly)
- `body_excerpt` — verbatim 1-3 sentences from that beat
- `why_pivotal` (≤ 80 chars, mechanics-aware)

Prompt explicitly favors beats with inventory_delta / pulse=broken /
twist directive / leverage plays — **events**, not setup.

### `synthesize_branches` (2-3 cards)
The post-game replay hook. LLM picks 2-3 pivot turns where alternate
options would lead to a **different ending label** (validated against
ENDING_LABELS pool, rejected if same as actual ending). Returns:
- `pivot_beat_ord`
- `chosen_path_summary` (what player did)
- `alternate_path_summary` (what they could have done)
- `alternate_ending_label` + tier (server-side derived from label)
- `rationale` (1-2 sentences in "我推测..." voice)

Retries once if first attempt returns < 2 branches. Hardcore players'
replay value depends on this.

---

## 6. The closed ending pool

15 labels in `ENDING_LABELS`, mapped to 3 tiers via `_LABEL_TIER`:

| Tier | Labels |
|---|---|
| **victory** | 复仇 · 和解 · 自由 · 救赎 · 回归 · 夺回 |
| **compromised** | 孤狼 · 共谋 · 牺牲 · 同谋 · 决裂 |
| **collapsed** | 沉沦 · 失控 · 反噬 · 破碎 |

Closed pool is intentional. With ~5 sessions per template the same label
should repeat — that collision IS the social-comparison mechanic
("you got 复仇? I got 自由 from the same opening!").

`tier_for_label(label)` is the public API for color-grading the UI
ending splash and the branch alternate-ending chips.

---

## 7. Frontend mirror

The frontend in `frontend2/` is a thin React 19 + TypeScript shell
that mirrors `rpg_backend/narrative/contracts.py` into
`frontend2/src/api/contracts.ts`. The play page (`play-page.tsx`,
~2400 lines) renders all the structured signals:

- `StoryBeat` → narration with intensity gradient (calm/rising/peak)
  derived from pulse + delta + stage
- `pulseStrip` → chips with shift color + reason line
- `optionBtn` → parses `[intent tag]` prefix → colored chip + body text
- `roleBanner` → live `current_inventory` + role's leverages and assets
- `EndingScreen` → ending splash + highlight reel + branches grid
- `AdvisorSidechat` with explicit "🔮 用 1 回合换情报" pay-budget button
- `StageProgressBar` → 5-segment dramatic-arc visualization
- Pulse legend (5 shift type meanings)

All frontend state lives in React `useState`; no global store. Hash-
based routing keeps the deploy simple.

---

## 8. Test surface

`tests/` mostly covers legacy author/v2/v3 modules. The `narrative/`
module's test surface is currently **LLM smoke tests** at the
script-and-eyeball level — see `/tmp/full_chain_sim.py` and
`/tmp/user_persona_sim.py` for examples.

This is a known gap. Adding deterministic unit tests for the schedulers
(no LLM) is a high-ROI contribution opportunity — `_pick_npc_agenda`,
`_pick_twist_directive`, `compute_current_inventory`,
`_summarize_recent_consequences`, `_parse_branches` are all pure
functions with structured I/O.

---

## 9. Performance notes

Per session economics on a qwen3.6-flash-class model:

| Op | LLM calls | Approx time | Approx cost |
|---|---|---|---|
| `generate_opening` | 1 (with up to 2 retries on density) | 12-20s | $0.05 |
| `advance_turn` | 1 | 5-8s | $0.03 |
| `judge_failure` (per turn) | 1 | 3-5s | $0.01 |
| `ask_advisor` | 1 | 3-5s | $0.01 |
| `synthesize_ending` + `_highlights` + `_branches` | 3 | 12-18s | $0.10 |
| **Full 12-turn session** | ~16-20 | 90-150s | ~$0.50-$0.60 |

If you're running a public deployment, **per-user-per-day budget caps**
are the single highest-priority thing to add — a single user can rack
up double-digit dollars before noticing.

---

## 10. Where to start contributing

Highest-leverage areas if you want to PR:

1. **Schedulers as pure-function unit tests** (no LLM) — biggest
   reliability win, lowest barrier
2. **Provider abstraction** — current `gateway.py` assumes OpenAI
   `responses_create` shape; an explicit "OpenAI compatible" /
   "Anthropic compatible" dispatch would broaden the user pool
3. **Frontend i18n** — strings are hard-coded Chinese; an i18n layer
   would unblock English / other locales
4. **Streaming narration** — currently `passage` arrives as a single
   blob; a typewriter-effect would dramatically improve perceived
   responsiveness
5. **Persistent HUD** — surface the `current_inventory` + discovered
   inter-NPC leverage map in a sidebar instead of just the role banner

Open an issue describing your plan before starting structural work —
the prompt-driven design has subtle invariants that aren't obvious
from the code alone.
