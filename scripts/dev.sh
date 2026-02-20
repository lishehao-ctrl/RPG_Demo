#!/usr/bin/env bash
set -euo pipefail

export ENV=dev
: "${DATABASE_URL:=sqlite:///./dev.db}"
export DATABASE_URL

python -m alembic upgrade head
if [[ "${SKIP_SEED:-0}" != "1" ]]; then
  python scripts/seed.py
fi
uvicorn app.main:app --reload
