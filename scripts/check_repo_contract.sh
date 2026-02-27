#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

REQUIRED_TRACKED_PATHS=(
  "app/main.py"
  "requirements.txt"
  "app/config.py"
  "app/db/models.py"
  "app/modules/story_domain/schemas.py"
  "app/utils/time.py"
)

for rel_path in "${REQUIRED_TRACKED_PATHS[@]}"; do
  git ls-files --error-unmatch "$rel_path" >/dev/null
  if [[ ! -e "$rel_path" ]]; then
    echo "missing required file on disk: $rel_path" >&2
    exit 1
  fi
  if [[ "$rel_path" == "requirements.txt" && ! -s "$rel_path" ]]; then
    echo "requirements.txt must not be empty" >&2
    exit 1
  fi
done

python - <<'PY'
import importlib

for mod in ("app.main", "app.modules.story_domain.service"):
    importlib.import_module(mod)

print("repo runtime contract check passed")
PY
