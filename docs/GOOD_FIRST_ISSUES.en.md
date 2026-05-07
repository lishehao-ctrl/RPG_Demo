# Good first issues

> Language: this doc is the English mirror of [GOOD_FIRST_ISSUES.md](./GOOD_FIRST_ISSUES.md).

A curated list of well-scoped tasks for new contributors. Each one is
small enough to land in 1-3 hours and does not require deep familiarity
with the prompt-driven engine.

When you start one, **comment on its tracking issue first** so we don't
double-up. If there's no issue yet, please open one referencing this
doc.

---

## Backend (Python)

### 1. Unit tests for `_pick_npc_agenda`
**File:** `tests/test_narrative_schedulers.py` (new)
**Estimated time:** 2h

Write deterministic tests covering the agenda scheduler's stage logic:

- `hook` stage → empty list
- `pressure` stage on `turn_index % 2 == 0` → 1 NPC with `intent="probe"`
- `pressure` on odd turn_index → empty
- `reversal` → 2 NPCs with intents `leverage` + `pressure`
- `climax` → 2 NPCs with leverage / reveal alternation
- `pre_finale` → 2 NPCs with leverage / reveal
- Story mode → always empty

Use synthetic CastMember objects from `narrative/contracts.py`. No LLM.

### 2. Unit tests for `compute_current_inventory`
**File:** `tests/test_narrative_inventory.py` (new)
**Estimated time:** 1h

Verify the walk-on-read behavior:

- Empty history + non-empty `starting_assets` → returns starting_assets
- History with one narrator beat that has `inventory_delta.added` → starting + added
- Removed item via case-insensitive substring match → dropped
- Repeated `removed` of the same item → no double-drop crash

### 3. Unit tests for `_parse_branches` label normalization
**File:** `tests/test_narrative_branches_parser.py` (new)
**Estimated time:** 1h

Verify:
- Off-pool labels get snapped via `_normalize_ending_label`
- Branches with `alternate_ending_label == actual_ending_label` get filtered
- Duplicate `pivot_beat_ord` get deduped (only first wins)
- Output is sorted by `pivot_beat_ord` ascending
- More than 4 input branches get capped at 4

### 4. Add a `--dry-run` flag to `tools/http_product_smoke.py`
**File:** `tools/http_product_smoke.py`
**Estimated time:** 1h

Currently the smoke runs end-to-end against a live server with real
LLM calls (cost money). Add `--dry-run` that exercises the HTTP
contract by running through routes but stubs out LLM calls so CI
can use it. Useful for OSS contributors without API keys.

---

## Frontend (TypeScript / React)

### 5. Extend the i18n string bundle for newly-added pages
**File:** `frontend2/src/shared/lib/i18n.ts`
**Estimated time:** 1-2h

The zh/en string bundle already exists. When a new page or component is
added with hardcoded copy, extend the `STRINGS_ZH` / `STRINGS_EN`
records and replace the literal with `useT('your.key')`. Aim to keep
both bundles in sync — if a key only has a zh value, the en bundle
should fall back gracefully (and vice versa).

### 6. Improve `LoadingShim` keyboard accessibility
**File:** `frontend2/src/shared/ui/loading-shim.tsx`
**Estimated time:** 30 min

Currently the loading shim has `role="status"` and `aria-live="polite"`
but the dot animation has no fallback for users with `prefers-reduced-
motion`. Add a media query that reduces the y-bounce animation when
the user prefers reduced motion.

### 7. Cap player diary character counter
**File:** `frontend2/src/pages/play/play-page.tsx`
**Estimated time:** 30 min

The diary textarea has `maxLength={600}` but no visible counter. Add
a small `{N} / 600` chip below the textarea that turns warm when
`N > 540`. Mirror what the create page does for the seed input.

### 8. Add a "Replay this run" button in EndingScreen
**File:** `frontend2/src/pages/play/play-page.tsx`
**Estimated time:** 1h

Currently the ending screen shows passage + highlights + branches +
share button, but there's no way to scroll back through the full
12-turn story. Add a button that scrolls the page back to the cast
strip / first turn so the player can re-read. Make sure both the
`zh` and `en` bundle have the button label.

---

## Docs / community

### 9. Add a third locale (e.g. `ja` or `es`)
**Files:** `frontend2/src/shared/lib/i18n.ts` + `rpg_backend/narrative/engine.py`
**Estimated time:** 3-4h

Extend the existing zh/en scaffolding:

- Add `STRINGS_JA` (or your locale) bundle, mirroring all keys
- Add the locale to `LANGUAGE_OPTIONS` in the create page
- Add a prompt-language branch in `_OPENING_SYSTEM_PROMPT` /
  `_TURN_SYSTEM_PROMPT` selection
- The ending-label canonical IDs stay Chinese — only the display
  label map needs translating

Open an issue describing which locale you want to add before starting,
so we can coordinate vocabulary choices.

### 10. Add more architecture diagrams
**File:** `ARCHITECTURE.md` + matching `ARCHITECTURE.en.md`
**Estimated time:** 2h

The doc already has the per-turn pipeline + session lifecycle as
mermaid blocks. Highest-value next diagram: **the inter-NPC leverage
graph** for a sample 4-NPC cast. Helps new readers understand why
`leverages_over_other_npcs` is N×N rather than just leverage_over_player.

Mermaid diagram is the easiest path. Keep both `.md` and `.en.md`
diagrams identical (mermaid is language-agnostic).

---

## How to claim

1. Pick a task above.
2. Open a GitHub issue titled `[GFI N] <task description>` (e.g.
   `[GFI 1] Unit tests for _pick_npc_agenda`).
3. Comment "I'm working on this" so others know.
4. Send the PR within 7 days; otherwise we'll un-assign.
