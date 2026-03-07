# Deployment Probes: `/health` for liveness, `/ready` for readiness

This backend uses split probe semantics:
- `GET /health`: process liveness only (lightweight, no dependency checks)
- `GET /ready`: strict readiness (DB + LLM config + cached LLM `who are you` probe)
- backend `/ready` checks worker readiness (backend does not probe upstream LLM directly).
- `/health` is excluded from 5xx alert-rate calculation by default.

## Kubernetes

Templates are provided in:
- `deploy/k8s/rpg-backend-deployment.yaml`
- `deploy/k8s/rpg-backend-configmap.yaml`
- `deploy/k8s/rpg-backend-secret.example.yaml`
- `deploy/k8s/rpg-observability-alerts-cronjob.yaml`

### Apply

```bash
kubectl apply -f deploy/k8s/rpg-backend-configmap.yaml
kubectl apply -f deploy/k8s/rpg-backend-secret.example.yaml
kubectl apply -f deploy/k8s/rpg-backend-deployment.yaml
kubectl apply -f deploy/k8s/rpg-llm-worker-deployment.yaml
kubectl apply -f deploy/k8s/rpg-llm-worker-service.yaml
kubectl apply -f deploy/k8s/rpg-llm-worker-hpa.yaml
kubectl apply -f deploy/k8s/rpg-observability-alerts-cronjob.yaml
```

Important:
- `APP_DATABASE_URL` is expected from secret (`deploy/k8s/rpg-backend-secret.example.yaml`), not configmap.
- Backend/worker do not rely on local SQLite files in Kubernetes.
- Secret should include auth/runtime critical keys:
  - `APP_AUTH_JWT_SECRET`
  - `APP_ADMIN_BOOTSTRAP_EMAIL`
  - `APP_ADMIN_BOOTSTRAP_PASSWORD`
  - `APP_INTERNAL_WORKER_TOKEN`
  - `APP_LLM_OPENAI_BASE_URL`
  - `APP_LLM_OPENAI_API_KEY`
  - `APP_OBS_ALERT_WEBHOOK_URL`

### Release sequence (manual migration mode)

```bash
# 1) migrate DB first
./scripts/k8s/k8s_db_migrate_manual.sh head

# 2) deploy backend/worker manifests
kubectl apply -f deploy/k8s/rpg-backend-deployment.yaml
kubectl apply -f deploy/k8s/rpg-llm-worker-deployment.yaml

# 3) verify rollout and probes
./scripts/k8s/k8s_verify_rollout.sh
```

If deployment fails:

```bash
./scripts/k8s/k8s_rollback_last.sh
```

Only run DB downgrade when incident assessment confirms schema rollback is required.

### Probe wiring

- `livenessProbe`: `GET /health`
- `readinessProbe`: `GET /ready`
- `startupProbe`: `GET /health`

Notes:
- Keep readiness period moderate (default template uses 15s) to avoid unnecessary probe traffic.
- `/ready` LLM check uses in-process cache (`APP_READY_LLM_PROBE_CACHE_TTL_SECONDS`, default `30`).

### Alert emitter CronJob

- runs every 60s with `concurrencyPolicy: Forbid`.
- executes `scripts/emit_runtime_alerts.py` with `APP_OBS_ALERT_WINDOW_SECONDS`.
- uses the same configmap/secret inputs as backend, including `APP_OBS_ALERT_WEBHOOK_URL`.

## systemd (process manager)

Units are provided in:
- `deploy/systemd/rpg-backend.service`
- `deploy/systemd/rpg-backend-readiness.service`
- `deploy/systemd/rpg-backend-readiness.timer`
- `deploy/systemd/rpg-llm-worker.service`
- `deploy/systemd/rpg-llm-worker-readiness.service`
- `deploy/systemd/rpg-llm-worker-readiness.timer`
- `deploy/systemd/rpg-alert-emitter.service`
- `deploy/systemd/rpg-alert-emitter.timer`

### Install

```bash
sudo cp deploy/systemd/rpg-backend.service /etc/systemd/system/
sudo cp deploy/systemd/rpg-backend-readiness.service /etc/systemd/system/
sudo cp deploy/systemd/rpg-backend-readiness.timer /etc/systemd/system/
sudo cp deploy/systemd/rpg-llm-worker.service /etc/systemd/system/
sudo cp deploy/systemd/rpg-llm-worker-readiness.service /etc/systemd/system/
sudo cp deploy/systemd/rpg-llm-worker-readiness.timer /etc/systemd/system/
sudo cp deploy/systemd/rpg-alert-emitter.service /etc/systemd/system/
sudo cp deploy/systemd/rpg-alert-emitter.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rpg-backend.service
sudo systemctl enable --now rpg-backend-readiness.timer
sudo systemctl enable --now rpg-llm-worker.service
sudo systemctl enable --now rpg-llm-worker-readiness.timer
sudo systemctl enable --now rpg-alert-emitter.timer
```

### Verify

```bash
systemctl status rpg-backend.service
systemctl status rpg-backend-readiness.timer
systemctl list-timers | rg rpg-backend-readiness
systemctl status rpg-llm-worker.service
systemctl status rpg-llm-worker-readiness.timer
systemctl list-timers | rg rpg-llm-worker-readiness
systemctl status rpg-alert-emitter.timer
systemctl list-timers | rg rpg-alert-emitter
```

- readiness timers run `curl --fail http://127.0.0.1:8000/ready` and `curl --fail http://127.0.0.1:8100/ready` every 30s.
- alert timer runs every 60s and executes `scripts/emit_runtime_alerts.py`.
- failures are visible with `systemctl status` and in journald logs.
