# RPG_Demo xcode JSON Methodology

## Scope
- Provider mode: `xcode`
- Endpoint: `https://api.xcode.best/v1`
- Model baseline: `gpt-5.4-mini` (same behavior observed on `gpt-5.4`, `gpt-5`)
- Goal: stable structured JSON for author/play/helper full chain.

## Core Findings
1. Base URL must include `/v1`.
- `https://api.xcode.best` returns non-API HTML and breaks JSON workflows.

2. Non-stream chat completion content extraction is unreliable on xcode.
- `chat/completions` non-stream often returns `choices[0].message.content = null`.
- This happened even for plain-text prompts and both `json_object`/`json_schema`.

3. `response_type` / `content_type` flags do not fix non-stream null content.
- Tested variants (`response_type=json`, `content_type=json`, both) still returned null content in non-stream mode.

4. Streamed chat is stable for JSON output.
- `chat/completions` with `stream=true` emits `choices[].delta.content` reliably.
- Aggregating stream chunks produced valid JSON consistently in probes.

5. xcode enforces strict object schema rules for `response_format=json_schema`.
- `properties` must exist and cannot be empty.
- `additionalProperties` must be explicitly provided and set to `false`.
- `required` must be provided and include every key in `properties`.

## Production Strategy (RPG_Demo)
1. Keep JSON path on `chat/completions`.
2. Use policy-driven stream routing for JSON calls, then aggregate `delta.content` when stream is enabled.
3. Default JSON format on xcode: `response_format.type = "json_schema"`.
4. Schema normalization for xcode object schemas:
- Ensure non-empty `properties`.
- Force `additionalProperties=false`.
- Force `required == list(properties.keys())`.
5. Parse aggregated text into one JSON object; keep existing retry/failover semantics.

## Stream Policy Knobs (Gateway)
The transport now supports explicit policy controls instead of hard-coded behavior:

- `APP_RESPONSES_CHAT_JSON_STREAM_MODE=auto|force|off`
- `APP_RESPONSES_CHAT_JSON_STREAM_HOSTS=api.xcode.best,beecode.cc,...`

Behavior:
- `auto` (default): stream only when base URL host matches configured host set.
- `force`: always use stream for `/chat/completions` JSON calls.
- `off`: never use stream; use normal non-stream chat completion path.

Default behavior remains compatible with prior stable setup (`xcode`/`beecode` on stream).

## Default Schema Policy (No Caller Schema)
When caller does not provide schema, synthesize an object schema that satisfies xcode constraints:

```json
{
  "type": "object",
  "properties": {
    "_": {
      "type": "string",
      "description": "Optional placeholder."
    }
  },
  "required": ["_"],
  "additionalProperties": false
}
```

Rationale: this avoids provider-side `invalid_json_schema` while preserving a deterministic baseline contract.

## Probe Checklist Before Eval/Training
1. Config sanity:
- `LLM_ACTIVE_MODE=xcode`
- base URL includes `/v1`
- author/play/helper keys and RPM limits are set as expected.

2. Structured probe (`json_schema`):
- Run 10 calls for representative schema payloads.
- Target success rate: `>= 0.98`.

3. No-schema probe:
- Run 10 calls with transport default format path.
- Target: no `invalid_json_schema` error.

4. Endpoint health:
- Both keys receive traffic in probe window.
- No persistent single-key starvation.

## Known Failure Signatures
1. `message.content = null` (non-stream chat path).
2. `invalid_json_schema`: `additionalProperties is required to be false`.
3. `invalid_json_schema`: `required ... including every key in properties`.
4. `invalid_json_schema`: `object schema missing properties`.

## Recovery Playbook
1. Verify `/v1` base URL.
2. Verify xcode JSON path is stream aggregation (not non-stream content extraction).
3. Verify schema normalization is applied (properties/additionalProperties/required).
4. Re-run schema and no-schema probes.
5. If failure persists, stop long eval and collect probe artifacts for escalation.
