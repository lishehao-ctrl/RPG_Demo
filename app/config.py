from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "rpg_demo"
    env: str = "dev"

    database_url: str = "sqlite:///./app.db"

    # LLM boundary (minimal env surface)
    llm_base_url: str = "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-flash-us"
    llm_api_key: str = ""

    # Runtime input policy
    story_input_max_chars: int = 512
    story_mapping_confidence_high: float = 0.65
    story_mapping_confidence_low: float = 0.45
    story_fallback_guard_default_max_consecutive: int = 3
    story_narration_language: str = "English"

    # Lightweight user bootstrap
    default_user_external_ref: str = "demo_user"
    default_user_display_name: str = "Demo User"

    # Optional API token guards. Empty means guard disabled for compatibility.
    author_api_token: str = ""
    player_api_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
