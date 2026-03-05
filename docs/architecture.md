# RPG_Demo Story Runtime Architecture (v3)

This document defines the current “north star” architecture for an **8–12 minute** interactive narrative RPG runtime.

## 1. Goals

### Product goals
- **8–12 minutes per playthrough** (target **14–16 steps**).
- Provider policy:
  - `openai`: quality-first failfast for route/narration failures.
- **Multiple NPCs**: 3–5 NPCs per story; each appears at least twice.

### Engineering goals
- **Deterministic state transitions** (LLM does not decide success/failure or next node).
- **Schema-first** story format with **lint + regenerate** loops for one-click generation.
- Runtime safety: no dead-ends, no infinite reroute loops, no “invalid input” stalls.

---

## 2. Core Model: Beat → Scene → Move → Outcome

### 2.1 Beat (macro structure)
**Purpose:** stabilize one-click generation and control pacing.

**Fields (conceptual):**
- `beat_id`, `title`
- `step_budget` (typically 3–4 steps)
- `required_events[]` (tags that must occur in this beat)
- `npc_quota` (min appearances / key interactions per NPC)
- `entry_scene_id`

**Constraints:**
- 3–5 beats total.
- Sum of beat `step_budget` ≈ 14–16 steps.

---

### 2.2 Scene (micro node)
**Purpose:** the player is “in” a scene; scenes form the playable graph.

**Fields (conceptual):**
- `scene_id`, `beat_id`
- `scene_seed` (short: situation + objective + conflict hook; not long prose)
- `present_npcs[]` (typically 1–2 primary NPCs in-scene)
- `enabled_moves[]` (4–5 visible moves; **never > 6**)
- `always_available_moves[]` (2–3 global moves; see below)
- `exit_conditions` (usually based on progress/event tags)

**Constraints:**
- Branching must **reconverge within 1–2 scenes** to prevent content explosion.
- Every scene must include **2–3 global moves** so the player can always proceed.

---

### 2.3 Move (action interface)
**Purpose:** the unit of intent and execution. **Moves are the executable interface**, not “choices”.

Moves are **parameterizable** and reusable across stories.

**Fields (conceptual):**
- `move_id`, `label`
- `strategy_style`: `fast_dirty | steady_slow | political_safe_resource_heavy`
- `intents/synonyms[]` (free-text routing surface)
- `args_schema` (optional; e.g., `target_npc_id`, `tone`, `goal_tag`)
- `resolution_policy` (deterministic rule for outcome selection)
- `outcomes` (see below)

**Constraints:**
- Every move must have at least:
  - `success`
  - `fail_forward` (**required**)
- `partial_success` is strongly recommended for richer gameplay.
- In each scene, non-global `enabled_moves` must cover all three strategy styles (hard lint error otherwise).

### 2.5 NPC Profiles
StoryPack includes explicit NPC profile metadata:
- `npc_profiles[]`: `{name, red_line, conflict_tags[]}`
- `red_line` is the NPC's non-negotiable constraint and must exist for every listed NPC.

---

### 2.4 Outcome (fail-forward execution)
**Purpose:** make every input “count”. Preconditions do not block execution; they **select a different outcome**.

**Fields (conceptual):**
- `result`: `success | partial | fail_forward`
- `effects`: deterministic deltas (state updates, relation shifts, flags)
- `next_scene_id`: may equal success target to reconverge
- `narration_slots`: structured beats for narration:
  - `npc_reaction`
  - `world_shift`
  - `clue_delta`
  - `cost_delta`
  - `next_hook`

**Constraints:**
- **No refusal**: unmet conditions → `fail_forward`, not “locked/invalid”.
- **Fail-forward must still progress**:
  - advance `beat_progress/scene_progress`, or
  - trigger required event tags, or
  - create a meaningful state change + move to a resolving scene.

---

## 3. Global Moves (Gameplay Backbone)

Each scene must include 2–3 global moves. Minimum set:
- `global.clarify`: low-confidence input → NPC asks/forces clarification **while advancing tension/progress**
- `global.look`: observation/scan → reveals a clue or changes situation slightly
- `global.help_me_progress`: “I don’t know what to do” → offers concrete next options + small progress

**Rule:** global moves remain available choices and button fallback targets, but text routing to `global.help_me_progress` is only allowed for explicit help/stuck intent.

---

## 4. Runtime Pipeline (Two-Pass)

### Pass A — Intent Routing
Input → `MoveInvocation`
- Button input: directly creates `MoveInvocation(move_id, args={})`.
- Free-text input: LLM (or heuristic) outputs structured JSON:
  - `move_id`
  - `args` (optional)
  - `confidence`
  - `interpreted_intent` (one sentence)

**Low confidence policy:**
- `openai`: if confidence < threshold, parse fails, or move is invalid, failfast this step with `503`.
- for non-help text, router excludes `global.help_me_progress` from LLM candidate moves.
- backend LLM transport is worker-only: backend calls internal LLM worker (`/internal/llm/tasks/*`), worker calls upstream OpenAI-compatible endpoint.

### Pass B — Outcome Resolution (Deterministic)
`MoveInvocation + scene + state` → choose an `Outcome`
- Evaluate preconditions (if any) **only to select outcome**, not to reject.
- If unmet: choose `fail_forward`.
- Otherwise: choose `success` or `partial` according to `resolution_policy`.
- Apply `effects`, update progress, transition to `next_scene_id`.
- Runtime tracks fixed pressure debt:
  - `public_trust`
  - `resource_stress`
  - `coordination_noise`
- In the final two beats, pressure recoil can trigger extra costs/consequences based on these tracks.
- Runtime maintains `npc_trust::<name>` and derives stance buckets (`support|contested|oppose`) from red-line alignment.

### Narration (LLM or template)
Narration renders `narration_slots` into player-facing text using a strict template:
- **Echo**: restate interpreted intent (paraphrase)
- **Commit**: state the consequence (NPC reaction + cost)
- **Hook**: present the next actionable direction

**Safety:** narration must not leak internal fields/ids/markers; enforce a denylist + final guard. In strict providers, narration errors failfast instead of template fallback.
- Narration commit layer periodically surfaces stance state (who supports, who opposes, whose red line was hit).

---

## 5. Pacing Rules (8–12 minutes)

### Defaults
- **14–16 steps** to reach an ending.
- Per step target reading time: ~25–40 seconds (short text, concrete options).

### Story authoring invariants
- Each step produces at least one player-visible change:
  - state delta (time/heat/resource), or
  - relation change (NPC trust/affection), or
  - progress/event tag, or
  - scene transition.
- Branch depth ≤ 2 scenes before reconvergence.

---

## 6. API Surface

Path governance:
- backend paths are centralized in `rpg_backend/api/route_paths.py`.
- worker task paths are centralized in `rpg_backend/llm_worker/route_paths.py`.
- router registration is centralized in `rpg_backend/api/router_registry.py`.

Auth governance:
- all business/admin routes require Bearer token.
- anonymous routes are limited to: `POST /admin/auth/login`, `GET /health`, `GET /ready`.
- worker internal task routes require `X-Internal-Worker-Token`.
- worker header value comes from `APP_INTERNAL_WORKER_TOKEN`.

### Stories
- `POST /stories` — create draft with raw `pack_json`
- `POST /stories/{story_id}/publish` — publish a version (store raw `pack_json`)
- `GET /stories/{story_id}?version=...` — returns response object with `pack` = raw `pack_json`

### Sessions
- `POST /sessions` — create session bound to `{story_id, version}`, initialize `state`, set `current_scene_id`
- `GET /sessions/{session_id}` — fetch current status (optionally `dev_mode` for full state)

### Step (player action)
- `POST /sessions/{session_id}/step`
  - Request:
    - `client_action_id` (idempotency)
    - `input`: `{type:"button"|"text", move_id?, text?}`
    - `dev_mode?`
  - Response (minimum):
    - `scene_id`, `narration_text`
    - `recognized`: `{interpreted_intent, move_id, confidence, route_source, llm_duration_ms?, llm_gateway_mode?}`
    - `resolution`: `{result, costs_summary, consequences_summary}`
    - `ui`: `{moves:[{move_id,label,risk_hint}], input_hint}`
    - `debug` (dev only): `{selected_move, selected_outcome, selected_strategy_style, pressure_recoil_triggered, stance_snapshot, state, beat_progress}`
  - Contract note:
    - `recognized/resolution/ui/debug` are strict typed objects (unknown keys rejected)
    - `debug` key is omitted when `dev_mode=false`

**Step contract:** `POST /sessions/{session_id}/step` may return:
- `503` on strict LLM failures (route error, low confidence, invalid move, narration failure)
- `409` with `error.code=session_conflict_retry` when optimistic CAS detects a concurrent turn advance

### Admin Auth & User Management
- `POST /admin/auth/login` — issue JWT access token from `{email,password}`
- `GET /admin/users` — list admin users
- `GET /admin/users/{user_id}` — fetch admin user profile

### Admin Diagnostics
- `GET /admin/sessions/{session_id}/timeline` — structured replay events (`step_started|step_succeeded|step_failed|step_replayed|step_conflicted`)
- `POST /admin/sessions/{session_id}/feedback` — attach `good|bad` verdict and tags/notes to a session
- `GET /admin/sessions/{session_id}/feedback` — list feedback markers for a session
- `GET /admin/observability/runtime-errors` — rolling window 503 aggregation by `error_code|stage|model`
- `GET /admin/observability/http-health` — HTTP request health (`5xx rate`, `p95`, `top_5xx_paths`) with `window_started_at/window_ended_at`
- `GET /admin/observability/llm-call-health` — per-call LLM health (`failure_rate`, `p95`) with fixed groups:
  - `by_stage`: `route/narration/json/unknown`
  - `by_gateway_mode`: `local/worker/unknown` (new traffic should be `worker` or `unknown`)
- `GET /admin/observability/readiness-health` — backend/worker readiness failures + streaks with `window_started_at/window_ended_at`

### One-click generation (author tooling)
- `POST /stories/generate`
  - Request: `{prompt_text?, seed_text?, target_minutes, npc_count, style?, publish?}`
  - Output:
    - `story_id, version?, pack, pack_hash`
    - `generation.mode` (`prompt|seed`)
    - `generation.compile.{spec_hash,spec_summary}`
    - `generation.lint.{errors,warnings}`
    - `generation.{attempts,regenerate_count,candidate_parallelism,attempt_history}`

Business endpoints use a unified error envelope:
- `{ "error": { "code", "message", "retryable", "request_id", "details" } }`

---

## 7. Linter & Regenerate

### Linter checks
- Schema validity
- Reference validity: `next_scene_id`, `move_id`, `outcome_id` exist
- Every move has `fail_forward`
- Every scene includes required global moves (2–3)
- Every scene includes full strategy triangle coverage (excluding `global.*`)
- `npc_profiles` fully match `npcs` (no missing/extra/duplicate names)
- Banned move IDs (e.g. `inspect_relic`) fail lint
- Reachability: entry → all required scenes reachable
- Existence of at least one ending path within 14–16 steps
- Basic cycle risk: ensure there is a terminating route
- Text leak guard: denylist scan on narration seeds (ids, debug markers)

### Regenerate loop (strict mode)
- Build pack and run linter.
- If linter fails, regenerate the full pack with derived seed.
- Max retries: 3 regenerates (4 total attempts).
- Prompt mode regenerates by rerunning `PromptCompiler + build + lint`.
- No local post-generation mutation of generated pack.
- Internal implementation is pipeline-based:
  - `generator/pipeline.py`: orchestration (`validate -> compile/plan -> execute candidates -> resolve`)
  - `generator/candidate_executor.py`: candidate parallelism + winner/best selection
  - `generator/result_builder.py`: diagnostics + `GeneratorBuildResult` assembly
  - `generator/errors.py`: `GeneratorBuildError` construction and mapping
  - imports are explicit module imports; no legacy facade or wrapper path

---

## 8. One-click Generation Pipeline (recommended)

1. **Prompt/Seed → Beat Plan** (prompt mode uses two-stage compile: outline -> full spec, strict max 3 calls)  
2. **Beat Plan → Scenes graph** (14–16 scenes, reconverging)
3. **Scenes → Moves/Intents** (4–5 visible + 2–3 global per scene)
4. **Outcomes fill** (success/partial/fail_forward; deterministic policies)
5. **Lint + Regenerate** (up to 3 retries)
6. **Publish + Playtest** (simulate one run; export transcript)

---

## 9. Observability & Testing

### Runtime telemetry (minimum)
- Request correlation: every request gets `X-Request-ID` (from inbound header or generated), propagated to response, logs, and runtime events
- Structured logs: JSON lines with `ts,level,service,env,event,request_id` plus context fields (`method,path,status_code,duration_ms,session_id,story_id,turn_index,error_code,stage,route_model,narration_model`)
- Route result: `move_id`, confidence, route source
- Resolution result: success/partial/fail_forward, applied deltas
- Progress: beat/scene progress increments
- Session timeline events persisted for replay and diagnostics (`step_started|step_succeeded|step_failed|step_replayed|step_conflicted`)
- User-side quality markers (`good|bad`) linked to session and turn index
- Runtime 503 aggregation: 5-minute rolling buckets keyed by `error_code|stage|model`, with sample `session_id/request_id`
- Request event sampling: every request stores `{service, method, path, status_code, duration_ms, request_id}`
- LLM call event sampling: route/narration/json calls store `{stage, gateway_mode, success, error_code, duration_ms}`
- Readiness probe event sampling: backend/worker `/ready` writes `{ok, error_code, latency_ms, request_id}`
- Alerting: cron-driven webhook emitter (`scripts/emit_runtime_alerts.py`) with cooldown dedupe via dispatch table and signal keys:
  - `http_5xx_rate_high`
  - `backend_ready_unhealthy`
  - `worker_failure_rate_high`
  - `llm_call_p95_high`
- Acceptance metrics:
  - meaningful_accept_rate (state/progress changed)
  - llm_route_success_rate
  - global_help_route_rate (diagnostic KPI)
  - non_global_text_route_rate (diagnostic KPI)
  - strategy_triangle_coverage_rate
  - pressure_recoil_trigger_rate
  - npc_stance_mentions_per_run_avg
  - step_error_rate

### Canary tests (must remain green)
- Healthy-path provider behavior: valid text/button inputs produce 200 and advance or change state (except inactive session)
- LLM route/narration failures produce 503 with structured error detail
- Preconditions unmet → `fail_forward` outcome
- Sample story completes within 14–16 steps

---

## 10. Notes on Extensibility

Move templates do not limit the game if treated as **interfaces**:
- Add story-specific moves for unique mechanics (e.g., `hack_terminal`, `cross_examine`)
- Keep global moves small and stable
- Prefer parameterization over move explosion to maintain routing accuracy
