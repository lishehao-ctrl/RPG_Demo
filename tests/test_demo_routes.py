from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_demo_root_redirects_to_play() -> None:
    client = TestClient(app)
    response = client.get("/demo", follow_redirects=False)
    assert response.status_code in {302, 307}
    assert response.headers.get("location") == "/demo/play"


def test_demo_dev_and_play_pages_are_available() -> None:
    client = TestClient(app)

    dev = client.get("/demo/dev")
    play = client.get("/demo/play")

    assert dev.status_code == 200
    assert play.status_code == 200
    assert "text/html" in dev.headers.get("content-type", "")
    assert "text/html" in play.headers.get("content-type", "")

    html = play.text
    assert "id=\"storyMetaPill\"" in html
    assert "id=\"runSummaryPanel\"" in html
    assert "id=\"playPhase\"" not in html
    assert "id=\"sessionId\"" not in html
    assert "id=\"tokenTotals\"" not in html


def test_demo_bootstrap_has_required_fields() -> None:
    client = TestClient(app)
    response = client.get("/demo/bootstrap")
    assert response.status_code == 200

    payload = response.json()
    assert payload["default_story_id"] == settings.demo_default_story_id
    assert payload["default_story_version"] == settings.demo_default_story_version
    assert isinstance(payload["step_retry_max_attempts"], int)
    assert isinstance(payload["step_retry_backoff_ms"], int)
    assert payload["step_retry_max_attempts"] >= 1
    assert payload["step_retry_backoff_ms"] >= 1


def test_story_list_endpoint_is_available_for_play_picker() -> None:
    client = TestClient(app)
    response = client.get("/stories")
    assert response.status_code == 200
    payload = response.json()
    assert "stories" in payload
    assert isinstance(payload["stories"], list)
