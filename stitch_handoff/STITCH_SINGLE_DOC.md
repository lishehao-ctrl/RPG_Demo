# Google Stitch Single-Document Input

Use this file only as a design-generation handoff for Google Stitch.

This is not the source of truth for product APIs or route contracts.
Those live in:

- `/Users/lishehao/Desktop/Project/RPG_Demo/specs/interface_governance_20260319.md`
- `/Users/lishehao/Desktop/Project/RPG_Demo/frontend/specs/FRONTEND_PRODUCT_SPEC.md`

## Product Goal

Design a responsive web application for an AI-assisted interactive story product.

This is not a generic writing tool or CMS.
It is a short-loop product:

1. user enters an English story seed
2. system generates a preview
3. user starts an async author job
4. user watches the story take shape
5. user publishes the completed story to a shared library
6. user chooses a published story
7. user plays it through natural language

The app should feel like:

- pitch a story
- watch it take shape
- pick and play

## Product Domains

The app has two product domains:

- `Author`
- `Play`

Visually it may feel like two large workspaces.
Structurally it should still be designed as 5 screens.

## Main Screens

1. `Create Story`
   Route intent: `#/create-story`

2. `Author Loading`
   Route intent: `#/author-jobs/:jobId`

3. `Story Library`
   Route intent: `#/stories`

4. `Story Detail`
   Route intent: `#/stories/:storyId`

5. `Play Session`
   Route intent: `#/play/sessions/:sessionId`

## User Flows

### Flow A: Seed to Published Story

- user enters a seed
- user generates preview
- user sees preview card and flashcards
- user starts author job
- user watches loading cards and progress
- user publishes completed story
- user lands in story library or story detail

### Flow B: Library to Play

- user browses library
- user selects a story
- user reads story detail
- user clicks play
- user starts a play session

### Flow C: Play Loop

- user reads narration
- user reviews state bars
- user optionally taps a suggested action
- user writes or edits a natural-language turn
- user submits the turn
- narration updates
- loop continues until ending or expiry

### Flow D: After Play

- session completes
- ending is shown clearly
- user can return to library
- user can create another story

## Visual Direction

Design the UI like a civic-tech editorial interface with playable tension.

The overall feel should be:

- restrained but not sterile
- serious but still inviting
- readable, structured, and atmospheric
- more editorial and civic than fantasy-game chrome

Avoid:

- purple SaaS default look
- dark-mode-only concept
- neon game HUD styling
- fantasy parchment gimmicks
- admin dashboard chrome
- generic CMS/editor layouts
- node graph or backend tooling aesthetics

Recommended palette direction:

- paper / fog / stone background tones
- ink / harbor navy / charcoal for primary structure and text
- brass / rust / muted civic red as accents

Typography and layout requirements:

- strong typographic hierarchy
- card-driven layout system
- clear primary actions
- loading cards must look intentional
- narration panel must be spacious and readable
- state bars must be visible but secondary to narration

Motion:

- subtle transitions only
- no flashy animations

Image rule for phase 1:

- do not assume story-specific cover images exist
- do not include per-story art, portraits, or thumbnails as a required part of the layout
- global atmospheric background imagery is allowed, but it must be shared app-level decoration only

## Copy Rules

- English-only
- concise labels
- serious but accessible tone
- no joke copy
- no internal AI/debug language in the main experience
- second-person narration only in play

Example domain labels:

- Legitimacy crisis
- Logistics quarantine crisis
- Truth and record crisis
- Public order crisis
- Civic crisis

Example seed placeholders:

- `A harbor inspector must keep quarantine from turning into private rule.`
- `An archivist must restore public trust after the vote record is altered.`
- `A city ombudsman must hold the councils together during a blackout referendum.`

Example empty/error copy:

- `No stories published yet. Generate one and publish it to start building the library.`
- `Generation failed before the story package was completed. Retry from the seed or inspect the job state.`
- `This short session expired. Return to the library and start a new run.`

## Screen Requirements

### 1. Create Story

Goal:
- let the user pitch one story seed, inspect the preview, and launch authoring

Primary actions:
- `Generate Preview`
- after preview: `Start Author Job`

Required UI:
- seed text input
- preview card
- preview flashcards
- strong CTA area
- path to library

Required content:
- working title
- premise
- tone
- stakes
- theme
- cast structure
- npc count
- beat count

States:
- empty
- preview loading
- preview ready
- job launch loading
- error

Important tone:
- this page should feel like pitching an episode, not filling a form

### 2. Author Loading

Goal:
- show the story taking shape while the async author job runs

Dominant UI element:
- `progress_snapshot.loading_cards`

Required UI:
- stage label
- progress sense
- ordered loading card deck
- token/cost area
- publish CTA once complete

Required loading cards:
- theme
- tone
- structure
- npc count
- beat count
- working title
- core conflict
- generation status
- token budget

States:
- queued
- running
- intermediate progress
- completed
- failed

Important tone:
- this page should feel like watching a story skeleton assemble itself

### 3. Story Library

Goal:
- let the user browse published playable stories

Behavior:
- newest first
- card-based list
- no story-specific image dependency

Story card fields:
- title
- one-liner
- premise snippet
- theme
- tone
- npc count
- beat count
- topology
- published time

States:
- populated
- empty
- loading
- fetch error

Important tone:
- this should feel like browsing playable episodes, not files

### 4. Story Detail

Goal:
- let the user inspect one published story before entering play

Primary action:
- `Play Story`

Secondary action:
- `Back to Library`

Required content:
- title
- one-liner
- premise
- theme
- tone
- npc count
- beat count
- topology
- published timestamp

Constraint:
- do not expose internal bundle or backend graph structure

### 5. Play Session

Goal:
- let the user play through a published story via natural language

Visual hierarchy:

1. narration
2. turn composer
3. suggested actions
4. state bars
5. ending

Required UI:
- narration panel
- visible state bars
- 3 suggested actions
- natural-language input
- submit action
- ending panel once complete

Required behavior:
- suggestions are helper prompts, not fixed choices
- narration updates after every turn
- completed state replaces active flow cleanly
- expired state is explicit

States:
- active
- submitting
- completed
- expired
- fetch error

Important tone:
- this should feel like talking to a GM, not clicking a branching tree

## Backend API Surface

Design only around this public backend surface:

| Route | Purpose | Input | Output |
| --- | --- | --- | --- |
| `POST /author/story-previews` | Generate preview | `prompt_seed` | preview payload |
| `POST /author/jobs` | Start author job | `prompt_seed`, optional `preview_id` | job status |
| `GET /author/jobs/{job_id}` | Poll author status | `job_id` | job status + progress snapshot |
| `GET /author/jobs/{job_id}/events` | Stream author progress | `job_id` | SSE events |
| `GET /author/jobs/{job_id}/result` | Read final author result | `job_id` | summary + bundle reference |
| `POST /author/jobs/{job_id}/publish` | Publish story | `job_id` | published story card |
| `GET /stories` | List library | none | story list |
| `GET /stories/{story_id}` | Read one story | `story_id` | story detail + preview |
| `POST /play/sessions` | Start play | `story_id` | initial play snapshot |
| `GET /play/sessions/{session_id}` | Read session | `session_id` | play snapshot |
| `POST /play/sessions/{session_id}/turns` | Submit turn | `input_text`, optional `selected_suggestion_id` | updated play snapshot |

## Frontend-Safe Data Shapes

Depend on these response objects, not internal backend artifacts:

### Preview

- `focused_brief`
- `theme`
- `strategies`
- `structure`
- `story`
- `flashcards`

### Author Progress Snapshot

- `stage`
- `stage_label`
- `completion_ratio`
- `primary_theme`
- `cast_topology`
- `expected_npc_count`
- `expected_beat_count`
- `preview_title`
- `preview_premise`
- `flashcards`
- `loading_cards`

### Published Story

- `title`
- `one_liner`
- `premise`
- `theme`
- `tone`
- `npc_count`
- `beat_count`
- `topology`
- `published_at`

### Play Session Snapshot

- `session_id`
- `story_id`
- `status`
- `turn_index`
- `beat_index`
- `beat_title`
- `story_title`
- `narration`
- `state_bars`
- `suggested_actions`
- `ending`

## What Not To Build

- no auth UI
- no admin panel
- no story graph editor
- no backend debugging console
- no benchmark dashboards
- no raw bundle explorer
- no generic CMS shell

## Final Instruction To Stitch

Generate a clean responsive web app concept for the full author + library + play loop.
Keep the system visually coherent across all five screens.
Prioritize clarity, hierarchy, and product usability over decorative complexity.
