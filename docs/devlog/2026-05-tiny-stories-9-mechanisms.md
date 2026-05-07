# Tiny Stories design notes — turning an LLM into an interactive-drama director with 9 prompt layers

> This is the design doc for [Tiny Stories](https://github.com/...).
> It's about **why** the engine is shaped this way, not a code tutorial.
> If you only want the code, jump to [ARCHITECTURE.md](../../ARCHITECTURE.md).

> Languages: **English** · [中文](./2026-05-tiny-stories-9-mechanisms.zh.md)

---

## The core tension

LLMs are great at writing prose. But the LLM-driven interactive-fiction
products in market today (AI Dungeon, Character.AI…) all share one
weakness:

**The player is an audience, not the protagonist.**

You write a sentence, the LLM gives you a paragraph of polished prose.
You write another, it gives another. Your "choices" sit in the prompt
as one line of free input, and the LLM mostly drives forward on its
own stylistic preferences and the running history pattern. The result:

- Every paragraph reads fine
- But what you do barely matters; the story walks the same line either way
- After 5 minutes you notice, and you quit

Tiny Stories is my attempt at a concrete sub-problem: **make a
12-turn drama compact enough that a player can actually feel "my
choice changed something."**

To get there, I stacked 9 mechanisms. Below is the design rationale.

---

## Opening move: why 12 turns?

Not 100. Not infinite.

- **12 turns ≈ 15 minutes** — the mobile-era attention ceiling
- **Long enough for a full arc**: hook → pressure → reversal → climax
  → pre_finale, 5 stages × 2-3 turns each
- **Short enough to replay** — finish a run, immediately start another
  with a different role; you don't get the "already saw this" fatigue
- **Short enough to share** — text a friend a link, they finish in
  15 min, they reply "I got X, what did you get?"

This form factor decides everything else. At 100 turns, the mechanism
stack overloads. At 5 turns, the dramatic arc has no room to breathe.

---

## 9 mechanisms — why these 9

Each layer maps to one specific player question:

### 1. NPC scheduling (`_pick_npc_agenda`)
**Player question:** "Why is X talking to me this turn instead of Y?"
**Mechanism:** every NPC has a `hidden_objective`. In gauntlet mode, a
scheduler decides per stage_phase **which NPC should actively push this
turn** (probe / pressure / leverage / reveal / betray / ally). Stale
NPCs (recent npc_pulse all `steady`) get bumped to the front, so
airtime distributes evenly.

Without scheduling, the LLM lets one NPC hog the spotlight while the
rest become wallpaper.

### 2. Forced reversal (`_pick_twist_directive`)
**Player question:** "Will the plot actually turn, or is the LLM just
ramping pressure forever?"
**Mechanism:** during the reversal stage (~turn 6) the scheduler
injects a forced twist directive — `secret_inter_leverage_revealed` /
`betrayal_realignment` / `player_persona_crack` / `hidden_npc_arrival`
/ `external_event_intrusion`. The LLM has to honor it; pure escalation
is not allowed.

LLMs by default ramp pressure. Structural reversal has to be
hard-coded.

### 3. Player-as-cast (`PlayerRole`)
**Player question:** "If I replay the same seed, will it feel the same?"
**Mechanism:** every template has 3-5 player role cards. Each is a
different identity (`public_persona` what others see, `hidden_objective`
what you actually want, `leverages_over_npcs` your counter-cards,
`starting_assets` what you walk in holding). Same seed + different
role = a fundamentally different story.

This is what turns "replayability" from rhetoric into structure. Single
role, you're just watching the LLM write different endings; multi-role,
you're re-living the situation as a different person.

### 4. N×N inter-NPC leverage (`leverages_over_other_npcs`)
**Player question:** "What's between the NPCs themselves? Will they
turn on each other?"
**Mechanism:** each NPC may hold leverage not just over the player but
over other NPCs too. The cast becomes a 4-9 edge political network. The
LLM can have NPCs threaten each other, form temporary alliances, or
flip on cue — **with structural justification underneath.**

This shifts the player from "vs N NPCs" to "finding position in an
N×N network" — you can play them off each other instead of bashing
head-on.

### 5. Inventory accumulation
**Player question:** "Does the system remember what I picked up?"
**Mechanism:** every narrator beat may emit an `inventory_delta`
(added/removed). Walk-on-read:
`current_inventory = starting_assets + Σ(narrator deltas)`. Never
desyncs, because there is no cached state.

Each turn the LLM sees everything in the player's hands, so an option
like "show them the X" has actual ground to stand on.

### 6. Advisor oracle (pay-1-turn)
**Player question:** "Can I just ask 'what does this NPC actually want'?"
**Mechanism:** the advisor is normally a casual phone friend. The
player can choose to **spend 1 turn budget** to put the advisor into
oracle mode — they see every NPC's `hidden_objective` + leverage +
the player's inventory + failure_conditions, and reply with a
vague-but-useful hint.

The cost is real: `turn_budget` decrements, the story compresses.
The player makes a meta-resource decision: "do I cash this in?"

### 7. Player diary (inner monologue)
**Player question:** "Does the LLM know what I'm actually thinking?"
**Mechanism:** each turn the player can optionally write 30-200 chars
of diary. NPCs **can't see it**. The LLM uses it to calibrate the
inner-state register of the narration (the gap between "the performed
self" and "the true self"). After the run, scrolling the 12 diary
entries = a psychological journal.

### 8. Three tiers + 15-label closed pool
**Player question:** "Did I win or lose?"
**Mechanism:** 15 fixed ending labels mapped to 3 tiers (victory /
compromised / collapsed). The LLM must pick from the pool; off-pool
labels snap to the closest. With 5 people playing the same template,
labels collide — **and that collision is the social-comparison hook**
("you got 'reconcile'? I got 'backfire' on the same seed!").

### 9. Failure judge + early collapse
**Player question:** "If I screw up, can I actually fail?"
**Mechanism:** in gauntlet mode, every turn runs a failure-judge LLM
call against the recent history + failure_conditions. If triggered →
forced early ending, label restricted to the collapsed-tier pool.

This makes "failure" actually fail, instead of "well, let me just take
one more step."

### Bonus post-game — Highlight reel + Branches
**Player question:** "What did I just live through?"
**Mechanism:** after the run the LLM picks 5 pivotal beats (headline +
body excerpt + why_pivotal), then picks 2-3 **paths you didn't take**
(pivot turn + alternate option + alternate ending label). Highlights =
"what you did," Branches = "what you didn't" — a clean closing loop.

---

## Cross-layer contracts: why the 9 layers don't fight each other

Each mechanism in isolation isn't complex. The challenge is making
9 of them stackable without conflict.

I leaned on 3 principles:

**1. Single source of truth (Pydantic contracts)**

Every cross-module / cross-layer payload uses Pydantic types in
`narrative/contracts.py`. The frontend TypeScript is a mirror; any
backend change must update the frontend in the same PR. LLM outputs
are validated against this layer; non-conforming fields get dropped
by the parser.

This eliminates the classic "frontend/backend contract drift" trap.

**2. Walk-on-read, no cached intermediate state**

`current_inventory` is not stored — each `advance_turn` walks the
history and recomputes it. `pulse_trend` is the same — recomputed each
turn from the last 4 narrator beats.

Cost: O(N) per turn. Win: it never desyncs, and the question "what's
the source of truth for value X" always has one clear answer.

**3. The prompt is the contract**

The behavior of each mechanism isn't "trained" — it's a few lines of
hard rules in `_TURN_SYSTEM_PROMPT`:

```
**Forced reversal (twist_directive) — appears only in reversal stage**:
when user_payload contains `twist_directive: {kind, hint}`, this turn
IS the reversal pivot…
the passage MUST genuinely honor the specified twist kind…
```

When debugging a mechanism that misbehaves, 90% of the fix is adding
one "⚠️ MUST" line in the prompt rather than touching Python.

---

## What I learned

Building this gave me a few visceral takeaways about prompt-driven
LLM apps:

**1. The LLM is a black box, but structured fields anchor it**

Free-text prompts give uncontrollable output. **A JSON output schema
plus per-field hard rules** gets you 90% reliable output. Use retries
to cover the remaining 10%.

**2. LLM-as-player is dirt-cheap mechanism testing**

I ran dozens of 12-turn LLM-as-cooperative-player simulations to
verify the 9 layers don't fight each other. This kind of validation
**costs $thousands and weeks with real users**; LLM simulation costs
$tens and hours.

But: **LLM players are extremely cooperative.** They follow the persona
strictly. Real users skip the diary, pick randomly, quit at turn 5.
LLM simulation only validates "do the mechanics work," not "will users
like it."

**3. Persona-driven LLM players surface real problems**

Later I ran 3 sonnet subagents simulating 3 "new user archetypes"
(casual / hardcore / skeptic) and had them write independent UX
reviews. The skeptic's sharpest feedback: **"I feel like an audience,
not the protagonist. Whether I pick option 0 or option 1, the
narrative drifts the same way."** That's a soul-level product
diagnosis I couldn't have written from 100 internal test cases.

---

## What I haven't solved

Honest assessment: after 9 mechanisms + 2 visual polish rounds + 3
regression-test rounds, **the deepest product problem is still open**:

> Skeptic: "My input is decorative."

The mechanisms are all firing correctly on the backend — npc_pulse is
shifting, inventory delta is accumulating, branches are generating.
But the **narrative weight of player options is too light**. The LLM
is mostly driven by stage scheduler / agenda / twist; player choice is
a trigger, not a director.

A skeptic who picks `[0]` every turn still gets the LLM's preset
arc, because the LLM is acting on stage targets and what you picked
matters less than where the stage says it's headed.

This is the next-version core problem. Likely fix: rewrite the turn
prompt so that "option 0 / 1 / 2 MUST lead to fundamentally different
narrative paths," or introduce `player_pick` as a first-class signal
weighted alongside stage / agenda / twist.

---

## What you can take away (if you also build LLM products)

1. **Structured schema + Pydantic + JSON-mode LLM = a 90%-controllable
   LLM.** Do this first, then do prompt engineering.
2. **A scheduler is free controllability.** Write "when does the LLM
   do what" in Python; let the LLM only handle "how to do it well."
   Reliability climbs sharply.
3. **Walk-on-read beats caching intermediate state.** LLM-app state
   isn't usually complex but is easy to desync. Recompute from source.
4. **LLM-simulated players are the cheapest alpha-stage validation.**
   Spawn a few subagents with different personas, play, observe. Richer
   signal than unit tests.
5. **Real users are still irreplaceable early.** LLM players are too
   cooperative. 5 real friends playing one session each beats 100 LLM
   simulations for product-truth signal.

---

## Repo

[github.com/...](https://github.com/...) — MIT licensed. Contributions
welcome. Specific directions in
[CONTRIBUTING.md](../../CONTRIBUTING.md) and
[docs/GOOD_FIRST_ISSUES.md](../GOOD_FIRST_ISSUES.md).

---

*Written 2026-05. Project status: OSS preview / alpha.*
