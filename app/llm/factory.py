from app.config.settings import get_settings
from app.llm.base import LLMProvider, LLMProviderConfigError
from app.llm.fake_provider import FakeProvider
from app.llm.openai_provider import OpenAIProvider


def resolve_openai_models(
    route_model: str | None,
    narration_model: str | None,
    model: str | None,
) -> tuple[str, str]:
    route = (route_model or "").strip()
    narration = (narration_model or "").strip()
    default = (model or "").strip()
    effective_route = route or narration or default
    effective_narration = narration or route or default
    return effective_route, effective_narration


def get_llm_provider(provider_override: str | None = None) -> LLMProvider:
    settings = get_settings()
    provider = (provider_override or settings.llm_provider).lower()

    if provider == "fake":
        return FakeProvider()
    if provider == "openai":
        missing: list[str] = []
        if not (settings.llm_openai_base_url or "").strip():
            missing.append("APP_LLM_OPENAI_BASE_URL")
        if not (settings.llm_openai_api_key or "").strip():
            missing.append("APP_LLM_OPENAI_API_KEY")
        route_model, narration_model = resolve_openai_models(
            settings.llm_openai_route_model,
            settings.llm_openai_narration_model,
            settings.llm_openai_model,
        )
        if not route_model and not narration_model:
            missing.append(
                "one of APP_LLM_OPENAI_ROUTE_MODEL / APP_LLM_OPENAI_NARRATION_MODEL / APP_LLM_OPENAI_MODEL"
            )
        if missing:
            joined = ", ".join(missing)
            raise LLMProviderConfigError(f"openai provider misconfigured; missing: {joined}")

        return OpenAIProvider(
            base_url=settings.llm_openai_base_url or "",
            api_key=settings.llm_openai_api_key or "",
            model=settings.llm_openai_model,
            route_model=route_model,
            narration_model=narration_model,
            timeout_seconds=settings.llm_openai_timeout_seconds,
            route_max_retries=settings.llm_openai_route_max_retries,
            narration_max_retries=settings.llm_openai_narration_max_retries,
            route_temperature=settings.llm_openai_temperature_route,
            narration_temperature=settings.llm_openai_temperature_narration,
        )

    raise LLMProviderConfigError(f"unsupported llm provider: {provider}")
