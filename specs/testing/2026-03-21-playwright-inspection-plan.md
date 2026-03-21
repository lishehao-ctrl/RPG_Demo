# Playwright Inspection Plan

## Goal

Design a comprehensive Playwright inspection pass for the current RPG frontend so that every major route, every interactive component, and every meaningful button/select/input is explicitly exercised.

This is not a lightweight smoke test.

This inspection should verify:

- visual route reachability
- account-aware behavior
- owner/private/public resource behavior
- destructive actions
- empty/error states
- route-state persistence
- real backend integration

The inspection should be executable against:

- local dev: `http://127.0.0.1:5173` + `http://127.0.0.1:8000`
- production: `https://rpg.shehao.app`

## Scope

Covered routes:

- `#/create-story`
- `#/author-jobs/:jobId`
- `#/stories`
- `#/stories/:storyId`
- `#/play/sessions/:sessionId`

Covered component groups:

- global shell and header
- account switcher
- create-story workspace
- preview pane
- author-loading dashboard
- loading-card spotlight
- library browser
- library cards
- detail sidebar / detail management controls
- play session sidebar
- transcript
- suggested actions
- state bars
- recent consequences
- support surfaces
- play input dock

## Core Principles

1. Prefer real backend integration over placeholder mode.
2. Prefer accessible selectors:
   - role
   - label
   - visible text
3. Recreate test data through the product when possible.
4. For setup-heavy scenarios, API seeding is acceptable if cleanup is guaranteed.
5. Every destructive action used for setup verification must clean up after itself.
6. Do not treat "page loaded" as sufficient. Each control must prove its expected effect.

## Required Test Accounts

Use the three built-in demo accounts:

- `local-dev`
- `alice`
- `bob`

The inspection should explicitly verify cross-account visibility and ownership boundaries.

## Required Test Data

Use three fixture classes during the run:

1. `alice_private_story`
- owner: `alice`
- visibility: `private`

2. `alice_public_story`
- owner: `alice`
- visibility: `public`

3. `bob_public_story`
- owner: `bob`
- visibility: `public`

Optionally:

4. `play_fixture_story`
- any owner
- used to produce a session for play-page validation

Cleanup rule:

- any story created only for inspection must be deleted before the run ends unless intentionally retained as demo content

## Test Harness Structure

Recommended suite organization:

1. `global-shell.spec`
2. `create-preview-author.spec`
3. `library-management.spec`
4. `story-detail-management.spec`
5. `play-session.spec`
6. `account-boundaries.spec`
7. `error-empty-states.spec`

Recommended data strategy:

- `beforeAll`: confirm `/health`, confirm current actor API, clear accidental leftover test data when safe
- per spec: create only the data needed for that scenario
- `afterAll`: delete temporary stories

## Inspection Matrix

### A. Global Shell

#### A1. Header Brand

Control:

- `Narrative Studio` brand button

Assertions:

- navigates to `#/create-story`
- does not produce console errors
- route hash updates correctly

#### A2. Top Navigation

Controls:

- `Create`
- `Library`

Assertions:

- `Create` routes to `#/create-story`
- `Library` routes to `#/stories`
- active visual state follows route

#### A3. Search Input

Control:

- top search input

Assertions:

- enabled on library/detail/play pages
- disabled on author-loading page
- value persists when navigating within library/detail/play context as designed
- library results react to query updates

#### A4. Account Switcher

Controls:

- account combobox

Assertions:

- switching account updates displayed actor name/id
- switching account triggers refetch
- route remains stable when switching accounts
- inaccessible resources degrade gracefully after switch

### B. Create Story Page

Component:

- `CreateStoryWorkspace`

#### B1. Story Seed Textarea

Control:

- `Story Seed` textarea

Assertions:

- empty by default
- accepts input
- preserves current seed while preview is pending

#### B2. Generate Preview Button

Controls:

- `Generate Preview`
- `Generating Preview...`

Assertions:

- disabled during request
- preview pane transitions from awaiting state to generating state to ready state
- no duplicate submissions from rapid click

#### B3. Browse Library Buttons

Controls:

- `Browse Library` primary secondary button
- ghost `Browse Library` button when preview exists

Assertions:

- navigates correctly to library
- preserves route/query state if expected

#### B4. Preview Pane

Checks:

- badge transitions:
  - `Awaiting Input`
  - `Generating`
  - `Preview Ready`
- title renders
- premise renders
- tone renders
- core theme / structure / NPCs / beats populate
- loading shell appears only during generation
- no layout jump from empty to ready

#### B5. Start Authoring

Control:

- `Start Authoring`

Assertions:

- only appears once preview exists
- transitions to author-loading route
- uses preview checkpoint instead of forcing a new preview

### C. Author Loading Page

Component:

- `AuthorLoadingDashboard`

#### C1. Progress Header

Checks:

- session label present
- progress fill updates over time
- stage label updates
- completion percent updates

#### C2. Loading Card Spotlight

Checks:

- active card changes over time
- card frame height is stable
- card content updates from pool
- no "randomly rotating" copy

#### C3. Current Story Context Card

Checks:

- title updates
- premise updates
- theme/tone/NPC/beat stats populate

#### C4. Publish Controls

Controls:

- `Publish Visibility` select
- `Publish to Library`

Assertions:

- publish controls appear only after result exists
- visibility defaults to `private`
- visibility selection affects published story visibility
- button disables while publishing
- on success routes to library with selected story highlighted

### D. Library Page

Components:

- `StoryLibraryPage`
- `StoryLibraryBrowser`
- `StoryLibraryCard`

#### D1. View Selector

Control:

- `View` combobox

Options:

- `Accessible`
- `Mine`
- `Public`

Assertions:

- `Accessible` shows owned private/public + others' public
- `Mine` shows only owned stories
- `Public` shows only public stories
- route hash stores `view`
- refresh preserves `view`

#### D2. Theme Filter

Control:

- `Filter by Theme`

Assertions:

- options reflect current facet counts
- filter works together with current `view`
- filter works together with search query
- route hash stores `theme`

#### D3. Empty States

Assertions by view:

- `Accessible`: "No visible stories yet" style message
- `Mine`: "No owned stories yet" style message
- `Public`: "No public stories available" style message

Current implementation should be checked for whether it distinguishes these well enough.

#### D4. Story Cards

Per card assertions:

- title renders
- published time renders
- ownership badge correct:
  - `My Private Story`
  - `My Public Story`
  - `Public Story`
- clicking card opens detail
- selected visual state follows current story

#### D5. New Dossier Button

Control:

- `New Dossier`

Assertions:

- routes to create page

#### D6. Load More

Control:

- `Load More from Library`

Assertions:

- appears only when pagination exists
- appends stories without duplication
- preserves current filters/view

### E. Story Detail Page

Components:

- `StoryDetailPage`
- `PlayDomainSidebar`

#### E1. Detail Sidebar Navigation

Controls:

- `Overview`
- `Structure`
- `Cast`
- `Start Play`

Assertions:

- each button scrolls to correct section
- active state updates
- route hash remains stable if that is the intended behavior
- no fake-tab behavior

#### E2. Detail Content Blocks

Checks:

- opening framing exists when play overview exists
- premise renders
- stakes render
- theme/tone render
- narrative structure list renders
- cast session panel renders

#### E3. Cast Session Tabs

Controls:

- `Topology`
- `Player Role`
- `Cast Manifest`

Assertions:

- tabs switch content in-place
- correct panel content appears
- no missing data when switching repeatedly

#### E4. Visibility Control

Control:

- detail visibility select

Assertions:

- visible only when `viewer_can_manage`
- hidden for non-owned public stories
- switching `private -> public` updates label immediately
- switching `public -> private` updates label immediately
- after switching to private, another account can no longer access detail

#### E5. Delete Story

Control:

- `Delete Story`

Assertions:

- visible only when `viewer_can_manage`
- confirmation dialog appears
- cancel leaves story intact
- confirm deletes story
- after delete:
  - navigate back to library
  - deleted story disappears from current list
  - stale selection is cleared
  - direct revisit of deleted detail fails gracefully

#### E6. Start Play Session

Control:

- `Start Play Session`

Assertions:

- creates a session
- routes to play page
- uses current actor context
- inaccessible story should not create a session for non-owner if private

### F. Play Session Page

Components:

- `PlaySessionPage`
- `TranscriptView`
- `SuggestedActions`
- `StateBarList`
- `EndingSummary`
- `PlayMetaPanel`
- `PlayDomainSidebar`

#### F1. Play Sidebar

Controls:

- `Story So Far`
- `Progress`
- `Consequences`
- `Tools` when support surfaces section is present

Assertions:

- in-page navigation works
- active state updates
- `Tools` only appears when support surface section exists

#### F2. Transcript

Checks:

- initial GM entry present
- player turn appends
- GM response appends
- pending player text renders during submission
- pending GM resolving state renders during submission

#### F3. Meta Panels

Controls:

- `Protagonist`
- `Session Metadata`
- `State Bars`
- `Recent Consequences`
- `Suggested Actions`
- `Support Surfaces`

Assertions:

- each can expand/collapse
- default-open/default-closed states match intended UX
- repeated toggling does not corrupt layout

#### F4. Suggested Actions

Controls:

- every suggested action button

Assertions:

- selecting suggestion populates input text
- selected suggestion visual state updates
- switching suggestions replaces input

#### F5. Input Dock

Controls:

- turn textarea
- submit button
- `Inventory`
- `Map`
- `Leave Session`

Assertions:

- textarea accepts text
- submit sends turn
- submit disables during request
- input clears after success
- `Inventory` and `Map` reflect disabled/enabled state from backend
- `Leave Session` returns to library

#### F6. Consequence Rendering

Checks after a real turn:

- narration updates
- progress percent changes
- state bars update when expected
- consequence list updates when expected
- ledger values update when expected
- tags render when expected

#### F7. Ending State

If a session reaches completion:

- ending card renders
- submit is disabled
- suggestion list collapses to terminal state

### G. Account Boundary Scenarios

These are mandatory.

#### G1. Private Story Visibility

Flow:

1. Alice creates and publishes private story
2. Bob cannot see it in `accessible`
3. Bob cannot open detail directly

#### G2. Public Story Visibility

Flow:

1. Alice changes story to public
2. Bob sees it in `accessible`
3. Bob sees it in `public`
4. Bob can open detail
5. Bob cannot see manage controls

#### G3. Delete Boundary

Flow:

1. Owner can delete
2. Non-owner cannot delete
3. After delete, old detail URL no longer resolves

#### G4. Play Session Ownership

Flow:

1. Alice creates session on private story
2. Bob cannot open that session directly
3. Alice still can

#### G5. Account Switch While Viewing Protected Resource

Flow:

1. Alice opens private story detail
2. Switch account to Bob
3. App should not remain on a silently broken detail
4. Expected behavior:
   - redirect to library, or
   - show clean "story unavailable" state with a library escape action

### H. Error and Recovery States

#### H1. Library Fetch Failure

Inject or simulate backend failure.

Assertions:

- error message is readable
- page remains navigable

#### H2. Detail Fetch Failure

Assertions:

- clean unavailable state
- back-to-library action works

#### H3. Session Fetch Failure

Assertions:

- clean unavailable state
- fallback to library works

#### H4. Publish Failure

Assertions:

- publish controls remain usable after failure
- user gets actionable message

#### H5. Delete Failure

Assertions:

- story remains visible
- user sees actionable error
- no half-deleted UI state

### I. Route Persistence

Mandatory checks:

- `#/stories?view=mine`
- `#/stories?view=public&theme=...`
- `#/stories?view=accessible&q=...`

Assertions:

- reload preserves state
- back/forward preserves state
- account switch does not erase query/theme/view unexpectedly

### J. Accessibility and Interaction Sanity

At minimum:

- all buttons reachable by role
- comboboxes labeled
- confirm dialog appears for delete
- disabled controls actually disabled, not only visually muted

## Concrete Control Inventory

Every one of these must be touched by the inspection:

### Global

- `Narrative Studio`
- `Create`
- `Library`
- top search input
- account select

### Create

- seed textarea
- `Generate Preview`
- `Start Authoring`
- `Refresh Preview`
- `Browse Library`

### Author Loading

- `Publish Visibility`
- `Publish to Library`

### Library

- `View`
- `Filter by Theme`
- every visible story card
- `New Dossier`
- `Load More from Library` when present
- placeholder `Initiate New Narrative Chain`

### Story Detail

- sidebar: `Overview`, `Structure`, `Cast`, `Start Play`
- cast session tabs: `Topology`, `Player Role`, `Cast Manifest`
- detail visibility select
- `Start Play Session`
- `Delete Story`
- `Back to Library`

### Play Session

- sidebar nav items present for the current snapshot
- every meta-panel toggle
- every suggested action button
- turn textarea
- submit button
- `Inventory`
- `Map`
- `Leave Session`

## Pass Criteria

Inspection passes only if:

- no control causes an uncaught runtime exception
- no control silently does nothing when it should have a visible effect
- no cross-account visibility violation is observed
- destructive actions complete and leave UI in a coherent state
- route-state controls (`q`, `theme`, `view`) remain synchronized with navigation
- no unexpected console errors appear other than explicitly accepted noise such as missing favicon during dev

## Known Accepted Noise

Current known low-priority noise:

- dev-only `favicon.ico` 404

This should be tracked but not treated as an inspection blocker unless the environment under test requires a clean console.

## Recommended Artifact Output

For each run, produce:

- route-level screenshots
- one console log capture
- a matrix result table:
  - control
  - action
  - expected result
  - actual result
  - pass/fail
- a short defects list with severity

## Recommended Execution Order

1. health check
2. account switcher
3. library view/theme/search state
4. create preview flow
5. author loading and publish visibility
6. story detail management
7. play session interaction
8. cross-account access checks
9. cleanup of temporary stories

