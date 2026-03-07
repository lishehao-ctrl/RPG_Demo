#!/usr/bin/env bash
set -euo pipefail

REVISION=${1:-head}
RUN_IN_POD=${RUN_IN_POD:-false}

if [[ "${RUN_IN_POD}" == "true" ]]; then
  NAMESPACE=${NAMESPACE:-default}
  BACKEND_SELECTOR=${BACKEND_SELECTOR:-app=rpg-backend}
  POD=$(kubectl get pods -n "${NAMESPACE}" -l "${BACKEND_SELECTOR}" --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')
  if [[ -z "${POD}" ]]; then
    echo "no running backend pod found for migration" >&2
    exit 1
  fi
  kubectl exec -n "${NAMESPACE}" "${POD}" -- python -m scripts.db_migrate upgrade "${REVISION}"
else
  PYTHONPATH=. python scripts/db_migrate.py upgrade "${REVISION}"
fi
