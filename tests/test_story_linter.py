from __future__ import annotations

import json
from pathlib import Path

from rpg_backend.domain.linter import lint_story_pack


FIXTURE = Path("sample_data/story_pack_v1.json")


def test_story_pack_linter_accepts_sample() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = lint_story_pack(pack)
    assert report.ok, report.errors


def test_story_pack_linter_rejects_missing_fail_forward() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    move = next(item for item in pack["moves"] if item["id"] == "scan_signal")
    move["outcomes"] = [out for out in move["outcomes"] if out["result"] != "fail_forward"]

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("missing fail_forward" in err for err in report.errors)


def test_story_pack_linter_rejects_duplicate_beat_titles() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack["beats"][1]["title"] = pack["beats"][0]["title"]

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("duplicate beat titles" in err for err in report.errors)


def test_story_pack_linter_rejects_missing_strategy_triangle_style() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scene = pack["scenes"][0]
    scene["enabled_moves"] = ["scan_signal", "calm_crowd", "inspect_infrastructure", "global.look"]

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("missing strategy styles" in err for err in report.errors)


def test_story_pack_linter_rejects_banned_move_id() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack["moves"][0]["id"] = "inspect_relic"
    pack["scenes"][0]["enabled_moves"][0] = "inspect_relic"

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("banned move id: inspect_relic" in err for err in report.errors)


def test_story_pack_linter_rejects_missing_npc_profiles_schema_field() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack.pop("npc_profiles", None)

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("schema validation failed" in err for err in report.errors)


def test_story_pack_linter_rejects_missing_strategy_style_schema_field() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack["moves"][0].pop("strategy_style", None)

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("schema validation failed" in err for err in report.errors)


def test_story_pack_linter_rejects_missing_npc_conflict_tags_schema_field() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack["npc_profiles"][0].pop("conflict_tags", None)

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("schema validation failed" in err for err in report.errors)


def test_story_pack_linter_rejects_invalid_npc_conflict_tag_value() -> None:
    pack = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pack["npc_profiles"][0]["conflict_tags"] = ["unknown_tag"]

    report = lint_story_pack(pack)
    assert not report.ok
    assert any("schema validation failed" in err for err in report.errors)
