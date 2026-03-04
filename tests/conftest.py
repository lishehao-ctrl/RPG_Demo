from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from rpg_backend.main import app
from rpg_backend.storage.engine import engine
from rpg_backend.storage.migrations import run_downgrade, run_upgrade


@pytest.fixture(autouse=True)
def reset_db() -> Generator[None, None, None]:
    # Keep tests on the same migration path as runtime; avoid create_all shortcuts.
    run_downgrade("base")
    run_upgrade("head")
    yield


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
