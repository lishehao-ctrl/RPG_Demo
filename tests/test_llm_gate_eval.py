from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx


def _load_gate_eval_module():
    repo_root = Path(__file__).resolve().parents[1]
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


gate_eval = _load_gate_eval_module()


def test_compute_gate_fails_when_route_success_too_low() -> None:
    metrics = {
        "completion_rate": 1.0,
        "avg_steps": 14.0,
        "meaningful_accept_rate": 1.0,
        "llm_route_success_rate": 0.0,
        "step_error_rate": 0.0,
    }
    gate = gate_eval._compute_gate(metrics)
    assert gate["passed"] is False
    assert gate["evaluation_status"] == "failed"
    assert gate["llm_route_success_rate"] == 0.0


def test_compute_gate_passes_when_medium_thresholds_met() -> None:
    metrics = {
        "completion_rate": 1.0,
        "avg_steps": 14.0,
        "meaningful_accept_rate": 0.95,
        "llm_route_success_rate": 0.85,
        "step_error_rate": 0.0,
    }
    gate = gate_eval._compute_gate(metrics)
    assert gate["passed"] is True
    assert gate["evaluation_status"] == "passed"
    assert gate["thresholds"]["llm_route_success_rate_min"] == 0.80
    assert gate["thresholds"]["step_error_rate_required"] == 0.0
    assert gate["thresholds"]["meaningful_accept_rate_min"] == 0.90


def test_compute_gate_fails_when_openai_has_runtime_step_errors() -> None:
    metrics = {
        "completion_rate": 1.0,
        "avg_steps": 14.0,
        "meaningful_accept_rate": 0.95,
        "llm_route_success_rate": 0.95,
        "step_error_rate": 0.1,
    }
    gate = gate_eval._compute_gate(metrics)
    assert gate["passed"] is False
    assert gate["evaluation_status"] == "failed"
    assert gate["step_error_rate"] == 0.1


def test_precheck_dns_failure_returns_structured_error(monkeypatch) -> None:
    monkeypatch.setattr(
        gate_eval,
        "get_settings",
        lambda: SimpleNamespace(
            llm_openai_base_url="https://bad-host.example/compatible-mode",
            llm_openai_route_model="route-model",
            llm_openai_model=None,
        ),
    )
    monkeypatch.setattr(
        gate_eval.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.gaierror(8, "nodename nor servname provided")),
    )

    precheck = gate_eval._run_openai_precheck()
    assert precheck["status"] == "failed"
    assert precheck["error_type"] == "dns_unreachable"
    assert precheck["host"] == "bad-host.example"
    assert precheck["route_model"] == "route-model"


def test_precheck_calls_route_only_not_narration(monkeypatch) -> None:
    monkeypatch.setattr(
        gate_eval,
        "get_settings",
        lambda: SimpleNamespace(
            llm_openai_base_url="https://ok-host.example/compatible-mode",
            llm_openai_route_model="route-model",
            llm_openai_model=None,
        ),
    )
    monkeypatch.setattr(gate_eval.socket, "getaddrinfo", lambda *_args, **_kwargs: [object()])

    class _Provider:
        route_model = "route-model"

        def __init__(self) -> None:
            self.route_called = 0
            self.narration_called = 0

        async def route_intent(self, scene_context, text):  # noqa: ANN001, ANN201
            self.route_called += 1
            return SimpleNamespace(move_id="global.help_me_progress", confidence=0.9)

        async def render_narration(self, slots, style_guard):  # noqa: ANN001, ANN201
            self.narration_called += 1
            raise AssertionError("render_narration should not be called by precheck")

    provider = _Provider()
    monkeypatch.setattr(gate_eval, "get_llm_provider", lambda *_args, **_kwargs: provider)
    precheck = gate_eval._run_openai_precheck()
    assert precheck["status"] == "ok"
    assert precheck["route_model"] == "route-model"
    assert provider.route_called == 1
    assert provider.narration_called == 0


def test_precheck_requires_route_model_or_global_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        gate_eval,
        "get_settings",
        lambda: SimpleNamespace(
            llm_openai_base_url="https://bad-host.example/compatible-mode",
            llm_openai_route_model="",
            llm_openai_narration_model="narration-only-model",
            llm_openai_model=None,
        ),
    )

    precheck = gate_eval._run_openai_precheck()
    assert precheck["status"] == "failed"
    assert precheck["error_type"] == "missing_model"
    assert precheck["route_model"] == ""


def test_classify_precheck_error_marks_unsupported_chat_completions_api() -> None:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(404, request=request, text='{"error":"not found: /v1/chat/completions"}')
    exc = httpx.HTTPStatusError("not found", request=request, response=response)
    assert gate_eval._classify_precheck_error(exc) == "unsupported_chat_completions_api"


def test_evaluate_llm_gate_short_circuits_on_precheck_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        gate_eval,
        "_run_openai_precheck",
        lambda: {"status": "failed", "error_type": "dns_unreachable", "error": "boom"},
    )
    monkeypatch.setattr(
        gate_eval,
        "simulate_pack_playthrough",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not run simulations")),
    )

    report = gate_eval.evaluate_llm_gate(
        pack_json={"beats": [], "moves": [], "scenes": []},
        runs=5,
        strategy="mixed",
        max_steps=20,
    )
    assert report["precheck"]["status"] == "failed"
    assert report["gate"]["passed"] is False
    assert report["gate"]["evaluation_status"] == "failed"
    assert report["runs_detail"] == []


def test_evaluate_llm_gate_allows_inconclusive_when_flag_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        gate_eval,
        "_run_openai_precheck",
        lambda: {"status": "failed", "error_type": "dns_unreachable", "error": "boom"},
    )
    report = gate_eval.evaluate_llm_gate(
        pack_json={"beats": [], "moves": [], "scenes": []},
        runs=3,
        strategy="mixed",
        max_steps=20,
        allow_precheck_fail=True,
    )
    assert report["gate"]["passed"] is False
    assert report["gate"]["evaluation_status"] == "inconclusive"
    assert report["gate"]["inconclusive"] is True
    assert report["runs_detail"] == []


def test_evaluate_llm_gate_status_passed_when_metrics_meet_threshold(monkeypatch) -> None:
    monkeypatch.setattr(gate_eval, "_run_openai_precheck", lambda: {"status": "ok"})

    monkeypatch.setattr(
        gate_eval,
        "simulate_pack_playthrough",
        lambda *_args, **_kwargs: {
            "ended": True,
            "steps": 14,
            "meaningful_steps": 13,
            "text_input_steps": 10,
            "llm_route_steps": 9,
            "runtime_error_steps": 0,
        },
    )

    report = gate_eval.evaluate_llm_gate(
        pack_json={"beats": [], "moves": [], "scenes": []},
        runs=2,
        strategy="mixed",
        max_steps=20,
    )
    assert report["gate"]["evaluation_status"] == "passed"
    assert report["gate"]["passed"] is True


def test_evaluate_llm_gate_status_failed_when_metrics_below_threshold(monkeypatch) -> None:
    monkeypatch.setattr(gate_eval, "_run_openai_precheck", lambda: {"status": "ok"})

    monkeypatch.setattr(
        gate_eval,
        "simulate_pack_playthrough",
        lambda *_args, **_kwargs: {
            "ended": False,
            "steps": 14,
            "meaningful_steps": 5,
            "text_input_steps": 10,
            "llm_route_steps": 8,
            "runtime_error_steps": 1,
            "runtime_error": True,
            "runtime_error_code": "llm_narration_failed",
            "runtime_error_stage": "narration",
            "runtime_error_message": "render_narration failed",
        },
    )
    report = gate_eval.evaluate_llm_gate(
        pack_json={"beats": [], "moves": [], "scenes": []},
        runs=2,
        strategy="mixed",
        max_steps=20,
    )
    assert report["gate"]["evaluation_status"] == "failed"
    assert report["gate"]["passed"] is False
