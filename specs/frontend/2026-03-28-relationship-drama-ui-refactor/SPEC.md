# Relationship Drama UI Refactor Spec

## Purpose

Refactor the frontend expression of RPG_Demo from:

- editorial dossier
- civic procedural thriller
- archive / record / public-system workbench

to:

- `轻乙女`
- `都市情感悬疑`
- `关系博弈叙事`

This is **not** a full frontend rewrite.  
It is a product-expression refactor that keeps the current app skeleton but changes:

- visual direction
- page framing
- state language
- component priorities
- copy system

## Fixed Decisions

- Keep the current application structure:
  - home / library
  - story detail
  - play session
  - author / copilot surfaces
- Do not redesign the app into a generic chat bot.
- Do not keep the current dossier / public-record visual mother theme.
- Do not turn the product into low-end pink sweet-romance UI.
- The new visual target is:
  - `高级都市戏剧`
  - `关系悬疑`
  - `人物张力`
  - `暧昧与危险并存`

## New Product Feel

The user should feel:

- they are entering a series / route, not opening a workbench
- characters matter more than institutions
- every screen is about tension, alignment, secrecy, and choice
- the product is entertainment-first, not systems-first

The first-screen reaction should be:

- `我想点进去看看这几个人会发生什么`

not:

- `这套设定做得很严肃很完整`

## Visual Direction

### Replace

Move away from:

- paper dossier
- archive room
- editorial document
- procedural labels as dominant ornament
- warm rust + sage institutional calm as the core palette

### Move toward

Use a visual direction closer to:

- modern serialized drama
- night-city tension
- private message / event recap / relationship board
- soft neon, dark glass, muted luxury, intimate interiors
- emotional contrast over administrative texture

### Visual keywords

- `都市夜色`
- `暧昧`
- `危险感`
- `关系图谱`
- `追更感`
- `高质感`

## Information Architecture Shift

### Home / landing

Current problem:

- reads too much like an editorial studio

New goal:

- communicate immediately:
  - who the user can become
  - which characters matter
  - why the next choice changes the route

Hero should foreground:

- protagonist fantasy
- route tension
- emotional hook

### Story Library

Reframe the library as:

- `剧集入口`
- `路线入口`
- `人物关系故事架`

Cards should foreground:

- title
- emotional hook
- target cast
- route fantasy
- tone

Cards should not foreground:

- structural/procedural metadata
- system taxonomy jargon

### Story Detail

Reframe as:

- `作品页 + 角色关系页 + 入坑页`

Primary blocks should be:

- hook
- character lineup
- relationship graph
- route promise
- tone / tension
- start CTA

Secondary blocks:

- background premise
- branch/ending hints

### Play Session

This page should feel like:

- playing through an interactive drama episode

not:

- operating a state machine dashboard

Primary focus:

- current scene
- relationship tension
- key choice vectors
- visible emotional consequences

Secondary focus:

- deep system explanation
- heavy metadata

### Author Copilot

Reframe Copilot as:

- `剧情导演`
- `编剧室`

It should feel like the user is shaping:

- chemistry
- pacing
- secrets
- confrontation scenes
- ending direction

not editing a civic design bundle.

## State Language Refactor

Current play state language is too institutional.

Replace display language with:

- `亲密`
- `信任`
- `紧张`
- `怀疑`
- `秘密暴露`
- `风评 / 公众形象`

These should appear consistently across:

- state bars
- tooltips
- session summaries
- end-state framing

Do not expose old civic framing in the new UX.

## Component Direction

### Must become signature components

- `角色关系卡`
- `剧情节点 / 名场面卡`
- `关系波动反馈`
- `选择卡片`
- `秘密/站队状态模块`
- `编剧室修改预览`

### Must be visually weakened

- system labels that read like admin metadata
- procedural chrome
- document-like framing blocks
- archive-style paper containers as the default shell

### Relationship graph

Add or strengthen a relationship-map surface.

It should help users quickly read:

- who is close
- who is suspicious
- who is aligned
- who is hiding something

This should become more important than abstract story structure diagrams.

## Copy Direction

### Replace words like

- dossier
- archive
- record
- mandate
- procedure
- civic

with words like

- route
- scene
- tension
- chemistry
- trust
- secret
- confrontation
- confession
- fallout

### Product voice

The voice should be:

- emotionally legible
- elegant but not literary-heavy
- suggestive, not bureaucratic
- dramatic, not melodramatic

## Desktop / Mobile Priorities

### Desktop

Desktop should emphasize:

- relationship graph
- side-by-side story + state + copilot context
- richer visual atmosphere

### Mobile

Mobile should emphasize:

- scene-first reading
- one clear next action
- character reaction visibility
- swipeable route / cast / state modules

## Explicit Design Rules

### Must do

- make character attraction hooks visible early
- make every story card readable as a route fantasy
- make the play page feel like an episode, not a tool
- make state feedback emotionally interpretable
- make Copilot feel like directing a drama

### Must not do

- do not keep the dossier look as the dominant shell
- do not become sugary pink romance app UI
- do not reduce the product to chat bubbles only
- do not bury the characters under system labels
- do not over-explain the mechanics in the main reading path

## Acceptance Criteria

1. A new user can identify the product as a relationship-driven interactive drama within one screen.
2. Library cards communicate route fantasy and cast tension better than system metadata.
3. Play session surfaces emotional and relational state changes clearly.
4. Copilot reads as a story-directing surface, not a civic editor.
5. Current layout skeleton remains reusable; the refactor is expression-level, not architecture-level.
6. The old dossier / archive / civic procedural visual language no longer dominates.

## Validation

- static design review of home, library, story detail, play session, and copilot surfaces
- copy audit: remove civic/procedural vocabulary from user-facing key surfaces
- browser review on desktop and mobile
- “first impression” test:
  - viewer should describe the product as an interactive relationship drama, not a story generator or admin tool
