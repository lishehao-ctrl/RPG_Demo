from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "rpg-backend"
    app_env: str = "dev"
    debug: bool = False
    database_url: str = "sqlite:///./app.db"
    auth_jwt_secret: str = "dev-only-change-me"
    auth_jwt_expire_minutes: int = Field(default=480, ge=1, le=10080)
    auth_jwt_issuer: str = "rpg-backend"
    admin_bootstrap_email: str = "admin@example.com"
    admin_bootstrap_password: str = "admin123456"
    internal_worker_token: str = "dev-worker-token"
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
    generator_candidate_parallelism: int = Field(default=1, ge=1, le=8)
    llm_worker_base_url: str | None = None
    llm_worker_upstream_api_format: str = Field(default="chat_completions")
    llm_worker_model_limits_json: str = "{}"
    llm_worker_default_rpm: int = Field(default=300, ge=1)
    llm_worker_default_tpm: int = Field(default=600000, ge=1)
    llm_worker_queue_max_size: int = Field(default=1024, ge=1, le=500000)
    llm_worker_queue_wait_timeout_seconds: float = Field(default=8.0, gt=0, le=120)
    llm_worker_queue_weights_json: str = '{"route_intent":5,"render_narration":3,"json_object":2}'
    llm_worker_executor_concurrency: int = Field(default=16, ge=1, le=5000)
    llm_worker_token_est_route_output: int = Field(default=96, ge=1, le=4000)
    llm_worker_token_est_narration_output: int = Field(default=192, ge=1, le=8000)
    llm_worker_token_est_json_output: int = Field(default=256, ge=1, le=8000)
    llm_worker_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_worker_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    llm_worker_max_connections: int = Field(default=100, ge=1, le=2000)
    llm_worker_max_keepalive_connections: int = Field(default=20, ge=0, le=500)
    llm_worker_http2_enabled: bool = False
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
    obs_alert_worker_fail_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    obs_alert_worker_fail_min_count: int = Field(default=20, ge=1)
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
