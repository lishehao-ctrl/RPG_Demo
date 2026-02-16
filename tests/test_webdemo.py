from fastapi.testclient import TestClient

from app.main import app


def test_demo_page_returns_html_title() -> None:
    client = TestClient(app)
    resp = client.get('/demo')
    assert resp.status_code == 200
    assert '<title>RPG Demo</title>' in resp.text
