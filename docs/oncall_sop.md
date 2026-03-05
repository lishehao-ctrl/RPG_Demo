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
- Signals: `worker_failure_rate_high`, `llm_call_p95_high`.

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
2. Confirm backend process health: `GET /health`.
3. Compare with worker readiness: `GET http://<worker>/ready`.

Likely causes:
- DB unavailable or locked.
- Missing/invalid LLM configuration.
- Upstream LLM probe timeout/auth failure.

Mitigations:
1. Restore DB connectivity or release lock pressure.
2. Correct env/secrets (`APP_LLM_*`, `APP_LLM_WORKER_*`).
3. Temporarily reduce worker inflight limits.
4. Roll back latest backend/worker config release if regression is confirmed.

Exit criteria:
- `/ready` returns `200` consistently for at least two consecutive probe windows.

## worker_failure_rate_high

Signal criteria:
- worker mode call volume `>= APP_OBS_ALERT_WORKER_FAIL_MIN_COUNT`.
- worker failure rate `> APP_OBS_ALERT_WORKER_FAIL_RATE`.

Immediate checks:
1. Query `GET /admin/observability/llm-call-health?window_seconds=300&gateway_mode=worker`.
2. Inspect worker logs for `llm_worker_task_failed` grouped by `error_code`.
3. Verify worker `/ready` and backend `/ready`.

Likely causes:
- Upstream model 429/5xx spikes.
- Worker connection saturation or inflight misconfiguration.
- Bad deploy of worker task handlers.

Mitigations:
1. Lower inflight limits:
- `APP_LLM_WORKER_ROUTE_MAX_INFLIGHT`
- `APP_LLM_WORKER_NARRATION_MAX_INFLIGHT`
- `APP_LLM_WORKER_JSON_MAX_INFLIGHT`
2. Scale worker replicas temporarily.
3. Tune worker queue/quota knobs (`APP_LLM_WORKER_QUEUE_*`, `APP_LLM_WORKER_DEFAULT_RPM/TPM`, model limits JSON).
4. Roll back worker version/config if failures correlate with recent release.

Exit criteria:
- worker failure rate remains below threshold for two windows.

## llm_call_p95_high

Signal criteria:
- total LLM calls `>= APP_OBS_ALERT_LLM_CALL_MIN_COUNT`.
- per-call P95 latency `> APP_OBS_ALERT_LLM_CALL_P95_MS` (default `3000ms`).

Immediate checks:
1. Query `GET /admin/observability/llm-call-health?window_seconds=300`.
2. Split by stage:
- `...&stage=route`
- `...&stage=narration`
3. Split by gateway mode:
- `...&gateway_mode=worker`
- `...&gateway_mode=unknown` (for fallback/error classification)

Likely causes:
- Upstream model latency regression.
- Worker/network bottleneck.
- Prompt payload inflation.

Mitigations:
1. Reduce inflight limits to avoid queue collapse.
2. Scale worker horizontally.
3. Trim oversized prompt context if a recent change introduced payload bloat.
4. Roll back latest runtime/gateway changes if latency jump aligns with deploy.

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
- Worker task path failures in worker mode.

Mitigations:
1. Isolate failing path and revert the latest risky change.
2. Apply targeted config relief (retry/inflight/timeout) without breaking strict semantics.
3. Scale service if resource saturation is confirmed.

Exit criteria:
- 5xx rate is below threshold and top buckets are no longer growing.

## Standard Mitigation Levers

1. Reduce worker inflight values.
2. Increase worker replica count.
3. Tune worker queue and quota settings.
4. Roll back latest version/config.

## Incident Closure Template

1. Impact scope.
2. Trigger signal and threshold breached.
3. First response timestamp and ACK timestamp.
4. Mitigation timeline.
5. Root cause.
6. Preventive action items and owners.
