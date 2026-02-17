#!/usr/bin/env bash
set -euo pipefail

export ENV=dev
: "${DATABASE_URL:=sqlite:///./dev.db}"
export DATABASE_URL

python -m alembic upgrade head
uvicorn app.main:app --reload
