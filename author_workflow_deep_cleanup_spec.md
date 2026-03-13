# Author Workflow Deep Cleanup Spec

This document is the source of truth for the next cleanup pass on author workflow architecture.

It is written for an implementation agent, not for product brainstorming.

## Current Contract

The current active contract is:

- `review_ready = playable, not polished`
- author workflow retry budget is unified to `3 attempts`
- author workflow timeout budget is unified to `20s`
- the LangGraph wrapper is the only retry owner
- each author-chain compile call gets only one real LLM/gateway attempt
- `final_lint` failure goes directly to `workflow_failed`
- automatic `repair_pack` is not part of the active author workflow graph

Current active references:

- `docs/playable_validation_contract.md`
- `docs/runtime_status.md`
- `rpg_backend/generator/author_workflow_policy.py`
- `rpg_backend/application/author_runs/service.py`

## Objective

Deep-clean the author workflow implementation so the codebase is easier to extend later without changing the current product behavior.

This pass is a structural cleanup pass, not a feature pass.

## Required Outcomes

### 1. Reduce orchestration coupling

Refactor the current author workflow implementation so that `AuthorWorkflowService` is no longer the place where all of these live together:

- graph topology
- workflow state typing
- artifact/event serialization rules
- DB persistence helpers
- run completion policy

Target shape:

- keep `AuthorWorkflowService` as the public orchestration entrypoint
- move graph construction into a separate module
- move workflow state / node-name / artifact-name definitions into a separate module
- move artifact/event persistence mapping into a separate module

The refactor must preserve the current external behavior.

### 2. Eliminate active-tree legacy drift

Remove or rewrite active-code / active-doc references that still imply old semantics.

In active code and active docs, there must be no misleading references to:

- automatic `repair_pack` as part of the main author graph
- chain-level schema-feedback retry semantics
- old author workflow timeout/retry config names
- old naming that suggests skeleton-era behavior instead of outline/materialize behavior

Historical material under `docs/archive/` may keep old semantics, but it must remain clearly historical and must not be treated as current behavior.

### 3. Centralize workflow vocabulary

Author workflow should stop relying on scattered string literals for:

- node names
- artifact types
- event types
- terminal statuses

Introduce a central vocabulary module or strongly typed constant set and make active implementation code read from it.

Tests should also prefer the shared vocabulary over open-coded strings where practical.

### 4. Add architecture guardrails

Add regression protection for the architecture itself, not just runtime outcomes.

At minimum, add guards for:

- the active graph topology does not include `repair_pack`
- `final_lint` only routes to `review_ready` or `workflow_failed`
- author workflow still uses a single policy source
- author workflow still uses graph-owned retry semantics
- active docs do not drift back to old author workflow semantics

Prefer lightweight, high-signal tests over snapshot-heavy tests.

## Non-Goals

Do not change these in this pass:

- `/author/runs` API shape
- playable-first linter semantics
- move surface vs deterministic execution boundary
- runtime play-mode provider retry behavior
- worker infrastructure behavior outside author workflow usage

## Implementation Constraints

- Preserve current product semantics exactly unless a change is required to remove ambiguity or dead code.
- Prefer deleting misleading code over layering compatibility wrappers.
- Do not reintroduce automatic repair behavior.
- Do not reintroduce strict/playable split semantics.
- Do not add new feature flags for old author behavior.

## Aggressive Cleanup Authorization

This pass is explicitly authorized to be aggressive.

- Do not be conservative for the sake of historical compatibility.
- If an old path, compatibility layer, stale test, stale generated artifact, or stale module makes the system harder to understand, delete it rather than preserving it.
- If frontend code is only preserving dead author workflow semantics or is creating maintenance drag, it may be deleted as part of this pass.
- If frontend is kept, it must align with the current active author workflow contract and must not encode legacy regenerate / repair / strict-author assumptions.
- If frontend is deleted or substantially reduced, also delete or update related docs, scripts, tests, and generated artifacts so the repository remains internally consistent.
- Do not keep dead files around "just in case."

## Detailed Implementation Spec

This section is decision-complete for the next implementation pass.

### Decision 1: Keep frontend, but only as a thin client

Do **not** delete the entire frontend in this pass.

Instead:

- keep the author/play product rails
- delete frontend code only when it preserves dead backend semantics or duplicates backend workflow knowledge
- do not let frontend model the author graph beyond:
  - run status
  - current node
  - artifacts
  - events

Frontend is allowed to render backend state. It is **not** allowed to encode backend workflow policy.

That means:

- no frontend-side assumptions about repair/regenerate loops
- no frontend-only workflow state machine
- no frontend copy that describes old strict/repair semantics

### Decision 2: The next backend cleanup target is not product behavior

The next pass must keep behavior unchanged and focus only on structure.

The implementation goal is to move from:

- service
- graph with inline node logic
- persistence
- broad typed state

to:

- thin service composition
- explicit graph topology module
- explicit node handler module
- explicit route policy module
- explicit beat context builder
- explicit artifact serialization module

### Required Backend Refactor

Implement the following exact structure changes.

#### A. Split workflow graph responsibilities

`rpg_backend/application/author_runs/workflow_graph.py` must stop containing all of these together:

- topology constants
- node implementations
- route functions
- generic tracked retry wrapper

Target split:

- `workflow_graph.py`
  - graph assembly only
  - imports nodes/routes/topology
- `workflow_nodes.py`
  - node implementations only
- `workflow_routes.py`
  - route functions only
- `workflow_retry.py`
  - tracked retry wrapper only

Allowed variation:

- topology constants may stay in `workflow_vocabulary.py` or move to `workflow_topology.py`
- but graph assembly must be visually small and easy to scan

Acceptance signal:

- `build_author_workflow_graph()` should read like topology wiring, not like a giant mixed implementation file

#### B. Introduce a beat context builder

Create a dedicated module for beat-generation input assembly.

Target module:

- `rpg_backend/application/author_runs/beat_context_builder.py`

Move into it:

- `prefix_summary` assembly
- `author_memory` assembly
- projected overview context assembly
- last accepted beat compaction for outline generation

`generate_beat_outline` node should consume a single structured result from this builder instead of manually recomputing all inputs inline.

Acceptance signal:

- the beat outline node should mostly orchestrate calls, not assemble context piece by piece

#### C. Split persistence into serializer vs sink

`workflow_persistence.py` still owns too much.

Refactor into:

- `workflow_artifacts.py`
  - artifact payload conversion
  - artifact list construction from node updates
- `workflow_persistence.py`
  - DB writes only
  - run completion/failure persistence only

Do not leave artifact serialization logic embedded in the persistence sink.

Acceptance signal:

- persistence class should mostly say “write this”
- serializer module should say “what is written”

#### D. Tighten workflow vocabulary

Current shared vocabulary is good but still too loose.

Upgrade it so active code uses one authoritative vocabulary layer for:

- node names
- event types
- artifact types
- run statuses
- author workflow error codes

Implementation requirement:

- prefer `StrEnum` if available in current Python target, otherwise keep constant classes but add:
  - `ALL`
  - terminal sets
  - helper sets for validation/guard tests

Also use the shared vocabulary in:

- author workflow service
- graph / nodes / routes
- persistence
- author API tests
- frontend author view-models where status strings are currently open-coded

Do not chase every runtime string in the repo; focus on author-workflow-related vocabulary only.

#### E. Shrink state surface where practical

Do **not** redesign the workflow state into a brand new system in this pass.

Do this instead:

- keep `AuthorWorkflowState`
- extract grouped helper accessors/builders for:
  - overview phase fields
  - beat phase fields
  - pack phase fields

If a full split would create too much churn, stop at helper-layer decomposition rather than inventing a second giant state type.

This is important:

- avoid speculative overengineering
- reduce state sprawl without changing graph semantics

### Required Frontend Cleanup

Frontend is kept, but must be trimmed to a thin backend-driven shell.

Do the following:

#### A. Delete stale author semantics from frontend copy and helpers

Audit and remove any copy/helper logic that implies:

- automatic repair
- regenerate loops
- old strict review semantics
- any author graph path that no longer exists

Focus first on:

- `frontend/src/features/author-review/lib/*`
- `frontend/src/pages/author/*`
- `frontend/README.md`
- `frontend_agent_contract.md`

#### B. Converge author status vocabulary in frontend

Where frontend open-codes:

- `review_ready`
- `failed`
- `running`
- `pending`

converge those usages behind one small frontend author-status helper or shared constant module.

Do not import backend Python constants into frontend.
Create one frontend-local source of truth if needed.

#### C. Delete dead author UI paths if redundant

If any frontend author page exists only to expose stale workflow internals and is not needed for the active product flow, delete it.

Use this decision rule:

- keep pages needed for generate / inspect / publish / play handoff
- delete pages that only preserve historical workflow complexity

If a page is deleted:

- remove router entries
- remove links/navigation
- remove related tests/docs/scripts if they become dead

### Required Guardrails

Add or extend tests for the following exact conditions.

#### A. Backend architecture guardrails

- graph topology does not include `repair_pack`
- `final_lint` only routes to `review_ready` or `workflow_failed`
- graph wiring lives in graph assembly module, not mixed with large inline node logic
- author workflow still uses a single policy source
- author workflow retry ownership remains in graph wrapper

#### B. Backend behavior guardrails

- targeted author workflow tests still pass unchanged in outcome
- no chain compile path depends on schema-feedback retry

#### C. Frontend drift guardrails

- active frontend docs do not describe old author workflow semantics
- author review/status helpers do not mention repair/regenerate loops
- deleted pages/routes do not leave dead imports

### Required Verification

Run at minimum:

```bash
pytest -q tests/api/test_author_runs_api.py tests/test_author_workflow_beat_generation.py tests/test_story_linter.py tests/test_story_pack_normalizer.py tests/test_author_workflow_architecture.py
```

If frontend files are changed, also run the smallest relevant frontend or docs consistency checks that still exist in the repo, and record them.

### Required Writeback

When finished, update this document again.

The update must include:

- what backend modules were added / deleted / rewritten
- what frontend files/pages were deleted or simplified
- what guardrails were added
- exact verification commands
- any remaining debt

Do not leave this section stale after implementation.

## Acceptance Criteria

The pass is complete only if all of the following are true:

- active author workflow behavior is unchanged from the current contract
- `AuthorWorkflowService` is materially smaller in responsibility
- graph/state/persistence vocabulary is more modular than before
- no active docs describe automatic `repair_pack` in the main flow
- no active code path depends on chain-level schema-feedback retry
- targeted tests for author workflow and validation are green

Recommended verification set:

```bash
pytest -q tests/api/test_author_runs_api.py tests/test_author_workflow_beat_generation.py tests/test_story_linter.py tests/test_story_pack_normalizer.py
```

If additional tests are needed, run them and record them below.

## Required Documentation Update

The implementing agent must update this document before finishing.

Append or edit the sections below with concrete information:

### Implementation Log

- Date: 2026-03-13
- Agent: Codex (GPT-5)
- Summary of structural cleanup:
  - Split graph responsibilities into dedicated modules:
    - `workflow_graph.py` is now assembly/wiring only.
    - `workflow_nodes.py` contains node implementations only.
    - `workflow_routes.py` contains route decisions only.
    - `workflow_retry.py` contains retry ownership/wrapper only.
    - `workflow_topology.py` contains conditional/linear topology constants.
  - Added dedicated beat context builder:
    - `beat_context_builder.py` now owns prefix summary, author memory, overview projection, and last accepted beat compaction.
    - `generate_beat_outline` now consumes one structured context object instead of inline context assembly.
  - Split persistence serializer vs sink:
    - `workflow_artifacts.py` now owns artifact payload conversion and artifact list construction from node updates.
    - `workflow_persistence.py` now focuses on run/event/artifact writes and completion/failure persistence.
  - Tightened workflow vocabulary:
    - converted author workflow vocabulary to `StrEnum` in `workflow_vocabulary.py`.
    - added `ALL`/terminal/helper sets (`AUTHOR_WORKFLOW_*_ALL`, status/node terminal sets, graph node set).
    - active backend workflow modules now use this vocabulary layer.
  - Reduced state sprawl without redesign:
    - kept `AuthorWorkflowState`.
    - added grouped phase accessors/builders in `workflow_state.py` (`get_overview_phase`, `get_beat_phase`, `get_pack_phase`, plus grouped update builders).
    - node/route code now uses these helpers where practical.
  - Frontend kept as thin client and aligned to active contract:
    - added `frontend/src/features/author-review/lib/authorStatus.ts` as the only status-literal source for author run status semantics.
    - refactored `authorViewModel.ts` and author pages to consume status helpers instead of open-coded literals.
    - updated active frontend docs/contracts to backend-driven `/author/runs` + `/author/stories` semantics.
  - Guardrail expansion:
    - extended architecture tests for assembly-only graph structure, required split-module presence, frontend contract/status drift checks, and existing topology/policy/retry guards.

### Files / Modules Changed

- Added:
  - `rpg_backend/application/author_runs/beat_context_builder.py`
  - `rpg_backend/application/author_runs/workflow_nodes.py`
  - `rpg_backend/application/author_runs/workflow_routes.py`
  - `rpg_backend/application/author_runs/workflow_retry.py`
  - `rpg_backend/application/author_runs/workflow_topology.py`
  - `rpg_backend/application/author_runs/workflow_artifacts.py`
  - `frontend/src/features/author-review/lib/authorStatus.ts`
- Updated:
  - `rpg_backend/application/author_runs/workflow_graph.py` (assembly-only rewrite)
  - `rpg_backend/application/author_runs/workflow_persistence.py` (sink-only rewrite)
  - `rpg_backend/application/author_runs/workflow_state.py` (phase helpers/builders)
  - `rpg_backend/application/author_runs/workflow_vocabulary.py` (`StrEnum` + helper sets)
  - `tests/api/test_author_runs_api.py`
  - `tests/test_author_workflow_architecture.py`
  - `frontend/src/features/author-review/lib/authorViewModel.ts`
  - `frontend/src/pages/author/AuthorStoriesPage.tsx`
  - `frontend/src/pages/author/AuthorRunDetailPage.tsx`
  - `frontend/src/pages/author/AuthorStoryReviewPage.tsx`
  - `frontend/README.md`
  - `frontend_agent_contract.md`
- Deleted or removed in this pass:
  - no frontend routes/pages were deleted; active author pages were kept because they are still required for generate / inspect / publish / play handoff.
  - old mixed implementation sections were removed from `workflow_graph.py` and `workflow_persistence.py` as part of the split.

### Verification Run

- Commands executed:
  - `pytest -q tests/api/test_author_runs_api.py tests/test_author_workflow_beat_generation.py tests/test_story_linter.py tests/test_story_pack_normalizer.py tests/test_author_workflow_architecture.py`
  - `pytest -q tests/test_docs_consistency.py`
  - `npm --prefix frontend run test:unit`
  - `npm --prefix frontend run build`
- Result:
  - Pass (all commands above succeeded).

### Follow-up Notes

- Remaining cleanup debt, if any
  - `AuthorWorkflowState` is still a broad typed dict; this pass only added grouped helpers/builders rather than a full phase-type redesign.
  - Repository still contains historical progress/archive notes mentioning legacy states; active code/docs/guards now enforce current semantics.
- Any intentionally deferred work
  - No `/author/runs` API contract changes were made (intentionally preserved).
  - No compatibility wrappers for legacy regenerate/repair behavior were introduced.
  - Frontend was intentionally kept (not deleted) as a thin backend-driven shell for active author/play rails.
  - Historical archive docs under `docs/archive/` were intentionally kept as historical-only material.

Do not leave this document unchanged after implementation.
