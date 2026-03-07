#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-default}
BACKEND_DEPLOYMENT=${BACKEND_DEPLOYMENT:-rpg-backend}
WORKER_DEPLOYMENT=${WORKER_DEPLOYMENT:-rpg-llm-worker}
BACKEND_SELECTOR=${BACKEND_SELECTOR:-app=rpg-backend}
WORKER_SELECTOR=${WORKER_SELECTOR:-app=rpg-llm-worker}
ROLLOUT_TIMEOUT=${ROLLOUT_TIMEOUT:-180s}

kubectl rollout status deployment/"${BACKEND_DEPLOYMENT}" -n "${NAMESPACE}" --timeout="${ROLLOUT_TIMEOUT}"
kubectl rollout status deployment/"${WORKER_DEPLOYMENT}" -n "${NAMESPACE}" --timeout="${ROLLOUT_TIMEOUT}"

BACKEND_POD=$(kubectl get pods -n "${NAMESPACE}" -l "${BACKEND_SELECTOR}" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
WORKER_POD=$(kubectl get pods -n "${NAMESPACE}" -l "${WORKER_SELECTOR}" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

if [[ -z "${BACKEND_POD}" ]]; then
  echo "no running backend pod found" >&2
  exit 1
fi
if [[ -z "${WORKER_POD}" ]]; then
  echo "no running worker pod found" >&2
  exit 1
fi

kubectl exec -n "${NAMESPACE}" "${BACKEND_POD}" -- python -c "import urllib.request; [urllib.request.urlopen(u, timeout=5).read() for u in ('http://127.0.0.1:8000/health','http://127.0.0.1:8000/ready')]; print('backend probes ok')"
kubectl exec -n "${NAMESPACE}" "${WORKER_POD}" -- python -c "import urllib.request; [urllib.request.urlopen(u, timeout=5).read() for u in ('http://127.0.0.1:8100/health','http://127.0.0.1:8100/ready')]; print('worker probes ok')"

echo "rollout verification passed"
