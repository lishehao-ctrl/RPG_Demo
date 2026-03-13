# RPG Demo

Single-backend architecture powered by a direct Responses API integration.

## Current Architecture

```mermaid
flowchart LR
  A["Frontend"] --> B["Backend API"]
  B --> C["PlayAgent (Responses)"]
  B --> D["AuthorAgent (Responses)"]
  C --> E["Deterministic Play Runtime"]
  D --> F["LangGraph Author Workflow"]
  C --> G["Responses API"]
  D --> G
  B --> H["response_session_cursors"]
```

- No internal worker service in the active runtime path.
- Play Mode keeps deterministic resolution logic in backend code.
- Author Mode keeps LangGraph orchestration with deterministic non-LLM nodes.
- Provider-side KV reuse is done via `previous_response_id`, persisted per scope/channel in `response_session_cursors`.
- Cursor reuse invariant: if stored cursor model differs from current model, backend clears the cursor before any provider call.

## Core Runtime Paths

### Play Mode

Play Mode is single-agent at the LLM boundary and deterministic for state changes:

1. free-text player input goes to `PlayAgent.interpret_turn`
2. backend runtime resolves the chosen move, effects, and next scene deterministically
3. `PlayAgent.render_resolved_turn` turns the resolved state into player-facing narration

Button input skips interpretation and reuses the same deterministic resolution + render path.

### Author Mode

Author Mode keeps a LangGraph workflow, but beat generation is now direct:

1. `generate_story_overview`
2. `plan_beats`
3. `generate_beat`
4. `beat_lint`
5. `assemble_story_pack`
6. `normalize_story_pack`
7. `final_lint`

Important current behavior:

- only two Author LLM nodes remain: `generate_story_overview` and `generate_beat`
- each beat is generated directly as a full `BeatDraft` (no intermediate outline stage)
- generation is one beat at a time; if beat lint fails, only the current beat is retried
- accepted prior beats stay fixed and feed continuity through `last_accepted_beat`, `prefix_summary`, and `author_memory`

### Author Flow (Current)

```mermaid
flowchart TD
  A["generate_story_overview"] --> B["plan_beats"]
  B --> C["generate_beat"]
  C --> D["beat_lint"]
  D -->|"pass and more beats"| C
  D -->|"pass and all beats done"| E["assemble_story_pack"]
  D -->|"fail and retry budget remains"| C
  E --> F["normalize_story_pack"]
  F --> G["final_lint"]
  G -->|"pass"| H["review_ready"]
  G -->|"fail"| I["workflow_failed"]
```

### Assembly And Normalization

The final pack steps are intentionally separate:

- `assemble_story_pack` stitches accepted beat drafts into one `StoryPack`, injects cross-beat exits, adds global moves, and builds opening guidance inputs
- `normalize_story_pack` validates the pack shape and fills any missing standard fields such as `opening_guidance`
- `final_lint` is the playable-first gate before `review_ready`

### Cursor / KV Reuse

Responses cursor reuse is scoped by channel:

- Play: `play_agent`
- Author overview: `author_overview`
- Author beat generation: `author_beat`

On invalid or expired cursor errors, the backend clears the stored cursor and retries once without `previous_response_id`.
If cursor model mismatches current model, backend clears the cursor first and skips stale `previous_response_id` reuse.

## Responses Config

Use only these active env vars:

- `APP_RESPONSES_BASE_URL`
- `APP_RESPONSES_API_KEY`
- `APP_RESPONSES_MODEL`
- `APP_RESPONSES_TIMEOUT_SECONDS` (default `20.0`)
- `APP_RESPONSES_ENABLE_THINKING_PLAY` (default `false`)
- `APP_RESPONSES_ENABLE_THINKING_AUTHOR_OVERVIEW` (default `false`)
- `APP_RESPONSES_ENABLE_THINKING_AUTHOR_BEAT` (default `true`)
- `APP_RESPONSES_ENABLE_THINKING_STORY_QUALITY_JUDGE` (default `false`)

Recommended current defaults:

- Play keeps thinking off for latency
- Author overview usually keeps thinking off
- Author beat generation usually keeps thinking on
- Story quality judge can be toggled independently from runtime traffic

Reference template: [`/Users/lishehao/Desktop/Project/RPG_Demo/.env.llm.example`](/Users/lishehao/Desktop/Project/RPG_Demo/.env.llm.example)

## Local Development

```bash
./scripts/dev_stack.sh up
./scripts/dev_stack.sh ready
./scripts/dev_stack.sh logs backend
./scripts/dev_stack.sh logs frontend
```

Stop services:

```bash
./scripts/dev_stack.sh down
```

## Key API Contracts (unchanged)

- `POST /sessions`
- `POST /sessions/{session_id}/step`
- `POST /author/runs`

Public response shape for play/author remains stable; admin/dev telemetry fields now use single-agent semantics (`agent_model`, `agent_mode`, `response_id`, `reasoning_summary`).

## Migration Spec

Implementation contract for this migration:

- [`/Users/lishehao/Desktop/Project/RPG_Demo/responses_single_agent_migration_spec.md`](/Users/lishehao/Desktop/Project/RPG_Demo/responses_single_agent_migration_spec.md)
