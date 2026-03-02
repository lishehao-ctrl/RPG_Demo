from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "rpg-backend"
    app_env: str = "dev"
    debug: bool = False
    database_url: str = "sqlite:///./app.db"
    routing_confidence_threshold: float = 0.55
    llm_openai_base_url: str | None = None
    llm_openai_api_key: str | None = None
    llm_openai_model: str | None = None
    llm_openai_route_model: str | None = None
    llm_openai_narration_model: str | None = None
    llm_openai_generator_model: str | None = None
    llm_openai_timeout_seconds: float = Field(default=20.0, gt=0)
    llm_openai_route_max_retries: int = Field(default=3, ge=1, le=3)
    llm_openai_narration_max_retries: int = Field(default=1, ge=1, le=3)
    llm_openai_temperature_route: float = Field(default=0.1, ge=0.0, le=2.0)
    llm_openai_temperature_narration: float = Field(default=0.4, ge=0.0, le=2.0)
    llm_openai_generator_temperature: float = Field(default=0.15, ge=0.0, le=2.0)
    llm_openai_generator_max_retries: int = Field(default=3, ge=1, le=3)
    obs_log_level: str = "INFO"
    obs_request_id_header: str = "X-Request-ID"
    obs_redact_input_text: bool = True
    obs_alert_webhook_url: str | None = None
    obs_alert_window_seconds: int = Field(default=300, ge=60, le=3600)
    obs_alert_bucket_min_count: int = Field(default=3, ge=1)
    obs_alert_bucket_min_share: float = Field(default=0.10, ge=0.0, le=1.0)
    obs_alert_global_error_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    obs_alert_cooldown_seconds: int = Field(default=900, ge=60, le=86400)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
