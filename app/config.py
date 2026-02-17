from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "rpg_demo"
    env: str = "dev"
    database_url: str = "sqlite+pysqlite:///./app.db"
    session_token_budget_total: int = 12000
    redis_url: str = "redis://localhost:6379/0"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/auth/google/callback"
    google_oauth_scopes: str = "openid email profile"

    jwt_secret: str = "change-me-in-prod"
    jwt_exp_minutes: int = 60 * 24

    llm_provider_primary: str = "fake"
    llm_provider_fallbacks: list[str] = Field(default_factory=list)
    llm_model_classify: str = "fake-classify-v1"
    llm_model_generate: str = "fake-generate-v1"
    llm_model_summarize: str = "fake-summarize-v1"
    llm_timeout_s: float = 8.0
    llm_max_retries: int = 2

    llm_preflight_classify_max_tokens: int = 128
    llm_preflight_generate_prompt_max_tokens: int = 1024
    llm_preflight_generate_completion_max_tokens: int = 512

    llm_doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    llm_doubao_api_key: str = ""

    llm_price_table: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "fake": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "doubao": {"input_per_1k": 0.008, "output_per_1k": 0.02},
            "default": {"input_per_1k": 0.0, "output_per_1k": 0.0},
        }
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
