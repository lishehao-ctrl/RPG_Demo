from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "accept-all-rpg"
    app_env: str = "dev"
    debug: bool = False
    database_url: str = "sqlite:///./app.db"
    llm_provider: str = "fake"
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

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
