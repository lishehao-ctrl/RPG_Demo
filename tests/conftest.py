from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from rpg_backend.api.route_paths import admin_auth_login_path
from rpg_backend.config.settings import get_settings
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
        settings = get_settings()
        login_response = test_client.post(
            admin_auth_login_path(),
            json={
                "email": settings.admin_bootstrap_email,
                "password": settings.admin_bootstrap_password,
            },
        )
        assert login_response.status_code == 200, login_response.text
        token = login_response.json()["access_token"]
        test_client.headers.update({"Authorization": f"Bearer {token}"})
        yield test_client


@pytest.fixture()
def anon_client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
