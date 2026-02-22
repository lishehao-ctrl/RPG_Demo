from __future__ import annotations

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _default_fake_llm_provider() -> None:
    """Keep tests deterministic unless a test explicitly overrides provider settings."""
    original_primary = settings.llm_provider_primary
    original_fallbacks = list(settings.llm_provider_fallbacks)

    settings.llm_provider_primary = "fake"
    settings.llm_provider_fallbacks = []
    try:
        yield
    finally:
        settings.llm_provider_primary = original_primary
        settings.llm_provider_fallbacks = original_fallbacks
