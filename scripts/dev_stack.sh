#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_DIR="${REPO_ROOT}/output/dev_stack"
STATUS_FILE="${RUN_DIR}/status.json"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
FRONTEND_DIR="${REPO_ROOT}/frontend"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
WORKER_HOST="127.0.0.1"
WORKER_PORT="8100"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="8173"
TAIL_LINES="${DEV_STACK_TAIL_LINES:-80}"

log() {
  printf '[dev_stack] %s\n' "$*"
}

warn() {
  printf '[dev_stack] WARN: %s\n' "$*" >&2
}

fail() {
  printf '[dev_stack] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<USAGE
usage: ./scripts/dev_stack.sh <command> [args]

Commands:
  up                 Run migrate head, then start worker/backend/frontend
  down               Stop frontend/backend/worker and clean stale pid files
  restart            Restart the full local dev stack
  status             Show service state, pid, ports, logs, and recent health
  resetdb            Stop services, recreate local SQLite app.db, migrate, then start stack
  logs [service]     Show recent logs for all services or one of: backend worker frontend
  ready              Check backend /ready, worker /ready, and frontend /
USAGE
}

ensure_run_dir() {
  mkdir -p "${RUN_DIR}"
}

require_cmd() {
  local name="$1"
  command -v "${name}" >/dev/null 2>&1 || fail "missing required command '${name}'"
}

require_python_env() {
  [[ -x "${PYTHON_BIN}" ]] || fail "missing ${PYTHON_BIN}; create the virtualenv first: python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'"
}

require_frontend_deps() {
  [[ -f "${FRONTEND_DIR}/package.json" ]] || fail "missing frontend/package.json"
  [[ -d "${FRONTEND_DIR}/node_modules" ]] || fail "missing frontend/node_modules; run: cd frontend && npm install"
  require_cmd npm
}

service_port() {
  case "$1" in
    backend) printf '%s' "${BACKEND_PORT}" ;;
    worker) printf '%s' "${WORKER_PORT}" ;;
    frontend) printf '%s' "${FRONTEND_PORT}" ;;
    *) fail "unknown service '$1'" ;;
  esac
}

service_host() {
  case "$1" in
    backend) printf '%s' "${BACKEND_HOST}" ;;
    worker) printf '%s' "${WORKER_HOST}" ;;
    frontend) printf '%s' "${FRONTEND_HOST}" ;;
    *) fail "unknown service '$1'" ;;
  esac
}

service_pid_file() {
  printf '%s/%s.pid' "${RUN_DIR}" "$1"
}

service_log_file() {
  printf '%s/%s.log' "${RUN_DIR}" "$1"
}

service_health_url() {
  case "$1" in
    backend) printf 'http://%s:%s/ready' "${BACKEND_HOST}" "${BACKEND_PORT}" ;;
    worker) printf 'http://%s:%s/ready' "${WORKER_HOST}" "${WORKER_PORT}" ;;
    frontend) printf 'http://%s:%s/' "${FRONTEND_HOST}" "${FRONTEND_PORT}" ;;
    *) fail "unknown service '$1'" ;;
  esac
}

service_health_name() {
  case "$1" in
    backend) printf 'backend /ready' ;;
    worker) printf 'worker /ready' ;;
    frontend) printf 'frontend /' ;;
    *) fail "unknown service '$1'" ;;
  esac
}

pid_alive() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

service_pid() {
  local name="$1"
  local pid_file
  pid_file="$(service_pid_file "${name}")"
  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(tr -d '[:space:]' < "${pid_file}")"
    if pid_alive "${pid}"; then
      printf '%s' "${pid}"
      return 0
    fi
  fi
  return 1
}

list_pids_for_port() {
  local port="$1"
  lsof -t -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

service_state() {
  local name="$1"
  if service_pid "${name}" >/dev/null 2>&1; then
    printf 'running'
    return 0
  fi

  local port
  port="$(service_port "${name}")"
  if [[ -n "$(list_pids_for_port "${port}")" ]]; then
    printf 'port_busy'
  else
    printf 'stopped'
  fi
}

service_any_pid() {
  local name="$1"
  if service_pid "${name}" >/dev/null 2>&1; then
    service_pid "${name}"
    return 0
  fi
  local port
  port="$(service_port "${name}")"
  local pids
  pids="$(list_pids_for_port "${port}" | paste -sd, -)"
  [[ -n "${pids}" ]] && printf '%s' "${pids}"
}

http_code() {
  local url="$1"
  curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${url}" 2>/dev/null || printf '000'
}

wait_for_http_ok() {
  local name="$1"
  local url="$2"
  local attempts="$3"
  local sleep_seconds="$4"
  local code='000'
  local try=1
  while (( try <= attempts )); do
    code="$(http_code "${url}")"
    if [[ "${code}" == "200" ]]; then
      return 0
    fi
    sleep "${sleep_seconds}"
    try=$(( try + 1 ))
  done
  warn "${name} did not become ready; last http=${code} url=${url}"
  return 1
}

write_status_file() {
  ensure_run_dir

  local backend_state worker_state frontend_state
  local backend_pid_json worker_pid_json frontend_pid_json
  local backend_code worker_code frontend_code
  local backend_ready worker_ready frontend_ready
  local now

  backend_state="$(service_state backend)"
  worker_state="$(service_state worker)"
  frontend_state="$(service_state frontend)"

  backend_pid_json="$(service_any_pid backend || true)"
  worker_pid_json="$(service_any_pid worker || true)"
  frontend_pid_json="$(service_any_pid frontend || true)"

  backend_code="$(http_code "$(service_health_url backend)")"
  worker_code="$(http_code "$(service_health_url worker)")"
  frontend_code="$(http_code "$(service_health_url frontend)")"

  [[ "${backend_code}" == "200" ]] && backend_ready=true || backend_ready=false
  [[ "${worker_code}" == "200" ]] && worker_ready=true || worker_ready=false
  [[ "${frontend_code}" == "200" ]] && frontend_ready=true || frontend_ready=false

  [[ -n "${backend_pid_json}" ]] || backend_pid_json='null'
  [[ -n "${worker_pid_json}" ]] || worker_pid_json='null'
  [[ -n "${frontend_pid_json}" ]] || frontend_pid_json='null'

  now="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

  cat > "${STATUS_FILE}" <<JSON
{
  "generated_at": "${now}",
  "services": {
    "backend": {
      "state": "${backend_state}",
      "pid": ${backend_pid_json},
      "port": ${BACKEND_PORT},
      "log": "$(service_log_file backend)",
      "http_code": "${backend_code}",
      "ready": ${backend_ready}
    },
    "worker": {
      "state": "${worker_state}",
      "pid": ${worker_pid_json},
      "port": ${WORKER_PORT},
      "log": "$(service_log_file worker)",
      "http_code": "${worker_code}",
      "ready": ${worker_ready}
    },
    "frontend": {
      "state": "${frontend_state}",
      "pid": ${frontend_pid_json},
      "port": ${FRONTEND_PORT},
      "log": "$(service_log_file frontend)",
      "http_code": "${frontend_code}",
      "ready": ${frontend_ready}
    }
  }
}
JSON
}

show_status() {
  write_status_file

  for name in worker backend frontend; do
    local state pid port log_file code ready_flag
    state="$(service_state "${name}")"
    pid="$(service_any_pid "${name}" || true)"
    [[ -n "${pid}" ]] || pid='-'
    port="$(service_port "${name}")"
    log_file="$(service_log_file "${name}")"
    code="$(http_code "$(service_health_url "${name}")")"
    if [[ "${code}" == '200' ]]; then
      ready_flag='ok'
    else
      ready_flag='down'
    fi
    printf '%-8s state=%-9s pid=%-12s port=%-5s health=%-4s log=%s\n' "${name}" "${state}" "${pid}" "${port}" "${ready_flag}" "${log_file}"
  done
  printf 'status_file=%s\n' "${STATUS_FILE}"
}

show_ready() {
  write_status_file
  local failed=0
  for name in worker backend frontend; do
    local url code
    url="$(service_health_url "${name}")"
    code="$(http_code "${url}")"
    printf '%-15s http=%s url=%s\n' "$(service_health_name "${name}")" "${code}" "${url}"
    if [[ "${code}" != '200' ]]; then
      failed=1
    fi
  done
  return "${failed}"
}

run_migrate_head() {
  require_python_env
  log 'running migrations to head'
  (
    cd "${REPO_ROOT}"
    PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" scripts/db_migrate.py upgrade head
  )
}

start_service() {
  local name="$1"
  local state workdir pid_file log_file
  local -a cmd

  state="$(service_state "${name}")"
  if [[ "${state}" == 'running' ]]; then
    log "${name} already running"
    return 0
  fi
  if [[ "${state}" == 'port_busy' ]]; then
    fail "${name} port $(service_port "${name}") is already in use without a valid pid file; run ./scripts/dev_stack.sh down or inspect the port"
  fi

  case "${name}" in
    worker)
      require_python_env
      workdir="${REPO_ROOT}"
      cmd=(env "PYTHONPATH=${REPO_ROOT}" "${PYTHON_BIN}" -m uvicorn rpg_backend.llm_worker.main:app --reload --host "${WORKER_HOST}" --port "${WORKER_PORT}")
      ;;
    backend)
      require_python_env
      workdir="${REPO_ROOT}"
      cmd=(env "PYTHONPATH=${REPO_ROOT}" "${PYTHON_BIN}" -m uvicorn rpg_backend.main:app --reload --host "${BACKEND_HOST}" --port "${BACKEND_PORT}")
      ;;
    frontend)
      require_frontend_deps
      workdir="${FRONTEND_DIR}"
      cmd=(npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}")
      ;;
    *)
      fail "unknown service '${name}'"
      ;;
  esac

  ensure_run_dir
  pid_file="$(service_pid_file "${name}")"
  log_file="$(service_log_file "${name}")"
  : > "${log_file}"

  log "starting ${name}"
  (
    cd "${workdir}"
    if command -v setsid >/dev/null 2>&1; then
      setsid nohup "${cmd[@]}" < /dev/null >> "${log_file}" 2>&1 &
    else
      nohup "${cmd[@]}" < /dev/null >> "${log_file}" 2>&1 &
    fi
    echo $! > "${pid_file}"
  )

  sleep 1
  local pid
  pid="$(tr -d '[:space:]' < "${pid_file}")"
  if ! pid_alive "${pid}"; then
    tail -n 60 "${log_file}" || true
    fail "${name} failed to stay running; see ${log_file}"
  fi
}

wait_for_stack_ready() {
  wait_for_http_ok 'worker /ready' "$(service_health_url worker)" 90 1 || return 1
  wait_for_http_ok 'backend /ready' "$(service_health_url backend)" 90 1 || return 1
  wait_for_http_ok 'frontend /' "$(service_health_url frontend)" 90 1 || return 1
  return 0
}

stop_service() {
  local name="$1"
  local pid_file pid port port_pids
  pid_file="$(service_pid_file "${name}")"
  pid="$(service_pid "${name}" || true)"
  if [[ -n "${pid}" ]]; then
    log "stopping ${name} pid=${pid}"
    kill "${pid}" 2>/dev/null || true
    local try=1
    while pid_alive "${pid}" && (( try <= 15 )); do
      sleep 1
      try=$(( try + 1 ))
    done
    if pid_alive "${pid}"; then
      warn "${name} did not stop after SIGTERM; sending SIGKILL"
      kill -9 "${pid}" 2>/dev/null || true
    fi
  fi
  rm -f "${pid_file}"

  port="$(service_port "${name}")"
  port_pids="$(list_pids_for_port "${port}" | paste -sd' ' -)"
  if [[ -n "${port_pids}" ]]; then
    warn "cleaning stale listeners for ${name} on port ${port}: ${port_pids}"
    kill ${port_pids} 2>/dev/null || true
    sleep 1
    port_pids="$(list_pids_for_port "${port}" | paste -sd' ' -)"
    if [[ -n "${port_pids}" ]]; then
      warn "forcing stale listeners for ${name} on port ${port}: ${port_pids}"
      kill -9 ${port_pids} 2>/dev/null || true
    fi
  fi
}

stack_up() {
  require_cmd curl
  require_cmd lsof
  require_python_env
  require_frontend_deps
  run_migrate_head
  start_service worker
  start_service backend
  start_service frontend
  if ! wait_for_stack_ready; then
    warn 'stack failed readiness checks; shutting down partial services'
    stack_down
    fail 'stack failed to become ready'
  fi
  write_status_file
  show_status
}

stack_down() {
  require_cmd lsof
  ensure_run_dir
  stop_service frontend
  stop_service backend
  stop_service worker
  write_status_file
  show_status
}

reset_db() {
  require_python_env
  require_cmd rm
  local db_path
  db_path="$(${PYTHON_BIN} - <<'PY'
from pathlib import Path
from rpg_backend.config.settings import get_settings
repo_root = Path.cwd().resolve()
expected = (repo_root / 'app.db').resolve()
database_url = (get_settings().database_url or '').strip()
if not database_url.startswith('sqlite:///'):
    raise SystemExit('APP_DATABASE_URL is not a local sqlite url; resetdb only supports local app.db')
raw_path = database_url[len('sqlite:///'):]
path = Path(raw_path)
if not path.is_absolute():
    path = (repo_root / path).resolve()
else:
    path = path.resolve()
if path != expected:
    raise SystemExit(f'resetdb only supports {expected}; current APP_DATABASE_URL resolves to {path}')
print(path)
PY
)"
  stack_down
  log "removing sqlite database ${db_path}"
  rm -f "${db_path}"
  stack_up
}

show_logs() {
  ensure_run_dir
  if [[ $# -eq 0 ]]; then
    for name in worker backend frontend; do
      printf '===== %s (%s) =====\n' "${name}" "$(service_log_file "${name}")"
      if [[ -f "$(service_log_file "${name}")" ]]; then
        tail -n "${TAIL_LINES}" "$(service_log_file "${name}")"
      else
        printf '(no log yet)\n'
      fi
      printf '\n'
    done
    return 0
  fi

  case "$1" in
    worker|backend|frontend)
      if [[ -f "$(service_log_file "$1")" ]]; then
        tail -n "${TAIL_LINES}" "$(service_log_file "$1")"
      else
        printf '(no log yet for %s)\n' "$1"
      fi
      ;;
    *)
      fail "unknown service '$1'; expected one of: backend worker frontend"
      ;;
  esac
}

main() {
  local command="${1:-}"
  case "${command}" in
    up)
      stack_up
      ;;
    down)
      stack_down
      ;;
    restart)
      stack_down
      stack_up
      ;;
    status)
      show_status
      ;;
    resetdb)
      reset_db
      ;;
    logs)
      shift || true
      show_logs "$@"
      ;;
    ready)
      show_ready
      ;;
    ''|-h|--help|help)
      usage
      ;;
    *)
      usage >&2
      fail "unknown command '${command}'"
      ;;
  esac
}

main "$@"
