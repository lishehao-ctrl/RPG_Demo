# Deployment Probes

## Backend Probe Endpoints

- `GET /health` -> liveness
- `GET /ready` -> readiness

`/ready` includes:

- DB check
- responses config check (`APP_RESPONSES_*`)
- direct Responses probe (TTL-cached)

## Required Env For LLM Readiness

- `APP_RESPONSES_BASE_URL`
- `APP_RESPONSES_API_KEY`
- `APP_RESPONSES_MODEL`

## Kubernetes Notes

- Deploy backend only for LLM runtime (no internal worker deployment).
- Probe target is backend service only.
- Use backend deployment + service manifests under `deploy/k8s`.

## Systemd Notes

- Active unit files are backend and alert emitter units under `deploy/systemd`.
- No worker service unit is required in the active architecture.

