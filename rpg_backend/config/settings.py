from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "rpg-backend"
    app_env: str = "dev"
    debug: bool = False
    database_url: str = "postgresql://rpg_local:rpg_local@127.0.0.1:8132/rpg_dev"
    db_async_pool_size: int = Field(default=20, ge=1, le=500)
    db_async_max_overflow: int = Field(default=20, ge=0, le=1000)
    db_async_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    auth_jwt_secret: str = "dev-only-change-me"
    auth_jwt_expire_minutes: int = Field(default=480, ge=1, le=10080)
    auth_jwt_issuer: str = "rpg-backend"
    admin_bootstrap_email: str = "admin@example.com"
    admin_bootstrap_password: str = "admin123456"
    author_workflow_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    author_workflow_max_attempts: int = Field(default=3, ge=1, le=10)
    routing_confidence_threshold: float = 0.55
    responses_base_url: str | None = None
    responses_api_key: str | None = None
    responses_model: str | None = None
    responses_timeout_seconds: float = Field(default=20.0, gt=0)
    responses_enable_thinking_play: bool = False
    responses_enable_thinking_author_overview: bool = False
    responses_enable_thinking_author_beat: bool = True
    responses_enable_thinking_story_quality_judge: bool = False
    obs_log_level: str = "INFO"
    obs_request_id_header: str = "X-Request-ID"
    obs_redact_input_text: bool = True
    obs_alert_webhook_url: str | None = None
    obs_alert_window_seconds: int = Field(default=300, ge=60, le=3600)
    obs_alert_bucket_min_count: int = Field(default=3, ge=1)
    obs_alert_bucket_min_share: float = Field(default=0.10, ge=0.0, le=1.0)
    obs_alert_global_error_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    obs_alert_cooldown_seconds: int = Field(default=900, ge=60, le=86400)
    obs_alert_http_5xx_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    obs_alert_http_5xx_min_count: int = Field(default=10, ge=1)
    obs_alert_ready_fail_streak: int = Field(default=2, ge=1, le=50)
    obs_alert_responses_fail_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    obs_alert_responses_fail_min_count: int = Field(default=20, ge=1)
    obs_alert_llm_call_p95_ms: int = Field(default=3000, ge=1, le=120000)
    obs_alert_llm_call_min_count: int = Field(default=30, ge=1)
    ready_llm_probe_enabled: bool = True
    ready_llm_probe_cache_ttl_seconds: int = Field(default=30, ge=1, le=300)
    ready_llm_probe_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
