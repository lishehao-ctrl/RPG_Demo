from __future__ import annotations

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _default_fake_llm_provider() -> None:
    """Keep tests deterministic by forcing test runtime mode."""
    original_env = settings.env
    settings.env = "test"
    try:
        yield
    finally:
        settings.env = original_env
