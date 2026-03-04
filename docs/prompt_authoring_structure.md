# Prompt Authoring Structure (Current Baseline)

This document explains the current prompt-authoring pipeline used by `/v2/stories/generate` in `prompt` mode.

Goal:
- give reviewers a concrete view of prompt structure and constraints
- make it easy to suggest improvements with minimal code-reading overhead

Scope:
- story generation prompt compile path only (`PromptCompiler`)
- no runtime route/narration prompt details in this document

Last verified against code:
- `rpg_backend/generator/prompt_compiler.py`
- `rpg_backend/llm/json_gateway.py`
- `rpg_backend/generator/spec_outline_schema.py`
- `rpg_backend/generator/spec_schema.py`

## V2 Prompt Structure Delta

Step 31-B upgraded authoring structure from free-form instructions to sectioned contract prompts in both stages.

What changed:
- hard physical split between narrative intent and hard schema constraints
- enum anchoring injected as markdown list near output requirements
- stronger contract wording (`JSON only`, `no extra text`, `schema violations crash runtime parsing`)

New payload field added in both stage-1 and stage-2:
- `npc_conflict_tag_catalog_markdown: str`
- existing `npc_conflict_tag_catalog` dict is retained

Review focus for this delta:
1. Constraint clarity: section headings make hard limits visually dominant.
2. Enum adherence: markdown anchoring should reduce invalid `conflict_tags`.
3. Schema stability: no change to compile budget or error-code semantics.
4. Tail failure trend: watch for reduction in `prompt_outline_invalid` and `prompt_spec_invalid`.

Live verification policy for this step:
- run live marker tests at end of flow
- outcome is recorded as evidence only (`live_passed|live_failed|live_skipped_missing_env`)
- live failure/skip is non-blocking for merge.

## 1) End-To-End Call Path

Prompt mode execution path:
1. `POST /v2/stories/generate` receives `prompt_text`
2. `GeneratorPipeline.run(...)`
3. `GeneratorPipeline.compile_or_plan(...)`
4. `PromptCompiler.compile(...)`
5. `JsonGateway.call_json_object(...)` (gateway mode: `local` or `worker`)
6. returns validated `StorySpec`, then planner/builder/linter continue

## 2) Compile Budget And Control Flow

`PromptCompiler` is strict two-stage compile with max 3 model calls:
- Call 1: `outline` generation (`StorySpecOutline`)
- Call 2: full `spec` generation (`StorySpec`)
- Call 3: full `spec` regeneration only if call 2 fails schema validation

Failure behavior:
- outline schema fail -> `prompt_outline_invalid`
- full spec schema fail after retry -> `prompt_spec_invalid`
- transport/provider/config error -> `prompt_compile_failed`

No fallback to seed planner when prompt compile fails.

## 3) Stage 1 Prompt (Outline)

### 3.1 Stage 1 System Prompt Intent

`outline_prompt` asks model to:
- output JSON only
- produce compact outline, not full spec
- satisfy hard limits (title/premise/tone/stakes lengths)
- produce exactly 4 beats, exactly 4 NPCs
- include `conflict_tags` for each NPC (1..3 from fixed enum)
- align `red_line` semantics with `conflict_tags`
- preserve strategy triangle feasibility for downstream scenes
- design debt that can be paid back in final beats

### 3.2 Stage 1 User Payload Shape

Actual payload is JSON serialized as `user_prompt`.

Top-level keys:
- `task`: `"compile_story_outline"`
- `prompt_text`
- `target_minutes`
- `npc_count`
- `style`
- `attempt_index`
- `attempt_seed`
- `required_move_bias_tags`
- `required_ending_shapes`
- `field_limits` (outline limits)
- `style_targets` (path-based writing hints)
- `npc_conflict_tag_catalog` (allowed tags + meaning)
- `npc_conflict_tag_catalog_markdown` (stable markdown bullet list for enum anchoring)
- `output_schema` (`StorySpecOutline` JSON schema)

## 4) Stage 2 Prompt (Full Spec)

### 4.1 Stage 2 System Prompt Intent

`spec_prompt` asks model to:
- expand the outline into full `StorySpec` JSON only
- satisfy full limits (`title<=120`, `premise<=400`, ...)
- keep grounded realism
- keep `red_line` and `conflict_tags` semantically aligned
- preserve delayed consequence structure

### 4.2 Stage 2 User Payload Shape

Call 2 payload:
- `task`: `"compile_story_spec_from_outline"`
- same common fields as stage 1
- `outline` (validated stage-1 object)
- `field_limits` (spec limits)
- `npc_conflict_tag_catalog`
- `npc_conflict_tag_catalog_markdown`
- `output_schema` (`StorySpec` JSON schema)
- `compile_call`: `2`
- `validation_feedback`: `[]`

Call 3 payload (retry):
- same as above
- `compile_call`: `3`
- `validation_feedback`: list of path-level validation diagnostics
- `retry_instruction`: explicit instruction to regenerate full JSON and fix violations

## 5) Validation Feedback Format

When schema validation fails, compiler builds structured feedback items:
- one item per unique path (deduplicated)
- includes:
  - path (for example `npcs.2.conflict_tags.0`)
  - error type
  - constraint hints from validation context (if available)
  - optional target style hint for selected paths

Current max feedback items:
- `12`

Example style targets:
- `premise_core`: 1-2 concise sentences
- `beats.*.required_event`: snake_case tag style, 3-5 words
- `beats.*.conflict`: short 8-14 word sentence
- `npcs.*.conflict_tags`: choose from fixed enum only

## 6) Output Schemas Enforced

Stage 1 schema:
- `StorySpecOutline` (`spec_outline_schema.py`)
- exact counts for beats/NPCs/constraints in outline phase

Stage 2 schema:
- `StorySpec` (`spec_schema.py`)
- ranges for beats/NPCs/constraints
- strict field limits and enum constraints

Important:
- schema validation is hard fail, not best-effort cleanup

## 7) Transport Layer (JsonGateway) Contract

`PromptCompiler` does not call provider directly; it calls `JsonGateway`.

Gateway modes:
- `local`: direct OpenAI-compatible chat-completions call
- `worker`: internal worker task call

Shared behavior:
- JSON-object mode body builder
- retriable error policy (bounded retries, current upper clamp at 3)
- returns `{payload, attempts, duration_ms}` on success
- throws `JsonGatewayError` with `error_code/message/retryable/status_code/attempts`

## 8) Known Pain Points (For Reviewer Context)

Observed from existing reports (`reports/llm_story_generation_eval*.json`):
- generation pass rate is close but below hard threshold:
  - `generation_success_rate` often `0.9583 ~ 0.9861` (gate requires `1.0`)
- top compile failures are still present:
  - `prompt_outline_invalid`
  - `prompt_spec_invalid`
- route quality is strong (`llm_route_success_rate` high), but prompt-compile strictness still creates tail failures

This means current system is high quality but brittle at the strict edge.

## 9) Review Checklist (How To Improve)

Reviewers should evaluate:
1. Prompt clarity:
- Are hard constraints grouped and unambiguous?
- Are there conflicting instructions between compactness and richness?

2. Schema alignment:
- Does system prompt over-constrain fields beyond schema?
- Are any required fields weakly instructed (especially nested arrays)?

3. Retry usefulness:
- Is validation feedback concise enough for model correction?
- Are retry instructions explicit enough for full regeneration behavior?

4. Token efficiency:
- Is any repeated payload data unnecessary across stage 2 retries?
- Can hints be compressed without harming adherence?

5. Robustness:
- Which validation errors are most frequent and should get dedicated prompt hints?
- Should some constraints move from free text to stronger structured fields?

## 10) Suggested Improvement Experiments

To keep changes measurable, propose one experiment at a time:

1. Constraint refactor experiment
- rewrite stage prompts into numbered constraint blocks
- expected: lower `prompt_spec_invalid`
- risk: longer prompt, higher latency

2. Feedback compression experiment
- compact validation feedback to short machine-readable tuples
- expected: clearer retry correction behavior
- risk: reduced semantic guidance for nuanced text fields

3. Instruction separation experiment
- separate style guidance from hard schema constraints
- expected: fewer conflicting generations
- risk: tone quality drift if style hints become too weak

4. Enum anchoring experiment
- repeat allowed enum values near every relevant nested field instruction
- expected: fewer invalid enum outputs
- risk: prompt verbosity increase

## 11) What To Send Back In A Review

Ask reviewers to return:
1. Proposed revised stage-1 prompt text
2. Proposed revised stage-2 prompt text
3. Any payload shape adjustments
4. Expected impact hypothesis
5. Validation criteria (what metric should improve)

This makes review feedback directly actionable in code.
