from rpg_backend.config.settings import get_settings
from rpg_backend.llm.base import LLMProvider, LLMProviderConfigError
from rpg_backend.llm.worker_client import WorkerClientError, get_worker_client
from rpg_backend.llm.worker_provider import WorkerProvider


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


def get_llm_provider() -> LLMProvider:
    settings = get_settings()

    route_model, narration_model = resolve_openai_models(
        settings.llm_openai_route_model,
        settings.llm_openai_narration_model,
        settings.llm_openai_model,
    )
    if not route_model and not narration_model:
        raise LLMProviderConfigError(
            "openai provider misconfigured; missing: "
            "one of APP_LLM_OPENAI_ROUTE_MODEL / APP_LLM_OPENAI_NARRATION_MODEL / APP_LLM_OPENAI_MODEL"
        )

    try:
        worker_client = get_worker_client()
    except WorkerClientError as exc:
        raise LLMProviderConfigError(f"llm worker misconfigured: {exc.error_code}: {exc.message}") from exc
    return WorkerProvider(
        worker_client=worker_client,
        route_model=route_model,
        narration_model=narration_model,
        timeout_seconds=settings.llm_openai_timeout_seconds,
        route_max_retries=settings.llm_openai_route_max_retries,
        narration_max_retries=settings.llm_openai_narration_max_retries,
        route_temperature=settings.llm_openai_temperature_route,
        narration_temperature=settings.llm_openai_temperature_narration,
    )
