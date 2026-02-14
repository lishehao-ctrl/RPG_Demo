from pathlib import Path

from rpg_cli import load_state, save_state


def test_load_state_missing_file_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / ".state.json"
    assert load_state(p) == {}


def test_save_and_load_state_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / ".state.json"
    payload = {"session_id": "s1", "snapshot_id": "sp1"}
    save_state(payload, p)
    assert load_state(p) == payload


def test_load_state_invalid_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / ".state.json"
    p.write_text("not-json")
    assert load_state(p) == {}
