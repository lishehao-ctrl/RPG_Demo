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
    author = client.get("/demo/author")

    assert dev.status_code == 200
    assert play.status_code == 200
    assert author.status_code == 200
    assert "text/html" in dev.headers.get("content-type", "")
    assert "text/html" in play.headers.get("content-type", "")
    assert "text/html" in author.headers.get("content-type", "")

    html = play.text
    for marker in [
        'data-testid="play-shell"',
        'data-testid="play-story-select"',
        'data-testid="play-main"',
        'data-testid="play-stats-panel"',
        'data-testid="play-quest-panel"',
        'data-testid="play-run-panel"',
        'data-testid="play-impact-panel"',
        'data-testid="play-replay-drawer"',
        'data-testid="play-busy-indicator"',
        'data-testid="play-llm-ack"',
        'id="stepBusyHint"',
        'id="stepBusyText"',
        'id="stepBusyPhase"',
        'id="stepAck"',
        'id="lastImpactList"',
    ]:
        assert marker in html

    # Play page should not expose developer-only diagnostic fields.
    assert 'id="sessionId"' not in html
    assert 'id="tokenTotals"' not in html

    dev_html = dev.text
    for marker in [
        'data-testid="dev-shell"',
        'data-testid="dev-session-panel"',
        'data-testid="dev-pending-panel"',
        'data-testid="dev-llm-trace-panel"',
        'data-testid="dev-layer-inspector-panel"',
        'data-testid="dev-state-panel"',
        'data-testid="dev-timeline-panel"',
        'data-testid="dev-replay-panel"',
        'id="llmTraceMeta"',
        'id="llmTraceSummary"',
        'id="llmTraceCalls"',
        'id="refreshLlmTraceBtn"',
        'id="layerInspectorSummary"',
        'id="layerInspectorSteps"',
        'id="refreshLayerInspectorBtn"',
        "Free input usually triggers two model calls: selection, then narrative.",
    ]:
        assert marker in dev_html

    author_html = author.text
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
        'data-testid="author-step-advanced"',
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
        'id="authorStoryId"',
        'id="validateAuthorBtn"',
        'id="compileAuthorBtn"',
        'id="undoPatchBtn"',
        'id="saveDraftBtn"',
        'id="playtestBtn"',
        'id="compiledPreview"',
    ]:
        assert marker in author_html


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
