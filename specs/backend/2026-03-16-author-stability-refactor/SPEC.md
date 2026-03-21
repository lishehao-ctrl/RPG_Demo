# Author Stability Architecture Refactor Spec

## Purpose

This pass turns the current authoring backend from a large mixed-responsibility workflow into a layered system that is easier to stabilize, benchmark, and evolve.

The main problem is no longer "can the model generate something usable"; it is that orchestration, deterministic compilation, quality gates, fallback policy, and benchmark practice are all mixed together in a small number of oversized files. That makes stability improvements expensive, hard to review, and hard to measure.

## Current Diagnosis

- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py` currently mixes:
  - LangGraph node orchestration
  - deterministic defaults
  - normalization and compilation
  - low-quality predicates
  - fallback policy
  - partial telemetry
- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/gateway.py` currently mixes:
  - OpenAI/Dashscope invocation
  - payload normalization
  - semantic stabilization
  - context packet assembly
  - per-domain generation entrypoints
- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/contracts.py` contains both final bundle contracts and transient draft IR.
- Benchmarking exists as generated artifacts under `/Users/lishehao/Desktop/Project/RPG_Demo/artifacts/benchmarks/`, but there is no canonical runner or fixed regression suite.

Recent A/B work already proved that deterministic compilation improves stability more reliably than adding more prompt restrictions. That direction is now fixed and should shape the architecture.

## Fixed Decisions

- Keep the public FastAPI surface and `AuthorBundleResponse` shape backward compatible in this pass.
- Keep `DesignBundle` as the central backend product contract.
- Keep LangGraph as the top-level orchestrator.
- Prefer `semantic generation -> deterministic compile -> quality decision -> fallback` over prompt-heavy one-shot generation.
- Hard invariants belong in compiler/normalizer code, not in larger prompts.
- Soft quality judgments belong in dedicated quality code, not in the main generation prompt.
- Every material backend change in this area must end with a 5-run full-generation A/B test and artifact output.
- This pass is backend-only. Do not touch frontend or play-runtime concerns.

## Required End State

- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py` is reduced to:
  - `AuthorState`
  - graph node wrappers
  - graph wiring
  - minimal state-to-module glue
- Deterministic logic is moved into dedicated compiler modules.
- Low-quality predicates and fallback reason capture are moved into dedicated quality modules.
- Generation responsibilities are grouped by domain instead of remaining as one giant protocol surface.
- The pipeline records structured source telemetry for at least:
  - `story_frame`
  - `beat_plan`
  - `route_affordance`
  - `ending`
- The pipeline records structured quality/fallback reasons for those stages.
- There is a canonical benchmark runner that can execute a fixed brief suite, run full generations, and write machine-readable plus human-readable reports under `/Users/lishehao/Desktop/Project/RPG_Demo/artifacts/benchmarks/`.

## Target Module Boundaries

The target structure should converge toward:

```text
rpg_backend/author/
  contracts.py
  workflow.py
  checkpointer.py
  generation/
    __init__.py
    context.py
    story_frame.py
    cast.py
    beats.py
    rules.py
    gateway.py
  compiler/
    __init__.py
    story_frame.py
    cast.py
    beats.py
    routes.py
    endings.py
    bundle.py
  quality/
    __init__.py
    story_frame.py
    cast.py
    beats.py
    routes.py
    endings.py
    telemetry.py
  benchmarks/
    __init__.py
    briefs.py
    runner.py
```

Notes:

- A thin facade may remain in `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/gateway.py` during migration, but heavy domain logic should move behind the `generation/` package.
- Splitting `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/contracts.py` into final-contract and draft-contract files is desirable later, but it is not required in the first implementation pass if it creates too much churn.

## Layer Responsibilities

### `generation/`

Owns:

- model invocation
- response parsing
- lightweight payload normalization
- author context packet assembly
- domain-level generation entrypoints

Must not own:

- fallback policy
- deterministic canonical ordering
- low-quality acceptance decisions
- final bundle assembly

### `compiler/`

Owns:

- deterministic defaults
- canonicalization
- semantic stabilization after generation
- route and ending compilation
- final `DesignBundle` assembly helpers

Must not own:

- network calls
- prompt text
- graph state transitions

### `quality/`

Owns:

- low-quality predicates
- reason generation
- source/outcome telemetry records
- shared decision helpers such as "accept / glean / default"

Must not own:

- LLM calls
- direct API shaping
- final persistence

### `benchmarks/`

Owns:

- fixed brief suites
- benchmark runner
- baseline vs candidate comparison
- JSON and Markdown report generation

Must not own:

- production graph logic
- prompt construction

## Telemetry Contract

Add a small structured telemetry contract for stability work. It may live in `quality/telemetry.py` and be represented as a TypedDict, dataclass, or pydantic model, but it must be structured and testable.

Minimum record shape:

```text
stage: story_frame | beat_plan | route_affordance | ending
source: generated | gleaned | default | compiled
outcome: accepted | repaired | rejected | fallback
reasons: list[str]
```

Minimum state additions:

- `story_frame_source`
- `beat_plan_source`
- `route_affordance_source`
- `ending_source`
- `quality_trace`

`quality_trace` may be a flat ordered list of records or a per-stage mapping, but the representation must be stable enough for tests and benchmark summaries.

## Migration Plan

### Phase 1: Extract Compiler and Quality Boundaries

Goal: reduce mixed responsibilities without changing the external API contract.

Required work:

- Move deterministic helpers out of `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py` into `compiler/` modules.
- Move low-quality predicates and fallback-reason logic out of `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py` into `quality/` modules.
- Keep `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py` as orchestration only.
- Extend `AuthorState` with full source telemetry and quality trace.
- Keep behavior intentionally close to current behavior; this phase is mostly structural plus observability.

Recommended extraction order:

1. `compiler/endings.py` and `compiler/routes.py`
2. `quality/endings.py` and `quality/routes.py`
3. `compiler/story_frame.py` and `compiler/beats.py`
4. `quality/story_frame.py` and `quality/beats.py`
5. `compiler/bundle.py`

### Phase 2: Extract Generation Facade and Productize Benchmarks

Goal: make future stability work cheaper and measurable.

Required work:

- Split domain generation logic in `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/gateway.py` into `generation/` modules.
- Keep a thin compatibility facade so workflow call sites do not need to know transport details.
- Add canonical benchmark brief sets under `benchmarks/briefs.py`.
- Add a benchmark runner under `benchmarks/runner.py` that can:
  - run a named brief suite
  - execute 5-run or N-run passes
  - compare baseline and candidate outputs
  - write JSON and Markdown reports under `/Users/lishehao/Desktop/Project/RPG_Demo/artifacts/benchmarks/`

## Required Implementation Areas

- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py`
- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/gateway.py`
- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/contracts.py`
- `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/checkpointer.py`
- new modules under `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/generation/`
- new modules under `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/compiler/`
- new modules under `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/quality/`
- new modules under `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/benchmarks/`
- `/Users/lishehao/Desktop/Project/RPG_Demo/tests/test_author_workflow.py`
- additional focused tests for compiler, quality, and benchmark code

## Acceptance Criteria

1. `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/workflow.py` no longer contains domain-level deterministic compiler helpers such as `build_default_*`, `normalize_*`, `compile_*`, or `_is_low_quality_*`, except for thin node-local glue that delegates to extracted modules.
2. The graph records source telemetry and quality reasons for `story_frame`, `beat_plan`, `route_affordance`, and `ending`, and those fields are visible in the returned backend state.
3. Existing API-level behavior remains backward compatible for `run_author_bundle(...)` and `/author/design-bundles`.
4. There is a canonical benchmark runner that writes both `.json` and `.md` reports to `/Users/lishehao/Desktop/Project/RPG_Demo/artifacts/benchmarks/`.
5. The benchmark runner can compare at least one fixed brief suite across baseline and candidate implementations.
6. Unit and integration tests pass after the refactor.
7. Each material sub-pass ends with a 5-run full-generation A/B test saved as an artifact.

## Required Tests

- Preserve and update current integration coverage in `/Users/lishehao/Desktop/Project/RPG_Demo/tests/test_author_workflow.py`.
- Add focused unit tests for:
  - compiler story-frame normalization
  - compiler beat-plan stabilization
  - compiler route supplementation
  - compiler ending canonicalization
  - quality predicates and reason emission for story frame, beats, routes, and endings
- Add integration tests that assert telemetry fields are populated in graph state.
- Add a benchmark smoke test that runs the benchmark runner with a fake gateway and verifies JSON/Markdown report output.

## Review Strategy

- Review the refactor by layer, not by file count.
- First verify that `workflow.py` became thinner for the right reasons rather than merely moving code around blindly.
- Then verify telemetry and quality-reason semantics.
- Then verify benchmark runner determinism and artifact format.
- Treat any prompt rewrite or unrelated schema change as out of scope unless it is required to keep the extracted modules working.

## Explicit Non-Goals

- No frontend or play-runtime work.
- No provider migration or model swap.
- No attempt to solve creativity quality purely by adding more prompt restrictions.
- No persistent checkpoint backend in this pass; `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/checkpointer.py` may stay in-memory.
- No full contract split of `/Users/lishehao/Desktop/Project/RPG_Demo/rpg_backend/author/contracts.py` if that would dominate the pass.
- No broad product redesign of `DesignBundle`.
