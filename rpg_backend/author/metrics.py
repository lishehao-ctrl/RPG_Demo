from __future__ import annotations

from typing import Any

from rpg_backend.author.contracts import (
    AuthorCacheMetrics,
    AuthorTokenCostEstimate,
    AuthorTokenUsageBucket,
)
from rpg_backend.config import get_settings


def _operation_stage(operation: str) -> str:
    if operation.startswith("story_frame_"):
        return "story_frame"
    if operation.startswith("cast_overview_"):
        return "cast_overview"
    if operation.startswith("cast_member_") or operation.startswith("cast_generate_") or operation.startswith("cast_glean_"):
        return "cast_member"
    if operation.startswith("beat_plan_"):
        return "beat_plan"
    if operation.startswith("route_"):
        return "route_affordance"
    if operation.startswith("ending_"):
        return "ending"
    return "unknown"


def _summarize_usage_buckets(
    llm_call_trace: list[dict[str, Any]] | None,
    *,
    bucket_resolver,
) -> list[AuthorTokenUsageBucket]:
    trace = list(llm_call_trace or [])
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in trace:
        bucket_id = str(bucket_resolver(str(item.get("operation") or "unknown")) or "unknown")
        buckets.setdefault(bucket_id, []).append(item)
    return [
        AuthorTokenUsageBucket(bucket_id=bucket_id, token_usage=summarize_cache_metrics(items))
        for bucket_id, items in sorted(buckets.items())
    ]


def summarize_cache_metrics(llm_call_trace: list[dict[str, Any]] | None) -> AuthorCacheMetrics:
    trace = list(llm_call_trace or [])
    total_input_characters = 0
    previous_response_call_count = 0
    session_cache_enabled = False
    provider_usage: dict[str, int] = {}
    cached_input_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_type: str | None = None
    billing_type: str | None = None

    for item in trace:
        total_input_characters += int(item.get("input_characters") or 0)
        if item.get("used_previous_response_id"):
            previous_response_call_count += 1
        if item.get("session_cache_enabled"):
            session_cache_enabled = True
        usage = dict(item.get("usage") or {})
        for key, value in usage.items():
            if isinstance(value, str):
                if key == "cache_type":
                    cache_type = value
                elif key == "billing_type":
                    billing_type = value
                continue
            provider_usage[key] = provider_usage.get(key, 0) + int(value)
        for usage_key, target_name in (
            ("cached_input_tokens", "cached_input_tokens"),
            ("cache_hit_tokens", "cache_hit_tokens"),
            ("cache_write_tokens", "cache_write_tokens"),
            ("cache_creation_tokens", "cache_write_tokens"),
            ("cache_creation_input_tokens", "cache_creation_input_tokens"),
            ("input_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
            ("reasoning_tokens", "reasoning_tokens"),
        ):
            if usage_key in usage:
                value = int(usage[usage_key])
                if target_name == "cached_input_tokens":
                    cached_input_tokens = (cached_input_tokens or 0) + value
                elif target_name == "cache_hit_tokens":
                    cache_hit_tokens = (cache_hit_tokens or 0) + value
                elif target_name == "cache_write_tokens":
                    cache_write_tokens = (cache_write_tokens or 0) + value
                elif target_name == "cache_creation_input_tokens":
                    cache_creation_input_tokens = (cache_creation_input_tokens or 0) + value
                elif target_name == "input_tokens":
                    input_tokens = (input_tokens or 0) + value
                elif target_name == "output_tokens":
                    output_tokens = (output_tokens or 0) + value
                elif target_name == "total_tokens":
                    total_tokens = (total_tokens or 0) + value
                elif target_name == "reasoning_tokens":
                    reasoning_tokens = (reasoning_tokens or 0) + value

    cache_metrics_source = "unavailable_from_provider_response"
    if any(
        key in provider_usage
        for key in ("cached_input_tokens", "cache_hit_tokens", "cache_write_tokens", "cache_creation_tokens")
    ):
        cache_metrics_source = "provider_usage_cache_fields"
    elif provider_usage:
        cache_metrics_source = "provider_usage_no_cache_breakdown"

    return AuthorCacheMetrics(
        session_cache_enabled=session_cache_enabled,
        cache_path_used=session_cache_enabled and previous_response_call_count > 0,
        total_call_count=len(trace),
        previous_response_call_count=previous_response_call_count,
        total_input_characters=total_input_characters,
        estimated_input_tokens_from_chars=max(total_input_characters // 4, 0),
        provider_usage=provider_usage,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_hit_tokens=cache_hit_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_type=cache_type,
        billing_type=billing_type,
        cache_metrics_source=cache_metrics_source,
    )


def summarize_operation_breakdown(llm_call_trace: list[dict[str, Any]] | None) -> list[AuthorTokenUsageBucket]:
    return _summarize_usage_buckets(
        llm_call_trace,
        bucket_resolver=lambda operation: operation,
    )


def summarize_stage_breakdown(llm_call_trace: list[dict[str, Any]] | None) -> list[AuthorTokenUsageBucket]:
    return _summarize_usage_buckets(
        llm_call_trace,
        bucket_resolver=_operation_stage,
    )


def estimate_token_cost(metrics: AuthorCacheMetrics) -> AuthorTokenCostEstimate | None:
    if metrics.input_tokens is None and metrics.output_tokens is None:
        return None
    settings = get_settings()
    input_tokens = int(metrics.input_tokens or 0)
    output_tokens = int(metrics.output_tokens or 0)
    cached_input_tokens = int(metrics.cached_input_tokens or 0)
    cache_creation_input_tokens = int(metrics.cache_creation_input_tokens or 0)
    uncached_input_tokens = max(input_tokens - cached_input_tokens - cache_creation_input_tokens, 0)
    input_rate = settings.responses_input_price_per_million_tokens_rmb / 1_000_000
    output_rate = settings.responses_output_price_per_million_tokens_rmb / 1_000_000
    estimated_input_cost = (
        (uncached_input_tokens * input_rate)
        + (cached_input_tokens * input_rate * settings.responses_session_cache_hit_multiplier)
        + (cache_creation_input_tokens * input_rate * settings.responses_session_cache_creation_multiplier)
    )
    estimated_output_cost = output_tokens * output_rate
    notes: str | None = None
    if metrics.cached_input_tokens is None and metrics.cache_creation_input_tokens is None:
        notes = "Provider cache breakdown unavailable; estimate treats all input tokens as uncached."
        uncached_input_tokens = input_tokens
        cached_input_tokens = 0
        cache_creation_input_tokens = 0
        estimated_input_cost = uncached_input_tokens * input_rate
    return AuthorTokenCostEstimate(
        model=settings.responses_model,
        currency="RMB",
        input_price_per_million_tokens_rmb=settings.responses_input_price_per_million_tokens_rmb,
        output_price_per_million_tokens_rmb=settings.responses_output_price_per_million_tokens_rmb,
        session_cache_hit_multiplier=settings.responses_session_cache_hit_multiplier,
        session_cache_creation_multiplier=settings.responses_session_cache_creation_multiplier,
        uncached_input_tokens=uncached_input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        output_tokens=output_tokens,
        estimated_input_cost_rmb=round(estimated_input_cost, 6),
        estimated_output_cost_rmb=round(estimated_output_cost, 6),
        estimated_total_cost_rmb=round(estimated_input_cost + estimated_output_cost, 6),
        notes=notes,
    )
