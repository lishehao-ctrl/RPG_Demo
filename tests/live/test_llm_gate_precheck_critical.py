from __future__ import annotations

import os
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_openai_critical


def _load_gate_eval_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "scripts" / "eval"
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(scripts_dir))
    script_path = scripts_dir / "evaluate_llm_gate.py"
    spec = importlib.util.spec_from_file_location("evaluate_llm_gate", script_path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("failed to load evaluate_llm_gate module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_openai_env() -> bool:
    base_url = (os.getenv("APP_LLM_OPENAI_BASE_URL") or "").strip()
    api_key = (os.getenv("APP_LLM_OPENAI_API_KEY") or "").strip()
    model = (os.getenv("APP_LLM_OPENAI_ROUTE_MODEL") or "").strip() or (
        os.getenv("APP_LLM_OPENAI_NARRATION_MODEL") or ""
    ).strip() or (os.getenv("APP_LLM_OPENAI_MODEL") or "").strip()
    return bool(base_url and api_key and model)


def test_live_openai_gate_precheck_status_ok() -> None:
    if not _has_openai_env():
        pytest.skip("missing OpenAI runtime env for live critical test")

    gate_eval = _load_gate_eval_module()
    precheck = gate_eval._run_openai_precheck()
    assert precheck["status"] == "ok", precheck
    assert precheck.get("route_model")
    assert isinstance(precheck.get("probe_confidence"), float)
