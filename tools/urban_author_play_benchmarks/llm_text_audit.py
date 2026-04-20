from __future__ import annotations

import json
from collections import Counter
from statistics import mean
import threading
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.config import HelperResponsesEndpoint, get_settings
from rpg_backend.responses_transport import build_openai_client

LLM_TEXT_AUDIT_FLAGS = (
    "角色反应太泛",
    "选择不够痛",
    "爆点没落地",
    "模板味偏重",
    "中文语感不足",
    "壳子辨识弱",
)
TURN_SCORE_KEYS = (
    "tone_naturalness",
    "character_specificity",
    "dramatic_tension",
    "shell_fidelity",
    "consequence_clarity",
    "anti_template_stiffness",
)
SESSION_SCORE_KEYS = (
    "arc_coherence",
    "payoff_strength",
    "npc_presence",
    "style_consistency",
    "shell_distinctiveness",
    "memorable_moments",
)
TURN_AUDIT_INSTRUCTIONS = (
    "你是都市关系戏文本审计员。请基于提供的文本主审信号和结构化辅证给出严格评分。"
    "只输出 JSON 对象，不要输出额外说明。"
    "优先输出结构：{\"scores\":{\"tone_naturalness\":1-5,\"character_specificity\":1-5,"
    "\"dramatic_tension\":1-5,\"shell_fidelity\":1-5,\"consequence_clarity\":1-5,"
    "\"anti_template_stiffness\":1-5},\"strongest_signal\":\"...\",\"main_issue\":\"...\","
    "\"flags\":[\"角色反应太泛\"...]}。"
)
SESSION_AUDIT_INSTRUCTIONS = (
    "你是都市关系戏会话审计员。请基于整局文本片段与结构化信号进行总结评分。"
    "只输出 JSON 对象，不要输出额外说明。"
    "优先输出结构：{\"scores\":{\"arc_coherence\":1-5,\"payoff_strength\":1-5,"
    "\"npc_presence\":1-5,\"style_consistency\":1-5,\"shell_distinctiveness\":1-5,"
    "\"memorable_moments\":1-5},\"best_moment\":\"...\",\"worst_moment\":\"...\","
    "\"one_sentence_verdict\":\"...\",\"top_issues\":[...],\"top_strengths\":[...],"
    "\"flags\":[...]}。"
)


_HELPER_KEY_CURSOR_LOCK = threading.Lock()
_HELPER_KEY_CURSOR_BY_SCOPE: dict[str, int] = {}

class TurnLlmTextAuditScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tone_naturalness: float = Field(ge=1, le=5)
    character_specificity: float = Field(ge=1, le=5)
    dramatic_tension: float = Field(ge=1, le=5)
    shell_fidelity: float = Field(ge=1, le=5)
    consequence_clarity: float = Field(ge=1, le=5)
    anti_template_stiffness: float = Field(ge=1, le=5)


class SessionLlmTextAuditScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arc_coherence: float = Field(ge=1, le=5)
    payoff_strength: float = Field(ge=1, le=5)
    npc_presence: float = Field(ge=1, le=5)
    style_consistency: float = Field(ge=1, le=5)
    shell_distinctiveness: float = Field(ge=1, le=5)
    memorable_moments: float = Field(ge=1, le=5)


class LlmTextAuditEndpointResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=240)
    model: str = Field(min_length=1, max_length=120)
    status: Literal["completed", "failed"] = "completed"
    response_id: str | None = Field(default=None, max_length=120)
    scores: dict[str, float] | None = None
    strongest_signal: str | None = Field(default=None, max_length=220)
    main_issue: str | None = Field(default=None, max_length=220)
    flags: list[str] = Field(default_factory=list, max_length=6)
    best_moment: str | None = Field(default=None, max_length=240)
    worst_moment: str | None = Field(default=None, max_length=240)
    one_sentence_verdict: str | None = Field(default=None, max_length=240)
    top_issues: list[str] = Field(default_factory=list, max_length=5)
    top_strengths: list[str] = Field(default_factory=list, max_length=5)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=240)


class TurnLlmTextAuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    turn_index: int = Field(ge=1)
    story_shell_id: str = Field(min_length=1)
    segment_role: str = Field(min_length=1)
    llm_audit_status: Literal["completed", "partial_success", "failed"] = "completed"
    scores: TurnLlmTextAuditScores | None = None
    strongest_signal: str | None = Field(default=None, max_length=220)
    main_issue: str | None = Field(default=None, max_length=220)
    flags: list[str] = Field(default_factory=list, max_length=6)
    disagreement_index: float | None = Field(default=None, ge=0, le=4)
    endpoint_results: list[LlmTextAuditEndpointResult] = Field(default_factory=list, max_length=2)
    llm_audit_error: str | None = Field(default=None, max_length=240)


class SessionLlmTextAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    llm_audit_status: Literal["completed", "partial_success", "failed"] = "completed"
    scores: SessionLlmTextAuditScores | None = None
    best_moment: str | None = Field(default=None, max_length=240)
    worst_moment: str | None = Field(default=None, max_length=240)
    one_sentence_verdict: str | None = Field(default=None, max_length=240)
    top_issues: list[str] = Field(default_factory=list, max_length=5)
    top_strengths: list[str] = Field(default_factory=list, max_length=5)
    disagreement_index: float | None = Field(default=None, ge=0, le=4)
    endpoint_results: list[LlmTextAuditEndpointResult] = Field(default_factory=list, max_length=2)
    llm_audit_error: str | None = Field(default=None, max_length=240)


def _safe_float(value: Any, default: float = 3.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def _llm_text_audit_timeout_seconds(settings: Any) -> float:
    raw_timeout = getattr(settings, "responses_timeout_seconds_llm_text_audit", None)
    if raw_timeout is None:
        raw_timeout = getattr(settings, "responses_timeout_seconds", 60.0)
    return max(10.0, min(120.0, float(raw_timeout)))


def _score_1_to_5(value: Any, *, default: float = 3.0) -> float:
    return max(1.0, min(5.0, _safe_float(value, default)))


def _normalize_flags(values: list[Any]) -> list[str]:
    allowed = set(LLM_TEXT_AUDIT_FLAGS)
    out: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        if value in allowed and value not in out:
            out.append(value)
        if len(out) >= 6:
            break
    return out


def _normalize_short_lines(values: list[Any], *, limit: int, max_length: int) -> list[str]:
    out: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        if not value:
            continue
        out.append(value[:max_length])
        if len(out) >= limit:
            break
    return out


def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if not candidate:
        raise ValueError("empty response text")
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            return payload
    except Exception:  # noqa: BLE001
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        payload = json.loads(candidate[start : end + 1])
        if isinstance(payload, dict):
            return payload
    raise ValueError("response is not a JSON object")


def _audit_endpoints() -> tuple[HelperResponsesEndpoint, ...]:
    settings = get_settings()
    endpoints = list(settings.configured_helper_responses_endpoints())
    # Single-helper policy: only the primary endpoint participates in LLM text audit.
    return tuple(endpoints[:1])


def _select_balanced_helper_endpoint(endpoint: HelperResponsesEndpoint) -> HelperResponsesEndpoint:
    settings = get_settings()
    key_pool = list(settings.helper_responses_api_key_pool())
    if not key_pool:
        return endpoint
    if len(key_pool) == 1:
        selected_key = key_pool[0]
        slot_name = endpoint.slot_name
    else:
        scope = f"{endpoint.base_url}|{endpoint.model}|{endpoint.slot_name}"
        with _HELPER_KEY_CURSOR_LOCK:
            key_index = _HELPER_KEY_CURSOR_BY_SCOPE.get(scope, 0) % len(key_pool)
            _HELPER_KEY_CURSOR_BY_SCOPE[scope] = (key_index + 1) % len(key_pool)
        selected_key = key_pool[key_index]
        slot_name = f"{endpoint.slot_name}#key{key_index + 1}"
    return HelperResponsesEndpoint(
        slot_name=slot_name,
        base_url=endpoint.base_url,
        api_key=selected_key,
        model=endpoint.model,
        use_session_cache=endpoint.use_session_cache,
        weight=endpoint.weight,
        role=endpoint.role,
    )


def _invoke_endpoint_json(
    *,
    endpoint: HelperResponsesEndpoint,
    instructions: str,
    payload: dict[str, Any],
    max_output_tokens: int,
) -> tuple[dict[str, Any], str | None, int, int]:
    settings = get_settings()
    timeout_seconds = _llm_text_audit_timeout_seconds(settings)
    client = build_openai_client(
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
        use_session_cache=endpoint.use_session_cache,
        session_cache_header=settings.responses_session_cache_header,
        session_cache_value=settings.responses_session_cache_value,
        requests_per_minute=settings.helper_responses_requests_per_minute,
        rate_limit_scope="helper:llm_text_audit",
    )
    request_kwargs = {
        "model": endpoint.model,
        "instructions": instructions,
        "input": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "max_output_tokens": max_output_tokens,
        "timeout": timeout_seconds,
        "temperature": 0.0,
        "extra_body": {
            "response_format": {"type": "json_object"},
            **({"content_type": "json"} if bool(getattr(settings, "responses_json_content_type_hint", False)) else {}),
        },
    }
    if bool(getattr(settings, "helper_responses_enable_web_search", False)):
        request_kwargs["tools"] = [{"type": "web_search_preview"}]
    try:
        response = client.responses.create(**request_kwargs)
    except Exception:  # noqa: BLE001
        fallback_kwargs = dict(request_kwargs)
        fallback_kwargs.pop("extra_body", None)
        response = client.responses.create(**fallback_kwargs)
    text = str(getattr(response, "output_text", "") or "")
    usage = getattr(response, "usage", {}) or {}
    input_tokens = int(_safe_float(dict(usage).get("input_tokens", 0), 0.0))
    output_tokens = int(_safe_float(dict(usage).get("output_tokens", 0), 0.0))
    return _parse_json_object(text), getattr(response, "id", None), max(input_tokens, 0), max(output_tokens, 0)


def _turn_scores_from_payload(payload: dict[str, Any]) -> TurnLlmTextAuditScores:
    return TurnLlmTextAuditScores(
        tone_naturalness=_score_1_to_5(payload.get("tone_naturalness")),
        character_specificity=_score_1_to_5(payload.get("character_specificity")),
        dramatic_tension=_score_1_to_5(payload.get("dramatic_tension")),
        shell_fidelity=_score_1_to_5(payload.get("shell_fidelity")),
        consequence_clarity=_score_1_to_5(payload.get("consequence_clarity")),
        anti_template_stiffness=_score_1_to_5(payload.get("anti_template_stiffness")),
    )


def _session_scores_from_payload(payload: dict[str, Any]) -> SessionLlmTextAuditScores:
    return SessionLlmTextAuditScores(
        arc_coherence=_score_1_to_5(payload.get("arc_coherence")),
        payoff_strength=_score_1_to_5(payload.get("payoff_strength")),
        npc_presence=_score_1_to_5(payload.get("npc_presence")),
        style_consistency=_score_1_to_5(payload.get("style_consistency")),
        shell_distinctiveness=_score_1_to_5(payload.get("shell_distinctiveness")),
        memorable_moments=_score_1_to_5(payload.get("memorable_moments")),
    )


def _extract_metric_payload(raw: dict[str, Any], metric_keys: tuple[str, ...]) -> dict[str, Any]:
    nested = raw.get("scores")
    if isinstance(nested, dict):
        return nested
    direct: dict[str, Any] = {}
    for key in metric_keys:
        if key in raw:
            direct[key] = raw.get(key)
    if direct:
        return direct
    if "score" in raw:
        return {key: raw.get("score") for key in metric_keys}
    return {}


def _evaluate_turn_on_endpoint(endpoint: HelperResponsesEndpoint, payload: dict[str, Any]) -> LlmTextAuditEndpointResult:
    selected_endpoint = _select_balanced_helper_endpoint(endpoint)
    started = time.perf_counter()
    try:
        raw, response_id, input_tokens, output_tokens = _invoke_endpoint_json(
            endpoint=selected_endpoint,
            instructions=TURN_AUDIT_INSTRUCTIONS,
            payload=payload,
            max_output_tokens=420,
        )
        score_payload = _extract_metric_payload(raw, TURN_SCORE_KEYS)
        if not score_payload:
            raise ValueError("llm_text_audit_missing_scores")
        scores = _turn_scores_from_payload(score_payload)
        rationale_lines = _normalize_short_lines(list(raw.get("rationale") or []), limit=4, max_length=220)
        strongest_signal = str(raw.get("strongest_signal") or "").strip()[:220] or (rationale_lines[0] if rationale_lines else None)
        main_issue = str(raw.get("main_issue") or "").strip()[:220] or (rationale_lines[-1] if len(rationale_lines) > 1 else None)
        return LlmTextAuditEndpointResult(
            slot_name=selected_endpoint.slot_name,
            base_url=selected_endpoint.base_url,
            model=selected_endpoint.model,
            status="completed",
            response_id=response_id,
            scores=scores.model_dump(mode="json"),
            strongest_signal=strongest_signal,
            main_issue=main_issue,
            flags=_normalize_flags(list(raw.get("flags") or [])),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
        )
    except Exception as exc:  # noqa: BLE001
        return LlmTextAuditEndpointResult(
            slot_name=selected_endpoint.slot_name,
            base_url=selected_endpoint.base_url,
            model=selected_endpoint.model,
            status="failed",
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
            error=str(exc)[:240],
        )


def _evaluate_session_on_endpoint(endpoint: HelperResponsesEndpoint, payload: dict[str, Any]) -> LlmTextAuditEndpointResult:
    selected_endpoint = _select_balanced_helper_endpoint(endpoint)
    started = time.perf_counter()
    try:
        raw, response_id, input_tokens, output_tokens = _invoke_endpoint_json(
            endpoint=selected_endpoint,
            instructions=SESSION_AUDIT_INSTRUCTIONS,
            payload=payload,
            max_output_tokens=560,
        )
        score_payload = _extract_metric_payload(raw, SESSION_SCORE_KEYS)
        if not score_payload:
            raise ValueError("llm_text_audit_missing_scores")
        scores = _session_scores_from_payload(score_payload)
        rationale_lines = _normalize_short_lines(list(raw.get("rationale") or []), limit=5, max_length=240)
        best_moment = str(raw.get("best_moment") or "").strip()[:240] or (rationale_lines[0] if rationale_lines else None)
        worst_moment = str(raw.get("worst_moment") or "").strip()[:240] or None
        verdict = str(raw.get("one_sentence_verdict") or "").strip()[:240] or (rationale_lines[0] if rationale_lines else None)
        top_issues = _normalize_short_lines(list(raw.get("top_issues") or []), limit=5, max_length=240) or rationale_lines
        return LlmTextAuditEndpointResult(
            slot_name=selected_endpoint.slot_name,
            base_url=selected_endpoint.base_url,
            model=selected_endpoint.model,
            status="completed",
            response_id=response_id,
            scores=scores.model_dump(mode="json"),
            best_moment=best_moment,
            worst_moment=worst_moment,
            one_sentence_verdict=verdict,
            top_issues=top_issues,
            top_strengths=_normalize_short_lines(list(raw.get("top_strengths") or []), limit=5, max_length=240),
            flags=_normalize_flags(list(raw.get("flags") or [])),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
        )
    except Exception as exc:  # noqa: BLE001
        return LlmTextAuditEndpointResult(
            slot_name=selected_endpoint.slot_name,
            base_url=selected_endpoint.base_url,
            model=selected_endpoint.model,
            status="failed",
            latency_ms=round((time.perf_counter() - started) * 1000, 4),
            error=str(exc)[:240],
        )


def _evaluate_endpoints_with_deadline(
    *,
    endpoints: tuple[HelperResponsesEndpoint, ...],
    timeout_seconds: float,
    worker: Any,
) -> list[LlmTextAuditEndpointResult]:
    results_by_slot: dict[str, LlmTextAuditEndpointResult] = {}
    threads: list[tuple[str, threading.Thread]] = []
    lock = threading.Lock()

    def _run(endpoint: HelperResponsesEndpoint) -> None:
        result = worker(endpoint)
        with lock:
            results_by_slot[endpoint.slot_name] = result

    for endpoint in endpoints:
        thread = threading.Thread(target=_run, args=(endpoint,), daemon=True)
        thread.start()
        threads.append((endpoint.slot_name, thread))

    deadline = time.monotonic() + timeout_seconds
    for _, thread in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        thread.join(remaining)

    ordered: list[LlmTextAuditEndpointResult] = []
    for endpoint in endpoints:
        result = results_by_slot.get(endpoint.slot_name)
        if result is None:
            result = LlmTextAuditEndpointResult(
                slot_name=endpoint.slot_name,
                base_url=endpoint.base_url,
                model=endpoint.model,
                status="failed",
                error=f"llm_text_audit_timeout:{int(timeout_seconds)}s",
            )
        ordered.append(result)
    return ordered


def _disagreement_index(successes: list[LlmTextAuditEndpointResult], metric_keys: tuple[str, ...]) -> float | None:
    if len(successes) < 2:
        return None
    a = dict(successes[0].scores or {})
    b = dict(successes[1].scores or {})
    return round(max(abs(_safe_float(a.get(key)) - _safe_float(b.get(key))) for key in metric_keys), 4)


def _aggregate_turn(
    *,
    case_id: str,
    persona_id: str,
    turn_index: int,
    story_shell_id: str,
    segment_role: str,
    endpoint_results: list[LlmTextAuditEndpointResult],
) -> TurnLlmTextAuditRecord:
    successes = [result for result in endpoint_results if result.status == "completed" and result.scores is not None]
    if not successes:
        error = "; ".join(result.error or "unknown" for result in endpoint_results if result.error)[:240] or "all endpoints failed"
        return TurnLlmTextAuditRecord(
            case_id=case_id,
            persona_id=persona_id,
            turn_index=turn_index,
            story_shell_id=story_shell_id,
            segment_role=segment_role,
            llm_audit_status="failed",
            endpoint_results=endpoint_results,
            llm_audit_error=error,
        )
    metric_means = {
        key: round(mean(_safe_float(result.scores.get(key)) for result in successes if result.scores is not None), 4)
        for key in TURN_SCORE_KEYS
    }
    flag_counter: Counter[str] = Counter()
    for result in successes:
        flag_counter.update(result.flags)
    best_endpoint = max(successes, key=lambda item: sum(_safe_float((item.scores or {}).get(key)) for key in TURN_SCORE_KEYS))
    status: Literal["completed", "partial_success", "failed"] = "completed" if len(successes) == len(endpoint_results) else "partial_success"
    return TurnLlmTextAuditRecord(
        case_id=case_id,
        persona_id=persona_id,
        turn_index=turn_index,
        story_shell_id=story_shell_id,
        segment_role=segment_role,
        llm_audit_status=status,
        scores=TurnLlmTextAuditScores(**metric_means),
        strongest_signal=best_endpoint.strongest_signal,
        main_issue=best_endpoint.main_issue,
        flags=[flag for flag, _ in flag_counter.most_common(6)],
        disagreement_index=_disagreement_index(successes, TURN_SCORE_KEYS),
        endpoint_results=endpoint_results,
    )


def _aggregate_session(
    *,
    case_id: str,
    persona_id: str,
    endpoint_results: list[LlmTextAuditEndpointResult],
) -> SessionLlmTextAuditReport:
    successes = [result for result in endpoint_results if result.status == "completed" and result.scores is not None]
    if not successes:
        error = "; ".join(result.error or "unknown" for result in endpoint_results if result.error)[:240] or "all endpoints failed"
        return SessionLlmTextAuditReport(
            case_id=case_id,
            persona_id=persona_id,
            llm_audit_status="failed",
            endpoint_results=endpoint_results,
            llm_audit_error=error,
        )
    metric_means = {
        key: round(mean(_safe_float(result.scores.get(key)) for result in successes if result.scores is not None), 4)
        for key in SESSION_SCORE_KEYS
    }
    issue_counter: Counter[str] = Counter()
    strength_counter: Counter[str] = Counter()
    for result in successes:
        issue_counter.update(result.top_issues)
        strength_counter.update(result.top_strengths)
    best_endpoint = max(successes, key=lambda item: sum(_safe_float((item.scores or {}).get(key)) for key in SESSION_SCORE_KEYS))
    status: Literal["completed", "partial_success", "failed"] = "completed" if len(successes) == len(endpoint_results) else "partial_success"
    return SessionLlmTextAuditReport(
        case_id=case_id,
        persona_id=persona_id,
        llm_audit_status=status,
        scores=SessionLlmTextAuditScores(**metric_means),
        best_moment=best_endpoint.best_moment,
        worst_moment=best_endpoint.worst_moment,
        one_sentence_verdict=best_endpoint.one_sentence_verdict,
        top_issues=[issue for issue, _ in issue_counter.most_common(5)],
        top_strengths=[strength for strength, _ in strength_counter.most_common(5)],
        disagreement_index=_disagreement_index(successes, SESSION_SCORE_KEYS),
        endpoint_results=endpoint_results,
    )


def evaluate_turn_text(payload: dict[str, Any]) -> TurnLlmTextAuditRecord:
    case_id = str(payload.get("case_id") or "unknown_case")
    persona_id = str(payload.get("persona_id") or "unknown_persona")
    turn_index = max(1, int(_safe_float(payload.get("turn_index"), 1)))
    story_shell_id = str(payload.get("story_shell_id") or "unknown_shell")
    segment_role = str(payload.get("segment_role") or "opening")
    endpoints = _audit_endpoints()
    if not endpoints:
        return TurnLlmTextAuditRecord(
            case_id=case_id,
            persona_id=persona_id,
            turn_index=turn_index,
            story_shell_id=story_shell_id,
            segment_role=segment_role,
            llm_audit_status="failed",
            llm_audit_error="no helper endpoints configured",
        )
    settings = get_settings()
    timeout_seconds = _llm_text_audit_timeout_seconds(settings)
    ordered = _evaluate_endpoints_with_deadline(
        endpoints=endpoints,
        timeout_seconds=timeout_seconds,
        worker=lambda endpoint: _evaluate_turn_on_endpoint(endpoint, payload),
    )
    return _aggregate_turn(
        case_id=case_id,
        persona_id=persona_id,
        turn_index=turn_index,
        story_shell_id=story_shell_id,
        segment_role=segment_role,
        endpoint_results=ordered,
    )


def evaluate_session_text(payload: dict[str, Any]) -> SessionLlmTextAuditReport:
    case_id = str(payload.get("case_id") or "unknown_case")
    persona_id = str(payload.get("persona_id") or "unknown_persona")
    endpoints = _audit_endpoints()
    if not endpoints:
        return SessionLlmTextAuditReport(
            case_id=case_id,
            persona_id=persona_id,
            llm_audit_status="failed",
            llm_audit_error="no helper endpoints configured",
        )
    settings = get_settings()
    timeout_seconds = _llm_text_audit_timeout_seconds(settings)
    ordered = _evaluate_endpoints_with_deadline(
        endpoints=endpoints,
        timeout_seconds=timeout_seconds,
        worker=lambda endpoint: _evaluate_session_on_endpoint(endpoint, payload),
    )
    return _aggregate_session(
        case_id=case_id,
        persona_id=persona_id,
        endpoint_results=ordered,
    )
