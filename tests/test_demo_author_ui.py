from fastapi.testclient import TestClient

from app.main import app


def test_demo_author_page_contains_workflow_controls() -> None:
    client = TestClient(app)
    response = client.get("/demo/author")
    assert response.status_code == 200
    html = response.text

    for marker in [
        'data-testid="author-shell"',
        'data-testid="author-tab-author"',
        'data-testid="author-tab-debug"',
        'data-testid="author-debug-toggle"',
        'data-testid="author-main-flow"',
        'data-testid="author-next-steps"',
        'data-testid="author-debug-panel"',
        'data-testid="author-stepper"',
        'data-testid="author-focus-core"',
        'data-testid="author-structure-collapse"',
        'data-testid="author-scene-advanced-toggle"',
        'data-testid="author-review-advanced-toggle"',
        'data-testid="author-entry-spark"',
        'data-testid="author-entry-ingest"',
        'data-testid="author-seed-input"',
        'data-testid="author-source-input"',
        'data-testid="author-auto-apply-hint"',
        'data-testid="author-step-world"',
        'data-testid="author-step-characters"',
        'data-testid="author-step-plot"',
        'data-testid="author-step-scenes"',
        'data-testid="author-step-action"',
        'data-testid="author-step-consequence"',
        'data-testid="author-step-ending"',
        'data-testid="author-step-review"',
        'data-testid="author-global-brief"',
        'data-testid="author-layer-intent-panel"',
        'data-testid="author-assist-panel"',
        'data-testid="author-writer-turn-feed"',
        'data-testid="author-turn-card"',
        'data-testid="author-playability-panel"',
        'data-testid="author-playability-blocking"',
        'data-testid="author-playability-metrics"',
        'data-testid="author-llm-feedback"',
        'data-testid="author-patch-preview"',
        'data-testid="author-form"',
        'data-testid="author-validate-panel"',
        'data-testid="author-compile-preview"',
        'data-testid="author-playtest-panel"',
        'id="assistBootstrapBtn"',
        'id="undoPatchBtn"',
        'id="validateAuthorBtn"',
        'id="compileAuthorBtn"',
        'id="saveDraftBtn"',
        'id="playtestBtn"',
        "/demo/static/author.js",
    ]:
        assert marker in html
