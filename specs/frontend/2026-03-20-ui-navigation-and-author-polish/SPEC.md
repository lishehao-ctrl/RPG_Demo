# UI Navigation And Author Polish

## Summary

This spec defines the current frontend-only UI polish pass.

The goals are:

1. make the create-story input area clearer and less overwhelming
2. make preview generation feel alive rather than static
3. make author loading cards readable and stable
4. turn sidebar labels into real navigation rather than fake tabs
5. reduce right-rail density in play and story detail

This pass must not add frontend-only contract assumptions and must not require new backend APIs.

## Product Rules

- Use only current public product APIs.
- Do not read `/benchmark/*`.
- Do not invent placeholder-only fields.
- Do not require backend changes for this pass.
- If the UI truly needs new data, stop and report the exact missing field rather than faking it.

## Public Data Available

### Author create / loading

- `POST /author/story-previews`
- `POST /author/jobs`
- `GET /author/jobs/{job_id}`
- `GET /author/jobs/{job_id}/result`

Available author preview/loading data already includes:

- preview title / premise / tone / theme
- expected npc count
- expected beat count
- loading cards
- progress stage label
- completion ratio

### Story detail

- `GET /stories/{story_id}`

Available story detail data already includes:

- `story`
- `preview`
- `presentation`
- `play_overview`

### Play session

- `GET /play/sessions/{session_id}`
- `GET /play/sessions/{session_id}/history`
- `POST /play/sessions/{session_id}/turns`

Available play data already includes:

- transcript history
- protagonist
- progress
- feedback
- state bars
- suggested actions
- support surfaces
- ending

## Scope

### A. Create page polish

Current issues:

- seed explanation is too long
- the input area looks too much like a hero statement rather than an editable box
- users should be able to see the primary action without scrolling on common laptop viewports

Required changes:

- keep the field label short and explicit
- shorten helper copy
- make the default field empty and rely on muted placeholder text
- reduce textarea font size and initial height
- preserve the editorial tone of the page
- ensure the primary CTA remains above the fold on typical desktop/laptop viewport

### B. Preview generation feel

Current issue:

- preview generation still feels like a hard wait followed by an instant replace

Required changes:

- when preview is generating, the preview pane should visibly enter a “building dossier” state
- use animated skeleton or streaming-like reveal
- once preview arrives, title / premise / tone may reveal progressively
- keep the same design language already used elsewhere in the app

### C. Author loading cards

Current issues:

- the old “randomly rotating” explanation is misleading
- card content can create visual instability
- the card should feel intentional rather than chaotic

Required changes:

- no “randomly rotating” copy
- fixed card frame size
- content should not make the box jump vertically
- card sequence should feel controlled and readable
- display of the active card should remain visually stable

### D. Sidebar recovery

Current issue:

- sidebar items previously looked clickable but were either dead or hidden

Required changes:

- sidebar items should map to real page sections
- do not implement fake tabs
- use in-page navigation / scroll targets

Play page mapping:

- `Transcript` -> transcript body
- `Chapters` -> session metadata / beat-progress block
- `Research` -> protagonist + consequences / ledger area
- `Settings` -> support surfaces + leave session area

Story detail mapping:

- `Overview` -> opening framing / premise
- `Structure` -> narrative structure
- `Cast` -> cast manifest
- `Start Play` -> CTA block

### E. Right rail density reduction

Current issue:

- right rail on play is too dense and competes with the main reading column

Required changes:

- organize right-rail cards as collapsible panels
- keep a small number open by default
- recommended default-open set on play:
  - protagonist
  - state bars
  - suggested actions
- the rest should start collapsed
- preserve readability and hierarchy

## Design Constraints

- Preserve the established visual system.
- Keep typography, colors, borders, and motion aligned with the current editorial style.
- Do not introduce app-like dashboard widgets that clash with the rest of the product.
- Prefer subtle transitions and deliberate spacing over generic UI chrome.

## File Targets

Likely files to touch:

- `frontend/src/widgets/authoring/create-story-workspace.tsx`
- `frontend/src/features/authoring/create-story/model/use-create-story-flow.ts`
- `frontend/src/features/authoring/loading/model/use-author-loading.ts`
- `frontend/src/entities/authoring/ui/loading-card-spotlight.tsx`
- `frontend/src/pages/play/play-session-page.tsx`
- `frontend/src/pages/play/story-detail-page.tsx`
- `frontend/src/widgets/chrome/play-domain-sidebar.tsx`
- `frontend/src/app/styles.css`

## Explicit Non-Goals

- no backend API changes
- no benchmark diagnostics in UI
- no new data model for chapters/research/settings
- no server deployment work
- no visual redesign of the whole app

## Acceptance Criteria

The pass is done only if:

1. `cd frontend && npm run check` passes
2. create page primary CTA is visible above the fold on a common laptop viewport
3. preview generation has visible animated feedback
4. author loading card area does not jump vertically as cards change
5. play/story-detail sidebars navigate to real sections
6. right rail in play is meaningfully less dense by default
7. no new dependency on non-public backend data exists

## Manual QA

1. Open create page.
2. Confirm seed field is clearly editable.
3. Trigger preview and observe animated preview state.
4. Start author job and observe stable loading card frame.
5. Open story detail and click each sidebar item.
6. Open play session and click each sidebar item.
7. Verify collapsed panels reduce right-rail overload.
