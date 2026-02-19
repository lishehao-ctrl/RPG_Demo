from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import typer

app = typer.Typer(help="RPG backend CLI")
session_app = typer.Typer(help="Session commands")
app.add_typer(session_app, name="session")

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
STATE_PATH = Path(__file__).resolve().parent / ".state.json"


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(data: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def backend_url() -> str:
    return os.getenv("BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")


def user_id() -> str:
    return os.getenv("X_USER_ID", DEFAULT_USER_ID)


def request(method: str, endpoint: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> httpx.Response:
    headers: dict[str, str] = {}
    auth_token = os.getenv("AUTH_TOKEN")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    else:
        headers["X-User-Id"] = user_id()
    url = f"{backend_url()}{endpoint}"
    with httpx.Client(timeout=20.0) as client:
        return client.request(method, url, json=json_body, params=params, headers=headers)


def _resolve_session_id(session_id: str | None) -> str:
    if session_id:
        return session_id
    sid = load_state().get("session_id")
    if not sid:
        raise typer.BadParameter("No session_id provided and no saved session in client/.state.json")
    return str(sid)


def _resolve_snapshot_id(snapshot_id: str | None) -> str:
    if snapshot_id:
        return snapshot_id
    spid = load_state().get("snapshot_id")
    if not spid:
        raise typer.BadParameter("No snapshot_id provided and no saved snapshot in client/.state.json")
    return str(spid)


def _handle_response(resp: httpx.Response, action: str) -> dict[str, Any] | None:
    if resp.status_code in (404, 501):
        typer.echo(f"{action}: endpoint unavailable or resource not found ({resp.status_code}).")
        try:
            typer.echo(resp.text)
        except Exception:
            pass
        return None
    if resp.status_code >= 400:
        typer.echo(f"{action} failed ({resp.status_code}): {resp.text}")
        raise typer.Exit(code=1)
    try:
        return resp.json()
    except Exception:
        typer.echo(resp.text)
        return None


def _print_step(body: dict[str, Any]) -> None:
    typer.echo(f"node_id: {body.get('node_id')}")
    typer.echo(f"narrative: {body.get('narrative_text')}")
    cost = body.get("cost", {})
    typer.echo(f"cost: provider={cost.get('provider')} in={cost.get('tokens_in')} out={cost.get('tokens_out')}")

    choices = body.get("choices", [])
    if choices:
        typer.echo("choices:")
        for c in choices:
            typer.echo(f"  - {c.get('id')}: {c.get('text')} ({c.get('type')})")


@app.command()
def ping() -> None:
    resp = request("GET", "/health")
    body = _handle_response(resp, "ping")
    if body is not None:
        typer.echo(f"ok: {body}")


@session_app.command("create")
def session_create(
    story_id: str = typer.Option(..., "--story-id", help="Published story id"),
    version: int | None = typer.Option(None, "--version", help="Optional story version"),
) -> None:
    payload: dict[str, Any] = {"story_id": story_id}
    if version is not None:
        payload["version"] = version
    resp = request("POST", "/sessions", json_body=payload)
    body = _handle_response(resp, "session create")
    if body is None:
        return
    state = load_state()
    state["session_id"] = body.get("id")
    save_state(state)
    typer.echo(f"session_id: {body.get('id')}")
    typer.echo(f"status: {body.get('status')}")


@session_app.command("get")
def session_get(session_id: str | None = typer.Argument(default=None)) -> None:
    sid = _resolve_session_id(session_id)
    resp = request("GET", f"/sessions/{sid}")
    body = _handle_response(resp, "session get")
    if body is None:
        return
    typer.echo(f"session_id: {body.get('id')}")
    typer.echo(f"status: {body.get('status')}")
    typer.echo(f"current_node_id: {body.get('current_node_id')}")


@app.command()
def step(
    text: str | None = typer.Option(default=None, help="Player input text"),
    choice_id: str | None = typer.Option(default=None, help="Choice id from previous response"),
    session_id: str | None = typer.Option(default=None, help="Override session id"),
) -> None:
    if not text and not choice_id:
        raise typer.BadParameter("Provide --text or --choice-id")
    if text and choice_id:
        raise typer.BadParameter("Provide exactly one of --text or --choice-id")
    sid = _resolve_session_id(session_id)
    payload: dict[str, Any] = {}
    if text:
        payload["player_input"] = text
    if choice_id:
        payload["choice_id"] = choice_id

    resp = request("POST", f"/sessions/{sid}/step", json_body=payload)
    body = _handle_response(resp, "step")
    if body is None:
        return

    _print_step(body)


@app.command()
def snapshot(
    name: str = typer.Option(default="manual", help="Snapshot name"),
    session_id: str | None = typer.Option(default=None),
) -> None:
    sid = _resolve_session_id(session_id)
    resp = request("POST", f"/sessions/{sid}/snapshot", params={"name": name})
    body = _handle_response(resp, "snapshot")
    if body is None:
        return
    spid = body.get("snapshot_id")
    state = load_state()
    state["snapshot_id"] = spid
    save_state(state)
    typer.echo(f"snapshot_id: {spid}")


@app.command()
def rollback(
    snapshot_id: str | None = typer.Option(default=None),
    session_id: str | None = typer.Option(default=None),
) -> None:
    sid = _resolve_session_id(session_id)
    spid = _resolve_snapshot_id(snapshot_id)
    resp = request("POST", f"/sessions/{sid}/rollback", params={"snapshot_id": spid})
    body = _handle_response(resp, "rollback")
    if body is not None:
        typer.echo(f"rolled back session_id={body.get('id')} current_node_id={body.get('current_node_id')}")


@app.command()
def end(session_id: str | None = typer.Option(default=None)) -> None:
    sid = _resolve_session_id(session_id)
    resp = request("POST", f"/sessions/{sid}/end")
    body = _handle_response(resp, "end")
    if body is not None:
        typer.echo(f"ended: {body.get('ended')} replay_report_id={body.get('replay_report_id')}")


@app.command()
def replay(session_id: str | None = typer.Option(default=None)) -> None:
    sid = _resolve_session_id(session_id)
    resp = request("GET", f"/sessions/{sid}/replay")
    body = _handle_response(resp, "replay")
    if body is None:
        return

    typer.echo(f"session_id: {body.get('session_id')}")
    typer.echo(f"total_steps: {body.get('total_steps')}")
    typer.echo(f"story_path: {len(body.get('story_path', []))}")
    typer.echo(f"key_decisions: {len(body.get('key_decisions', []))}")


if __name__ == "__main__":
    app()
