# Good first issues

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

### 5. Extract hardcoded Chinese strings into a shared constants file
**File:** `frontend2/src/shared/lib/strings.ts` (new)
**Estimated time:** 2h

Search-and-replace step toward future i18n. **Do not introduce a real
i18n library yet** (that's a separate larger PR). Just collect strings
into one file:

```ts
// shared/lib/strings.ts
export const STRINGS = {
  loading: "加载中…",
  loadingStory: "故事正在加载…",
  failedTryAgain: "续写失败，请稍后再试。",
  // ... etc
} as const
```

Then update the call sites to import from this. Aim for 80% coverage
of the pages directory; perfectionism not required.

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

### 8. Add a "回顾这局" button in EndingScreen
**File:** `frontend2/src/pages/play/play-page.tsx`
**Estimated time:** 1h

Currently the ending screen shows passage + highlights + branches +
share button, but there's no way to scroll back through the full
12-turn story. Add a button that scrolls the page back to the cast
strip / first turn so the player can re-read.

---

## Docs / community

### 9. Translate README.md to English
**File:** `README.en.md` (new)
**Estimated time:** 2h

Mostly mechanical translation of the new README.md. Keep section
structure identical. Frontmatter link from main README should land
this in either-or `[中文](./README.md) · [English](./README.en.md)`.

### 10. Add architecture diagram to ARCHITECTURE.md
**File:** `ARCHITECTURE.md` + a `docs/diagrams/architecture.svg` (or
`.mermaid` block inside the markdown — GitHub renders mermaid
natively)
**Estimated time:** 2h

Visualize the per-turn pipeline:
```
opening → cast + roles + leverage network
        ↓
each turn:
  scheduler signals → LLM call → npc_pulse + options + delta
        ↓
finalize:
  ending → highlights → branches
```

Mermaid diagram is the easiest path. Aim for one diagram per section.

---

## How to claim

1. Pick a task above.
2. Open a GitHub issue titled `[GFI N] <task description>` (e.g.
   `[GFI 1] Unit tests for _pick_npc_agenda`).
3. Comment "I'm working on this" so others know.
4. Send the PR within 7 days; otherwise we'll un-assign.
