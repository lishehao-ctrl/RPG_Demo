#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    TestClient = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_CALL_TARGET = 200
DEFAULT_TOKEN_KILL_SWITCH = 1_000_000
DEFAULT_TOKEN_WARNING = 500_000
DEFAULT_SCENARIO_QUOTAS = {
    "local_fake_baseline": 40,
    "remote_clean": 60,
    "remote_jitter_mild": 50,
    "remote_jitter_severe": 50,
}
DEFAULT_INPUT_WEIGHTS = {
    "choice_direct": 0.35,
    "free_input_clear": 0.35,
    "free_input_ambiguous": 0.20,
    "free_input_noise": 0.10,
}


@dataclass
class TokenProjection:
    calls: int
    avg_total_tokens: int
    p95_total_tokens: int
    p99_total_tokens: int
    max_envelope_tokens: int


@dataclass
class BudgetState:
    llm_calls_total: int = 0
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    tokens_total: int = 0
    stop_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class InputBucketMetrics:
    attempts: int = 0
    success_2xx: int = 0
    fallback_count: int = 0
    status_503_count: int = 0
    llm_unavailable_count: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        fallback_rate = (self.fallback_count / self.success_2xx) if self.success_2xx > 0 else 0.0
        status_503_rate = (self.status_503_count / self.attempts) if self.attempts > 0 else 0.0
        latency_p95 = _percentile(self.latencies_ms, 95)
        return {
            "attempts": self.attempts,
            "success_2xx": self.success_2xx,
            "fallback_count": self.fallback_count,
            "fallback_rate": round(fallback_rate, 4),
            "status_503_count": self.status_503_count,
            "status_503_rate": round(status_503_rate, 4),
            "llm_unavailable_count": self.llm_unavailable_count,
            "latency_p95_ms": round(latency_p95, 2),
        }


@dataclass
class ScenarioMetrics:
    name: str
    llm_calls_target: int
    llm_calls_delta: int = 0
    tokens_in_delta: int = 0
    tokens_out_delta: int = 0
    tokens_total_delta: int = 0
    actions_attempted: int = 0
    success_2xx: int = 0
    status_code_counts: dict[str, int] = field(default_factory=dict)
    detail_code_counts: dict[str, int] = field(default_factory=dict)
    latencies_ms: list[float] = field(default_factory=list)
    fallback_count: int = 0
    input_buckets: dict[str, InputBucketMetrics] = field(default_factory=lambda: {
        "choice_direct": InputBucketMetrics(),
        "free_input_clear": InputBucketMetrics(),
        "free_input_ambiguous": InputBucketMetrics(),
        "free_input_noise": InputBucketMetrics(),
    })
    uncertain_total: int = 0
    uncertain_recovered: int = 0
    uncertain_duplicate_violation: int = 0
    uncertain_retry_status_counts: dict[str, int] = field(default_factory=dict)
    llm_unavailable_state_advance_violations: int = 0
    idempotency_reused_checks_expected: int = 0
    idempotency_reused_checks_passed: int = 0
    stop_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        step_success_rate = (self.success_2xx / self.actions_attempted) if self.actions_attempted > 0 else 0.0
        fallback_rate = (self.fallback_count / self.success_2xx) if self.success_2xx > 0 else 0.0
        uncertain_recovered_rate = (
            self.uncertain_recovered / self.uncertain_total if self.uncertain_total > 0 else 0.0
        )
        return {
            "name": self.name,
            "llm_calls_target": self.llm_calls_target,
            "llm_calls_delta": self.llm_calls_delta,
            "tokens_in_delta": self.tokens_in_delta,
            "tokens_out_delta": self.tokens_out_delta,
            "tokens_total_delta": self.tokens_total_delta,
            "actions_attempted": self.actions_attempted,
            "success_2xx": self.success_2xx,
            "step_success_rate": round(step_success_rate, 4),
            "fallback_count": self.fallback_count,
            "fallback_rate": round(fallback_rate, 4),
            "status_code_counts": dict(self.status_code_counts),
            "detail_code_counts": dict(self.detail_code_counts),
            "latency_p95_ms": round(_percentile(self.latencies_ms, 95), 2),
            "input_buckets": {k: v.to_dict() for k, v in self.input_buckets.items()},
            "uncertain_total": self.uncertain_total,
            "uncertain_recovered": self.uncertain_recovered,
            "uncertain_recovered_rate": round(uncertain_recovered_rate, 4),
            "uncertain_duplicate_violation": self.uncertain_duplicate_violation,
            "uncertain_retry_status_counts": dict(self.uncertain_retry_status_counts),
            "llm_unavailable_state_advance_violations": self.llm_unavailable_state_advance_violations,
            "idempotency_reused_checks_expected": self.idempotency_reused_checks_expected,
            "idempotency_reused_checks_passed": self.idempotency_reused_checks_passed,
            "stop_reason": self.stop_reason,
            "error": self.error,
        }


@dataclass
class ScenarioSpec:
    name: str
    call_quota: int
    source: str  # local or remote
    jitter_profile: str  # clean / jitter_mild / jitter_severe


class SQLiteUsageMonitor:
    def __init__(self, sqlite_path: Path):
        self.sqlite_path = sqlite_path
        self._seen_ids: set[str] = set()

    def refresh(self, session_ids: set[str]) -> tuple[int, int, int]:
        if not session_ids:
            return 0, 0, 0
        placeholders = ",".join(["?"] * len(session_ids))
        sql = (
            "select id, prompt_tokens, completion_tokens "
            "from llm_usage_logs "
            "where operation = 'generate' and status = 'success' and session_id in ("
            + placeholders
            + ")"
        )
        conn = sqlite3.connect(str(self.sqlite_path))
        try:
            cur = conn.cursor()
            cur.execute(sql, tuple(sorted(session_ids)))
            rows = cur.fetchall()
        finally:
            conn.close()

        new_calls = 0
        tokens_in = 0
        tokens_out = 0
        for row_id, prompt_tokens, completion_tokens in rows:
            row_key = str(row_id)
            if row_key in self._seen_ids:
                continue
            self._seen_ids.add(row_key)
            new_calls += 1
            tokens_in += int(prompt_tokens or 0)
            tokens_out += int(completion_tokens or 0)
        return new_calls, tokens_in, tokens_out


class ToxiproxyManager:
    def __init__(self, *, api_url: str, proxy_name: str, listen: str, upstream: str):
        self.api_url = api_url.rstrip("/")
        self.proxy_name = proxy_name
        self.listen = listen
        self.upstream = upstream
        self._client = httpx.Client(timeout=10.0)

    def close(self) -> None:
        self._client.close()

    def ensure_proxy(self) -> None:
        resp = self._client.get(f"{self.api_url}/proxies")
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, list):
            if any(str(item.get("name")) == self.proxy_name for item in payload if isinstance(item, dict)):
                return
        elif isinstance(payload, dict):
            if self.proxy_name in payload:
                return
        payload = {
            "name": self.proxy_name,
            "listen": self.listen,
            "upstream": self.upstream,
        }
        create = self._client.post(f"{self.api_url}/proxies", json=payload)
        create.raise_for_status()

    def clear_toxics(self) -> None:
        resp = self._client.get(f"{self.api_url}/proxies/{self.proxy_name}")
        resp.raise_for_status()
        payload = resp.json() if isinstance(resp.json(), dict) else {}
        toxics = payload.get("toxics") or []
        for toxic in toxics:
            toxic_name = str((toxic or {}).get("name") or "").strip()
            if not toxic_name:
                continue
            delete_resp = self._client.delete(f"{self.api_url}/proxies/{self.proxy_name}/toxics/{toxic_name}")
            if delete_resp.status_code not in {200, 204, 404}:
                delete_resp.raise_for_status()

    def apply_profile(self, profile: str) -> None:
        self.ensure_proxy()
        self.clear_toxics()
        if profile == "clean":
            return
        toxics = []
        if profile == "jitter_mild":
            toxics = [
                {
                    "name": "latency_mild",
                    "type": "latency",
                    "stream": "downstream",
                    "attributes": {"latency": 120, "jitter": 60},
                },
                {
                    "name": "bandwidth_mild",
                    "type": "bandwidth",
                    "stream": "downstream",
                    "attributes": {"rate": 512},
                },
            ]
        elif profile == "jitter_severe":
            toxics = [
                {
                    "name": "latency_severe",
                    "type": "latency",
                    "stream": "downstream",
                    "attributes": {"latency": 450, "jitter": 220},
                },
                {
                    "name": "timeout_severe",
                    "type": "timeout",
                    "stream": "upstream",
                    "attributes": {"timeout": 2500},
                },
                {
                    "name": "bandwidth_severe",
                    "type": "bandwidth",
                    "stream": "downstream",
                    "attributes": {"rate": 128},
                },
            ]
        else:
            raise ValueError(f"unsupported toxiproxy profile: {profile}")

        for toxic in toxics:
            add_resp = self._client.post(
                f"{self.api_url}/proxies/{self.proxy_name}/toxics",
                json=toxic,
            )
            add_resp.raise_for_status()


class RemoteClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def create_session(self, story_id: str, version: int | None) -> str:
        payload: dict[str, Any] = {"story_id": story_id}
        if version is not None:
            payload["version"] = version
        resp = self._client.post(f"{self.base_url}/sessions", json=payload)
        resp.raise_for_status()
        return str(resp.json()["id"])

    def get_session(self, session_id: str) -> dict[str, Any]:
        resp = self._client.get(f"{self.base_url}/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()

    def step(self, session_id: str, payload: dict[str, Any], idempotency_key: str) -> tuple[int, Any, float]:
        started = time.perf_counter()
        try:
            resp = self._client.post(
                f"{self.base_url}/sessions/{session_id}/step",
                headers={"X-Idempotency-Key": idempotency_key},
                json=payload,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            data = _safe_json(resp)
            return int(resp.status_code), data, latency_ms
        except httpx.RequestError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            return 0, {"detail": {"code": "NETWORK_ERROR", "message": str(exc)}}, latency_ms


class LocalFakeClient:
    def __init__(self):
        if TestClient is None:
            raise RuntimeError("fastapi TestClient is unavailable")
        from app.config import settings
        from app.main import app

        self._settings = settings
        self._original_primary = settings.llm_provider_primary
        self._original_fallbacks = list(settings.llm_provider_fallbacks)
        settings.llm_provider_primary = "fake"
        settings.llm_provider_fallbacks = []
        self._client = TestClient(app)

    def close(self) -> None:
        self._client.close()
        self._settings.llm_provider_primary = self._original_primary
        self._settings.llm_provider_fallbacks = self._original_fallbacks

    def create_session(self, story_id: str, version: int | None) -> str:
        payload: dict[str, Any] = {"story_id": story_id}
        if version is not None:
            payload["version"] = version
        resp = self._client.post("/sessions", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"create session failed: {resp.status_code} {resp.text}")
        return str(resp.json()["id"])

    def get_session(self, session_id: str) -> dict[str, Any]:
        resp = self._client.get(f"/sessions/{session_id}")
        if resp.status_code >= 400:
            raise RuntimeError(f"get session failed: {resp.status_code} {resp.text}")
        return resp.json()

    def step(self, session_id: str, payload: dict[str, Any], idempotency_key: str) -> tuple[int, Any, float]:
        started = time.perf_counter()
        resp = self._client.post(
            f"/sessions/{session_id}/step",
            headers={"X-Idempotency-Key": idempotency_key},
            json=payload,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        return int(resp.status_code), _safe_json(resp), latency_ms


def project_token_budget_for_calls(
    calls: int,
    *,
    avg_per_call: float = 1035.49,
    p95_per_call: int = 1496,
    p99_per_call: int = 1828,
    max_per_call: int = 2321,
) -> TokenProjection:
    safe_calls = max(0, int(calls))
    return TokenProjection(
        calls=safe_calls,
        avg_total_tokens=int(round(avg_per_call * safe_calls)),
        p95_total_tokens=int(p95_per_call * safe_calls),
        p99_total_tokens=int(p99_per_call * safe_calls),
        max_envelope_tokens=int(max_per_call * safe_calls),
    )


def build_default_scenarios() -> list[ScenarioSpec]:
    return [
        ScenarioSpec("local_fake_baseline", DEFAULT_SCENARIO_QUOTAS["local_fake_baseline"], "local", "clean"),
        ScenarioSpec("remote_clean", DEFAULT_SCENARIO_QUOTAS["remote_clean"], "remote", "clean"),
        ScenarioSpec("remote_jitter_mild", DEFAULT_SCENARIO_QUOTAS["remote_jitter_mild"], "remote", "jitter_mild"),
        ScenarioSpec("remote_jitter_severe", DEFAULT_SCENARIO_QUOTAS["remote_jitter_severe"], "remote", "jitter_severe"),
    ]


def evaluate_release_v1(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    global_section = report.get("global", {}) if isinstance(report, dict) else {}
    llm_calls_total = int(global_section.get("llm_calls_total", 0) or 0)
    tokens_total = int(global_section.get("tokens_total", 0) or 0)
    if llm_calls_total != DEFAULT_CALL_TARGET and str(global_section.get("stop_reason")) != "BUDGET_KILL_SWITCH":
        errors.append(f"global llm_calls_total={llm_calls_total} expected {DEFAULT_CALL_TARGET}")
    if tokens_total >= DEFAULT_TOKEN_KILL_SWITCH:
        errors.append(f"global tokens_total={tokens_total} exceeds kill switch {DEFAULT_TOKEN_KILL_SWITCH}")

    scenarios_raw = report.get("scenarios") if isinstance(report, dict) else None
    scenario_map = {
        str(item.get("name")): item
        for item in (scenarios_raw or [])
        if isinstance(item, dict) and item.get("name")
    }

    def _scenario_metric(name: str, key: str, default: float = 0.0) -> float:
        scenario = scenario_map.get(name) or {}
        return float(scenario.get(key, default) or 0.0)

    if _scenario_metric("remote_clean", "step_success_rate") < 0.98:
        errors.append("remote_clean.step_success_rate < 0.98")
    if _scenario_metric("remote_jitter_mild", "step_success_rate") < 0.95:
        errors.append("remote_jitter_mild.step_success_rate < 0.95")
    if _scenario_metric("remote_jitter_severe", "step_success_rate") < 0.88:
        errors.append("remote_jitter_severe.step_success_rate < 0.88")

    for name, scenario in scenario_map.items():
        detail_counts = scenario.get("detail_code_counts") if isinstance(scenario, dict) else {}
        status_counts = scenario.get("status_code_counts") if isinstance(scenario, dict) else {}
        status_503 = int((status_counts or {}).get("503", 0) or 0)
        llm_503 = int((detail_counts or {}).get("LLM_UNAVAILABLE", 0) or 0)
        if status_503 != llm_503:
            errors.append(f"{name}: status 503 ({status_503}) != LLM_UNAVAILABLE ({llm_503})")

        violations = int(scenario.get("llm_unavailable_state_advance_violations", 0) or 0)
        if violations > 0:
            errors.append(f"{name}: llm_unavailable_state_advance_violations={violations}")

        duplicate_violations = int(scenario.get("uncertain_duplicate_violation", 0) or 0)
        if duplicate_violations > 0:
            errors.append(f"{name}: uncertain_duplicate_violation={duplicate_violations}")

        idempotency_expected = int(scenario.get("idempotency_reused_checks_expected", 0) or 0)
        idempotency_passed = int(scenario.get("idempotency_reused_checks_passed", 0) or 0)
        if idempotency_expected > 0 and idempotency_passed < idempotency_expected:
            errors.append(
                f"{name}: idempotency_reused_checks_passed={idempotency_passed} < expected={idempotency_expected}"
            )

    aggregated = report.get("aggregated_input_metrics") if isinstance(report, dict) else {}
    clear_bucket = (aggregated or {}).get("free_input_clear") if isinstance(aggregated, dict) else {}
    noise_bucket = (aggregated or {}).get("free_input_noise") if isinstance(aggregated, dict) else {}
    clear_fallback = float((clear_bucket or {}).get("fallback_rate", 0.0) or 0.0)
    noise_fallback = float((noise_bucket or {}).get("fallback_rate", 0.0) or 0.0)
    if clear_fallback >= noise_fallback:
        errors.append(
            f"input gradient invalid: free_input_clear.fallback_rate={clear_fallback:.4f} >= free_input_noise.fallback_rate={noise_fallback:.4f}"
        )

    return errors


def _safe_json(response: httpx.Response | Any) -> Any:
    text = getattr(response, "text", "") or ""
    if not text:
        return {}
    try:
        return response.json()
    except Exception:
        return text


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int((percentile / 100.0) * (len(ordered) - 1))))
    return float(ordered[rank])


def _detail_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        return str(detail.get("code"))
    return None


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _resolve_sqlite_path(database_url: str | None) -> Path | None:
    if not database_url:
        return None
    url = str(database_url).strip()
    prefixes = ["sqlite:///", "sqlite+pysqlite:///"]
    for prefix in prefixes:
        if url.startswith(prefix):
            raw_path = url[len(prefix) :]
            return Path(raw_path).expanduser().resolve()
    return None


def _load_input_sets(path: Path) -> dict[str, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for key in ("free_input_clear", "free_input_ambiguous", "free_input_noise"):
        values = payload.get(key) if isinstance(payload, dict) else []
        out[key] = [str(item) for item in values if isinstance(item, str)]
    return out


def _weighted_input_kind(rng: random.Random) -> str:
    draw = rng.random()
    cursor = 0.0
    for key, weight in DEFAULT_INPUT_WEIGHTS.items():
        cursor += float(weight)
        if draw <= cursor:
            return key
    return "free_input_noise"


def _pick_step_payload(
    *,
    state: dict[str, Any],
    input_sets: dict[str, list[str]],
    rng: random.Random,
) -> tuple[str, dict[str, Any]]:
    kind = _weighted_input_kind(rng)
    if kind == "choice_direct":
        choices = ((state.get("current_node") or {}).get("choices") or []) if isinstance(state, dict) else []
        available = [item for item in choices if bool(item.get("is_available", True))]
        candidates = available if available else list(choices)
        if candidates:
            selected = rng.choice(candidates)
            return kind, {"choice_id": str(selected.get("id") or "")}
        kind = "free_input_clear"

    values = input_sets.get(kind) or []
    if not values:
        values = ["study"] if kind == "free_input_clear" else ["nonsense ???"]
    return kind, {"player_input": rng.choice(values)}


def _increment_counter(bucket: dict[str, int], key: str) -> None:
    bucket[key] = int(bucket.get(key, 0) or 0) + 1


def _sync_budget(
    *,
    monitor: SQLiteUsageMonitor | None,
    budget: BudgetState,
    scenario: ScenarioMetrics,
    session_ids: set[str],
    fallback_call_increment: int = 0,
    fallback_tokens_in: int = 0,
    fallback_tokens_out: int = 0,
) -> None:
    if monitor is not None:
        new_calls, tokens_in, tokens_out = monitor.refresh(session_ids)
    else:
        new_calls, tokens_in, tokens_out = fallback_call_increment, fallback_tokens_in, fallback_tokens_out

    if new_calls <= 0 and tokens_in <= 0 and tokens_out <= 0:
        return

    budget.llm_calls_total += int(new_calls)
    budget.tokens_in_total += int(tokens_in)
    budget.tokens_out_total += int(tokens_out)
    budget.tokens_total = budget.tokens_in_total + budget.tokens_out_total

    scenario.llm_calls_delta += int(new_calls)
    scenario.tokens_in_delta += int(tokens_in)
    scenario.tokens_out_delta += int(tokens_out)
    scenario.tokens_total_delta = scenario.tokens_in_delta + scenario.tokens_out_delta


def _parse_cost(payload: Any) -> tuple[int, int, str]:
    if not isinstance(payload, dict):
        return 0, 0, "unknown"
    cost = payload.get("cost")
    if not isinstance(cost, dict):
        return 0, 0, "unknown"
    tokens_in = int(cost.get("tokens_in", 0) or 0)
    tokens_out = int(cost.get("tokens_out", 0) or 0)
    provider = str(cost.get("provider") or "unknown")
    return tokens_in, tokens_out, provider


def _run_idempotency_reused_check(
    *,
    client: Any,
    story_id: str,
    version: int | None,
    rng: random.Random,
    metrics: ScenarioMetrics,
) -> tuple[str | None, int, int, int]:
    metrics.idempotency_reused_checks_expected += 1
    try:
        sid = client.create_session(story_id, version)
        state = client.get_session(sid)
        choices = ((state.get("current_node") or {}).get("choices") or []) if isinstance(state, dict) else []
        if len(choices) < 2:
            return sid, 0, 0, 0
        payload_a = {"choice_id": str(choices[0].get("id") or "")}
        payload_b = {"choice_id": str(choices[1].get("id") or "")}
        key = str(uuid.uuid4())
        status_a, data_a, _lat_a = client.step(sid, payload_a, key)
        status_b, data_b, _lat_b = client.step(sid, payload_b, key)
        call_increment = 0
        tokens_in = 0
        tokens_out = 0
        if status_a == 200:
            cost_in, cost_out, provider = _parse_cost(data_a)
            if provider != "none" and (cost_in > 0 or cost_out > 0):
                call_increment = 1
                tokens_in = cost_in
                tokens_out = cost_out
        if status_a in {200, 503} and status_b == 409 and _detail_code(data_b) == "IDEMPOTENCY_KEY_REUSED":
            metrics.idempotency_reused_checks_passed += 1
        return sid, call_increment, tokens_in, tokens_out
    except Exception:
        return None, 0, 0, 0


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    rng = random.Random(int(args.seed))
    input_sets = _load_input_sets(Path(args.input_sets_path))

    token_projection = project_token_budget_for_calls(DEFAULT_CALL_TARGET)

    db_url = args.database_url
    if not db_url:
        try:
            from app.config import settings

            db_url = settings.database_url
        except Exception:
            db_url = None
    sqlite_path = _resolve_sqlite_path(db_url)
    monitor = None
    if sqlite_path is not None and sqlite_path.exists():
        monitor = SQLiteUsageMonitor(sqlite_path)

    budget = BudgetState()
    all_session_ids: set[str] = set()
    scenarios = build_default_scenarios()
    scenario_results: list[ScenarioMetrics] = []

    toxiproxy = None
    if args.target in {"both", "remote"} and args.enable_toxiproxy:
        toxiproxy = ToxiproxyManager(
            api_url=args.toxiproxy_url,
            proxy_name=args.toxiproxy_proxy_name,
            listen=args.toxiproxy_listen,
            upstream=args.toxiproxy_upstream,
        )

    remote_client = RemoteClient(args.base_url) if args.target in {"both", "remote"} else None

    try:
        for spec in scenarios:
            if budget.stop_reason:
                break
            if args.target == "local" and spec.source != "local":
                continue
            if args.target == "remote" and spec.source != "remote":
                continue

            metrics = ScenarioMetrics(name=spec.name, llm_calls_target=int(spec.call_quota))
            scenario_results.append(metrics)

            scenario_start_calls = budget.llm_calls_total
            scenario_actions = 0

            if spec.source == "remote":
                if remote_client is None:
                    metrics.error = "remote client is unavailable"
                    metrics.stop_reason = "SCENARIO_SETUP_FAILED"
                    continue
                scenario_client = remote_client
                if toxiproxy is not None:
                    try:
                        toxiproxy.apply_profile(spec.jitter_profile)
                    except Exception as exc:
                        metrics.error = f"toxiproxy setup failed: {exc}"
                        metrics.stop_reason = "SCENARIO_SETUP_FAILED"
                        continue
            else:
                try:
                    scenario_client = LocalFakeClient()
                except Exception as exc:
                    metrics.error = f"local client setup failed: {exc}"
                    metrics.stop_reason = "SCENARIO_SETUP_FAILED"
                    continue

            try:
                probe_sid, probe_call_increment, probe_tokens_in, probe_tokens_out = _run_idempotency_reused_check(
                    client=scenario_client,
                    story_id=args.story_id,
                    version=args.version,
                    rng=rng,
                    metrics=metrics,
                )
                if probe_sid:
                    all_session_ids.add(probe_sid)
                _sync_budget(
                    monitor=monitor,
                    budget=budget,
                    scenario=metrics,
                    session_ids=all_session_ids,
                    fallback_call_increment=probe_call_increment,
                    fallback_tokens_in=probe_tokens_in,
                    fallback_tokens_out=probe_tokens_out,
                )

                session_id = scenario_client.create_session(args.story_id, args.version)
                all_session_ids.add(session_id)

                while True:
                    scenario_actions += 1
                    if scenario_actions > int(args.max_actions_per_scenario):
                        metrics.stop_reason = "ACTION_CAP_REACHED"
                        break

                    if budget.llm_calls_total >= DEFAULT_CALL_TARGET:
                        budget.stop_reason = "CALL_TARGET_REACHED"
                        metrics.stop_reason = "GLOBAL_CALL_TARGET_REACHED"
                        break
                    if budget.tokens_total >= DEFAULT_TOKEN_KILL_SWITCH:
                        budget.stop_reason = "BUDGET_KILL_SWITCH"
                        metrics.stop_reason = "BUDGET_KILL_SWITCH"
                        break
                    if budget.tokens_total >= DEFAULT_TOKEN_WARNING and "COST_WARNING" not in budget.warnings:
                        budget.warnings.append("COST_WARNING")

                    scenario_calls = budget.llm_calls_total - scenario_start_calls
                    if scenario_calls >= spec.call_quota:
                        metrics.stop_reason = "SCENARIO_CALL_TARGET_REACHED"
                        break

                    pre_state = scenario_client.get_session(session_id)
                    input_kind, payload = _pick_step_payload(state=pre_state, input_sets=input_sets, rng=rng)
                    key = str(uuid.uuid4())

                    metrics.actions_attempted += 1
                    bucket = metrics.input_buckets[input_kind]
                    bucket.attempts += 1

                    status, data, latency_ms = scenario_client.step(session_id, payload, key)
                    metrics.latencies_ms.append(latency_ms)
                    bucket.latencies_ms.append(latency_ms)
                    _increment_counter(metrics.status_code_counts, str(status))

                    detail_code = _detail_code(data)
                    if detail_code:
                        _increment_counter(metrics.detail_code_counts, detail_code)

                    fallback_calls = 0
                    fallback_tokens_in = 0
                    fallback_tokens_out = 0

                    if status == 200:
                        metrics.success_2xx += 1
                        bucket.success_2xx += 1
                        fallback_used = bool(data.get("fallback_used")) if isinstance(data, dict) else False
                        if fallback_used:
                            metrics.fallback_count += 1
                            bucket.fallback_count += 1

                        tokens_in, tokens_out, provider = _parse_cost(data)
                        if monitor is None and provider != "none" and (tokens_in > 0 or tokens_out > 0):
                            fallback_calls = 1
                            fallback_tokens_in = tokens_in
                            fallback_tokens_out = tokens_out

                        if bool(args.enable_client_uncertain_sim) and rng.random() < float(args.uncertain_drop_rate):
                            metrics.uncertain_total += 1
                            replay_status, replay_data, _replay_latency = scenario_client.step(session_id, payload, key)
                            _increment_counter(metrics.uncertain_retry_status_counts, str(replay_status))
                            if replay_status == 200:
                                metrics.uncertain_recovered += 1
                                if _stable_json(replay_data) != _stable_json(data):
                                    metrics.uncertain_duplicate_violation += 1

                        if isinstance(data, dict) and bool(data.get("run_ended", False)):
                            session_id = scenario_client.create_session(args.story_id, args.version)
                            all_session_ids.add(session_id)
                    elif status == 503:
                        bucket.status_503_count += 1
                        if detail_code == "LLM_UNAVAILABLE":
                            bucket.llm_unavailable_count += 1
                        post_state = scenario_client.get_session(session_id)
                        if _stable_json(post_state.get("state_json")) != _stable_json(pre_state.get("state_json")):
                            metrics.llm_unavailable_state_advance_violations += 1
                    elif status == 0:
                        _increment_counter(metrics.detail_code_counts, "NETWORK_ERROR")

                    _sync_budget(
                        monitor=monitor,
                        budget=budget,
                        scenario=metrics,
                        session_ids=all_session_ids,
                        fallback_call_increment=fallback_calls,
                        fallback_tokens_in=fallback_tokens_in,
                        fallback_tokens_out=fallback_tokens_out,
                    )

                    if budget.tokens_total >= DEFAULT_TOKEN_WARNING and "COST_WARNING" not in budget.warnings:
                        budget.warnings.append("COST_WARNING")
            except Exception as exc:
                metrics.error = f"scenario runtime failed: {exc}"
                if not metrics.stop_reason:
                    metrics.stop_reason = "SCENARIO_RUNTIME_FAILED"
            finally:
                if spec.source == "local" and hasattr(scenario_client, "close"):
                    scenario_client.close()

            if not metrics.stop_reason:
                metrics.stop_reason = "SCENARIO_FINISHED"

        if not budget.stop_reason:
            budget.stop_reason = "SCENARIOS_FINISHED"

    finally:
        if remote_client is not None:
            remote_client.close()
        if toxiproxy is not None:
            try:
                toxiproxy.clear_toxics()
            except Exception:
                pass
            toxiproxy.close()

    aggregated_input = _aggregate_input_buckets(scenario_results)
    report = {
        "meta": {
            "story_id": args.story_id,
            "version": args.version,
            "seed": args.seed,
            "target": args.target,
            "started_at_epoch_s": int(time.time()),
            "database_url": db_url,
            "sqlite_monitor_enabled": bool(monitor is not None),
            "input_sets_path": args.input_sets_path,
        },
        "budget_projection_for_200_calls": {
            "avg_total_tokens": token_projection.avg_total_tokens,
            "p95_total_tokens": token_projection.p95_total_tokens,
            "p99_total_tokens": token_projection.p99_total_tokens,
            "max_envelope_tokens": token_projection.max_envelope_tokens,
        },
        "global": {
            "llm_calls_total": budget.llm_calls_total,
            "tokens_in_total": budget.tokens_in_total,
            "tokens_out_total": budget.tokens_out_total,
            "tokens_total": budget.tokens_total,
            "stop_reason": budget.stop_reason,
            "warnings": budget.warnings,
        },
        "scenarios": [item.to_dict() for item in scenario_results],
        "aggregated_input_metrics": aggregated_input,
    }

    gate_errors = evaluate_release_v1(report)
    report["release_gate_profile"] = "release_v1"
    report["release_gate_passed"] = len(gate_errors) == 0
    report["release_gate_errors"] = gate_errors
    return report


def _aggregate_input_buckets(scenarios: list[ScenarioMetrics]) -> dict[str, Any]:
    aggregate: dict[str, InputBucketMetrics] = {
        "choice_direct": InputBucketMetrics(),
        "free_input_clear": InputBucketMetrics(),
        "free_input_ambiguous": InputBucketMetrics(),
        "free_input_noise": InputBucketMetrics(),
    }

    for scenario in scenarios:
        for key, bucket in scenario.input_buckets.items():
            target = aggregate[key]
            target.attempts += bucket.attempts
            target.success_2xx += bucket.success_2xx
            target.fallback_count += bucket.fallback_count
            target.status_503_count += bucket.status_503_count
            target.llm_unavailable_count += bucket.llm_unavailable_count
            target.latencies_ms.extend(bucket.latencies_ms)

    return {key: value.to_dict() for key, value in aggregate.items()}


def _build_markdown_report(report: dict[str, Any]) -> str:
    global_section = report.get("global") or {}
    lines: list[str] = []
    lines.append("# Release Benchmark Report")
    lines.append("")
    lines.append(f"- release_gate_passed: **{report.get('release_gate_passed')}**")
    lines.append(f"- stop_reason: `{global_section.get('stop_reason')}`")
    lines.append(
        "- llm_calls_total: "
        f"`{global_section.get('llm_calls_total')}` | tokens_total: `{global_section.get('tokens_total')}`"
    )
    warnings = global_section.get("warnings") or []
    lines.append(f"- warnings: `{warnings}`")
    lines.append("")
    lines.append("## Scenarios")
    lines.append("")
    lines.append("| scenario | calls(delta/target) | success_rate | fallback_rate | latency_p95_ms | stop_reason |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for scenario in report.get("scenarios") or []:
        lines.append(
            "| "
            f"{scenario.get('name')} | "
            f"{scenario.get('llm_calls_delta')}/{scenario.get('llm_calls_target')} | "
            f"{scenario.get('step_success_rate')} | "
            f"{scenario.get('fallback_rate')} | "
            f"{scenario.get('latency_p95_ms')} | "
            f"{scenario.get('stop_reason')} |"
        )
    lines.append("")
    lines.append("## Gate Errors")
    errors = report.get("release_gate_errors") or []
    if not errors:
        lines.append("- none")
    else:
        for item in errors:
            lines.append(f"- {item}")
    lines.append("")
    lines.append("## Aggregated Input Metrics")
    for key, value in (report.get("aggregated_input_metrics") or {}).items():
        lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False)}")
    return "\n".join(lines)


def _default_database_url() -> str | None:
    try:
        from app.config import settings

        return str(settings.database_url)
    except Exception:
        return None


def _default_toxiproxy_upstream() -> str:
    try:
        from app.config import settings

        base = str(settings.llm_doubao_base_url).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base.replace("http://", "").replace("https://", "")
    except Exception:
        return "39.105.34.149:11451"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Release benchmark runner with 200 LLM-call budget gate.")
    parser.add_argument("--target", choices=["local", "remote", "both"], default="both")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--story-id", default="campus_week_v1")
    parser.add_argument("--version", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--input-sets-path", default="scripts/benchmark_input_sets.json")
    parser.add_argument("--max-actions-per-scenario", type=int, default=3000)
    parser.add_argument("--enable-client-uncertain-sim", action="store_true", default=True)
    parser.add_argument("--disable-client-uncertain-sim", action="store_false", dest="enable_client_uncertain_sim")
    parser.add_argument("--uncertain-drop-rate", type=float, default=0.03)
    parser.add_argument("--output-json", default="artifacts/benchmark_release.json")
    parser.add_argument("--output-md", default="artifacts/benchmark_release.md")
    parser.add_argument("--enable-toxiproxy", action="store_true", default=True)
    parser.add_argument("--disable-toxiproxy", action="store_false", dest="enable_toxiproxy")
    parser.add_argument("--toxiproxy-url", default="http://127.0.0.1:8474")
    parser.add_argument("--toxiproxy-proxy-name", default="llm_upstream")
    parser.add_argument("--toxiproxy-listen", default="127.0.0.1:11452")
    parser.add_argument("--toxiproxy-upstream", default=_default_toxiproxy_upstream())
    parser.add_argument("--assert-profile", choices=["release_v1", "none"], default="release_v1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_benchmark(args)

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(_build_markdown_report(report), encoding="utf-8")

    print(json.dumps(report["global"], ensure_ascii=False, indent=2))
    print(f"report_json={output_json}")
    print(f"report_md={output_md}")

    if args.assert_profile == "release_v1" and not report.get("release_gate_passed", False):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
