from fastapi.testclient import TestClient

from app.main import app


def test_demo_ui_smoke() -> None:
    client = TestClient(app)
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert "RPG Demo UI" in resp.text
