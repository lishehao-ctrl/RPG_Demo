from __future__ import annotations

import asyncio
from types import SimpleNamespace

from rpg_backend.llm.response_sessions import ResponseSessionCursorValue, ResponseSessionStore


def test_call_with_cursor_clears_invalid_cursor_and_retries_once(monkeypatch) -> None:  # noqa: ANN001
    store = ResponseSessionStore()
    set_calls: list[str] = []
    clear_calls: list[tuple[str, str, str]] = []
    invoke_calls: list[str | None] = []

    async def _fake_get_cursor(**kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return ResponseSessionCursorValue(previous_response_id="resp_old", model="qwen-plus")

    async def _fake_clear_cursor(**kwargs):  # noqa: ANN003, ANN201
        clear_calls.append((kwargs["scope_type"], kwargs["scope_id"], kwargs["channel"]))

    async def _fake_set_cursor(**kwargs):  # noqa: ANN003, ANN201
        set_calls.append(kwargs["response_id"])

    async def _invoke(previous_response_id: str | None):  # noqa: ANN202
        invoke_calls.append(previous_response_id)
        if previous_response_id is not None:
            raise RuntimeError("previous_response_id expired")
        return SimpleNamespace(response_id="resp_new")

    monkeypatch.setattr(store, "get_cursor", _fake_get_cursor)
    monkeypatch.setattr(store, "clear_cursor", _fake_clear_cursor)
    monkeypatch.setattr(store, "set_cursor", _fake_set_cursor)

    result = asyncio.run(
        store.call_with_cursor(
            scope_type="play_session",
            scope_id="session-1",
            channel="play_agent",
            model="qwen-plus",
            invoke=_invoke,
        )
    )

    assert result.response_id == "resp_new"
    assert invoke_calls == ["resp_old", None]
    assert clear_calls == [("play_session", "session-1", "play_agent")]
    assert set_calls == ["resp_new"]


def test_call_with_cursor_fails_after_single_fallback(monkeypatch) -> None:  # noqa: ANN001
    store = ResponseSessionStore()
    invoke_calls: list[str | None] = []

    async def _fake_get_cursor(**kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return ResponseSessionCursorValue(previous_response_id="resp_old", model="qwen-plus")

    async def _invoke(previous_response_id: str | None):  # noqa: ANN202
        invoke_calls.append(previous_response_id)
        raise RuntimeError("previous_response_id expired")

    async def _fake_clear_cursor(**kwargs):  # noqa: ANN003, ANN201
        del kwargs

    monkeypatch.setattr(store, "get_cursor", _fake_get_cursor)
    monkeypatch.setattr(store, "clear_cursor", _fake_clear_cursor)

    try:
        asyncio.run(
            store.call_with_cursor(
                scope_type="play_session",
                scope_id="session-1",
                channel="play_agent",
                model="qwen-plus",
                invoke=_invoke,
            )
        )
    except RuntimeError as exc:
        assert "expired" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")

    assert invoke_calls == ["resp_old", None]


def test_call_with_cursor_ignores_stale_cursor_when_model_mismatched(monkeypatch) -> None:  # noqa: ANN001
    store = ResponseSessionStore()
    invoke_calls: list[str | None] = []
    clear_calls: list[tuple[str, str, str]] = []

    async def _fake_get_cursor(**kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return ResponseSessionCursorValue(previous_response_id="resp_old", model="qwen-old")

    async def _fake_clear_cursor(**kwargs):  # noqa: ANN003, ANN201
        clear_calls.append((kwargs["scope_type"], kwargs["scope_id"], kwargs["channel"]))

    async def _invoke(previous_response_id: str | None):  # noqa: ANN202
        invoke_calls.append(previous_response_id)
        return SimpleNamespace(response_id="resp_new")

    async def _fake_set_cursor(**kwargs):  # noqa: ANN003, ANN201
        del kwargs

    monkeypatch.setattr(store, "get_cursor", _fake_get_cursor)
    monkeypatch.setattr(store, "clear_cursor", _fake_clear_cursor)
    monkeypatch.setattr(store, "set_cursor", _fake_set_cursor)

    result = asyncio.run(
        store.call_with_cursor(
            scope_type="play_session",
            scope_id="session-2",
            channel="play_agent",
            model="qwen-plus",
            invoke=_invoke,
        )
    )

    assert result.response_id == "resp_new"
    assert invoke_calls == [None]
    assert clear_calls == [("play_session", "session-2", "play_agent")]
