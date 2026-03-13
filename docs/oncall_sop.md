# Oncall SOP

This runbook defines acknowledgement targets, triage flow, and mitigation steps for backend runtime alerts emitted by `scripts/emit_runtime_alerts.py`.

## Severity And SLA

- `critical`
- ACK within 5 minutes.
- Mitigate within 15 minutes.
- Signals: `backend_ready_unhealthy`, `http_5xx_rate_high`.

- `warning`
- ACK within 15 minutes.
- Mitigate or document accepted risk within 60 minutes.
- Signals: `responses_failure_rate_high`, `llm_call_p95_high`.

## First Response Checklist

1. Acknowledge the alert in your oncall channel/ticket.
2. Capture timestamp, signal name, service environment, and request window.
3. Query observability endpoints for corroboration:
- `GET /admin/observability/http-health?window_seconds=300`
- `GET /admin/observability/llm-call-health?window_seconds=300`
- `GET /admin/observability/readiness-health?window_seconds=300`
   - all `/admin/*` queries require Bearer token from `POST /admin/auth/login`.
4. Check latest deploy/config changes in the last 30 minutes.
5. Start mitigation if threshold is still breached.

## backend_ready_unhealthy

Signal criteria:
- backend readiness fail streak `>= APP_OBS_ALERT_READY_FAIL_STREAK`.

Immediate checks:
1. Call `GET /ready` and inspect `checks.db`, `checks.llm_config`, `checks.llm_probe`.
   - use `GET /ready?refresh=true` when you need to bypass readiness probe cache.
2. Confirm backend process health: `GET /health`.
3. Confirm readiness-health counters for `backend` and `responses` channels.

Likely causes:
- DB unavailable or locked.
- Missing/invalid Responses configuration.
- Upstream Responses probe timeout/auth failure.
- Readiness cache stale data during active upstream incidents (verify with `refresh=true`).

Mitigations:
1. Restore DB connectivity or release lock pressure.
2. Correct env/secrets (`APP_RESPONSES_BASE_URL`, `APP_RESPONSES_API_KEY`, `APP_RESPONSES_MODEL`).
3. Reduce request pressure or step traffic while upstream provider is unstable.
4. Roll back latest backend config release if regression is confirmed.

Exit criteria:
- `/ready` returns `200` consistently for at least two consecutive probe windows.

## responses_failure_rate_high

Signal criteria:
- responses mode call volume `>= APP_OBS_ALERT_RESPONSES_FAIL_MIN_COUNT`.
- responses failure rate `> APP_OBS_ALERT_RESPONSES_FAIL_RATE`.

Immediate checks:
1. Query `GET /admin/observability/llm-call-health?window_seconds=300&gateway_mode=responses`.
2. Inspect backend logs for `llm_call_failed` and provider error classifications.
3. Verify backend `/ready` probe detail for responses status.

Likely causes:
- Upstream model 429/5xx spikes.
- Expired/invalid Responses credentials.
- Prompt/output drift causing strict JSON parse failures.

Mitigations:
1. Verify credentials, base URL, and model config in environment.
2. Raise timeout guard if failures are dominated by provider timeouts (`APP_RESPONSES_TIMEOUT_SECONDS`).
3. Check whether the spike is concentrated in a route with thinking enabled, especially Author beat generation.
4. Roll back latest runtime prompt/config release if failures correlate with recent deploy.

Exit criteria:
- responses failure rate remains below threshold for two windows.

## llm_call_p95_high

Signal criteria:
- total LLM calls `>= APP_OBS_ALERT_LLM_CALL_MIN_COUNT`.
- per-call P95 latency `> APP_OBS_ALERT_LLM_CALL_P95_MS` (default `3000ms`).

Immediate checks:
1. Query `GET /admin/observability/llm-call-health?window_seconds=300`.
2. Split by stage:
- `...&stage=interpret_turn`
- `...&stage=render_resolved_turn`
3. Split by gateway mode:
- `...&gateway_mode=responses`
- `...&gateway_mode=unknown` (for fallback/error classification)

Likely causes:
- Upstream model latency regression.
- Oversized prompt payloads in play/author flows.
- Elevated retry volume after cursor invalidation.

Mitigations:
1. Trim oversized context payloads in recent changes.
2. Tune `APP_RESPONSES_TIMEOUT_SECONDS` to avoid long-hanging requests.
3. Roll back latest runtime/agent prompt release if latency jump aligns with deploy.

Exit criteria:
- `p95_ms` drops below threshold for two windows and 5xx/error rates do not rise.

## http_5xx_rate_high

Signal criteria:
- total requests `>= APP_OBS_ALERT_HTTP_5XX_MIN_COUNT`.
- 5xx rate `> APP_OBS_ALERT_HTTP_5XX_RATE`.

Immediate checks:
1. Query `GET /admin/observability/http-health?window_seconds=300`.
2. Inspect `top_5xx_paths`.
3. Cross-check runtime buckets: `GET /admin/observability/runtime-errors?window_seconds=300`.

Likely causes:
- Runtime strict failures concentrated on `/sessions/*/step`.
- Readiness failures (`/ready`) causing infra churn.
- Responses transport or cursor fallback failures.

Mitigations:
1. Isolate failing path and revert the latest risky change.
2. Apply targeted config relief (timeout/retry pressure) without breaking strict semantics.
3. Scale backend service if resource saturation is confirmed.

Exit criteria:
- 5xx rate is below threshold and top buckets are no longer growing.

## Standard Mitigation Levers

1. Validate Responses env and secret injection.
2. Tune Responses timeout and the per-route thinking toggles.
3. Reduce load via traffic shaping if provider incident is ongoing.
4. Roll back latest backend version/config.

## Incident Closure Template

1. Impact scope.
2. Trigger signal and threshold breached.
3. First response timestamp and ACK timestamp.
4. Mitigation timeline.
5. Root cause.
6. Preventive action items and owners.
