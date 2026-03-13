from __future__ import annotations

from dataclasses import dataclass

from rpg_backend.config.settings import get_settings
from rpg_backend.llm.agents import AuthorAgent, PlayAgent
from rpg_backend.llm.base import LLMProviderConfigError
from rpg_backend.llm.response_sessions import ResponseSessionStore
from rpg_backend.llm.responses_transport import ResponsesTransport


@dataclass(frozen=True)
class ResponsesAgentBundle:
    play_agent: PlayAgent
    author_agent: AuthorAgent
    model: str
    mode: str = "responses"


_cached_bundle: ResponsesAgentBundle | None = None
_cached_signature: tuple[str, str, str, float, bool, bool, bool] | None = None


def _settings_signature() -> tuple[str, str, str, float, bool, bool, bool]:
    settings = get_settings()
    return (
        (settings.responses_base_url or "").strip(),
        (settings.responses_api_key or "").strip(),
        (settings.responses_model or "").strip(),
        float(settings.responses_timeout_seconds),
        bool(settings.responses_enable_thinking_play),
        bool(settings.responses_enable_thinking_author_overview),
        bool(settings.responses_enable_thinking_author_beat),
    )


def _build_bundle() -> ResponsesAgentBundle:
    settings = get_settings()

    base_url = (settings.responses_base_url or "").strip()
    api_key = (settings.responses_api_key or "").strip()
    model = (settings.responses_model or "").strip()

    if not base_url:
        raise LLMProviderConfigError("responses provider misconfigured: APP_RESPONSES_BASE_URL is required")
    if not api_key:
        raise LLMProviderConfigError("responses provider misconfigured: APP_RESPONSES_API_KEY is required")
    if not model:
        raise LLMProviderConfigError("responses provider misconfigured: APP_RESPONSES_MODEL is required")

    timeout_seconds = float(settings.responses_timeout_seconds)
    play_enable_thinking = bool(settings.responses_enable_thinking_play)
    author_overview_enable_thinking = bool(settings.responses_enable_thinking_author_overview)
    author_beat_enable_thinking = bool(settings.responses_enable_thinking_author_beat)
    transport = ResponsesTransport(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    session_store = ResponseSessionStore()

    play_agent = PlayAgent(
        transport=transport,
        session_store=session_store,
        model=model,
        timeout_seconds=timeout_seconds,
        enable_thinking=play_enable_thinking,
    )
    author_agent = AuthorAgent(
        transport=transport,
        session_store=session_store,
        model=model,
        timeout_seconds=timeout_seconds,
        overview_enable_thinking=author_overview_enable_thinking,
        beat_enable_thinking=author_beat_enable_thinking,
    )

    return ResponsesAgentBundle(
        play_agent=play_agent,
        author_agent=author_agent,
        model=model,
    )


def get_responses_agent_bundle() -> ResponsesAgentBundle:
    global _cached_bundle, _cached_signature
    signature = _settings_signature()
    if _cached_bundle is None or _cached_signature != signature:
        _cached_bundle = _build_bundle()
        _cached_signature = signature
    return _cached_bundle


# Backward compatibility for callsites that still reference "provider".
def get_llm_provider() -> ResponsesAgentBundle:
    return get_responses_agent_bundle()


def get_play_agent() -> PlayAgent:
    return get_responses_agent_bundle().play_agent


def get_author_agent() -> AuthorAgent:
    return get_responses_agent_bundle().author_agent
