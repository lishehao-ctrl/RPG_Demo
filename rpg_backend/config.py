from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    responses_base_url: str | None = None
    responses_api_key: str | None = None
    responses_model: str | None = None
    responses_timeout_seconds: float = Field(default=20.0, gt=0)
    responses_use_session_cache: bool | None = None
    responses_session_cache_header: str = "x-dashscope-session-cache"
    responses_session_cache_value: str = "enable"
    responses_input_price_per_million_tokens_rmb: float = Field(default=0.2, ge=0)
    responses_output_price_per_million_tokens_rmb: float = Field(default=2.0, ge=0)
    responses_session_cache_hit_multiplier: float = Field(default=0.1, ge=0)
    responses_session_cache_creation_multiplier: float = Field(default=1.25, ge=0)
    responses_enable_thinking_play: bool = False
    responses_enable_thinking_author_overview: bool = False
    responses_enable_thinking_author_beat_plan: bool = False
    responses_enable_thinking_author_scene: bool = False
    responses_enable_thinking_author_rulepack: bool = False
    responses_enable_thinking_story_quality_judge: bool = False
    responses_max_output_tokens_play_interpret: int | None = Field(default=220, ge=1)
    responses_max_output_tokens_play_render: int | None = Field(default=420, ge=1)
    responses_max_output_tokens_author_overview: int | None = Field(default=800, ge=1)
    responses_max_output_tokens_author_beat_plan: int | None = Field(default=1500, ge=1)
    responses_max_output_tokens_author_scene: int | None = Field(default=1600, ge=1)
    responses_max_output_tokens_author_rulepack: int | None = Field(default=900, ge=1)
    responses_max_output_tokens_story_quality_judge: int | None = Field(default=700, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
