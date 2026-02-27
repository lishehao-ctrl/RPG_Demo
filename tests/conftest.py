from __future__ import annotations

import pytest

from app.config import settings
from app.db.base import Base
from app.db.models import ActionLog, Session, SessionStepIdempotency, Story, StoryVersion, User  # noqa: F401
from app.db.session import engine
from app.modules.telemetry.service import reset_runtime_telemetry


@pytest.fixture(autouse=True)
def _reset_db_and_defaults() -> None:
    settings.llm_api_key = ""
    settings.llm_base_url = "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    settings.llm_model = "qwen-flash-us"
    settings.story_narration_language = "English"
    settings.author_api_token = ""
    settings.player_api_token = ""
    reset_runtime_telemetry()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    reset_runtime_telemetry()
    Base.metadata.drop_all(bind=engine)
