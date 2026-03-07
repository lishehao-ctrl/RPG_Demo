#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

NAMESPACE=${NAMESPACE:-default}
BACKEND_DEPLOYMENT=${BACKEND_DEPLOYMENT:-rpg-backend}
WORKER_DEPLOYMENT=${WORKER_DEPLOYMENT:-rpg-llm-worker}
ROLLOUT_TIMEOUT=${ROLLOUT_TIMEOUT:-180s}
VERIFY_AFTER_ROLLBACK=${VERIFY_AFTER_ROLLBACK:-true}

kubectl rollout undo deployment/"${BACKEND_DEPLOYMENT}" -n "${NAMESPACE}"
kubectl rollout undo deployment/"${WORKER_DEPLOYMENT}" -n "${NAMESPACE}"

kubectl rollout status deployment/"${BACKEND_DEPLOYMENT}" -n "${NAMESPACE}" --timeout="${ROLLOUT_TIMEOUT}"
kubectl rollout status deployment/"${WORKER_DEPLOYMENT}" -n "${NAMESPACE}" --timeout="${ROLLOUT_TIMEOUT}"

if [[ "${VERIFY_AFTER_ROLLBACK}" == "true" ]]; then
  "${SCRIPT_DIR}/k8s_verify_rollout.sh"
fi

echo "rollback complete"
