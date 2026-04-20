from __future__ import annotations

from rpg_backend.author.compiler.bundle import build_design_bundle
from rpg_backend.author.preview import build_author_preview_from_seed
from rpg_backend.author.seed_normalization import normalize_seed_packet
from rpg_backend.play.compiler import compile_play_plan
from tests.author_fixtures import author_fixture_bundle


def test_normalize_seed_packet_maps_wealth_family_prompt_to_supported_shell() -> None:
    packet = normalize_seed_packet("豪门订婚宴上，遗嘱突然公开，前任也在同一晚回来了。")

    assert packet.accepted_shell == "wealth_families"
    assert packet.fit_mode in {"direct_fit", "soft_fit"}
    assert packet.relationship_hook
    assert packet.secret_hook
    assert packet.surface_signal_summary
    assert "联姻" in packet.relationship_hook or "继承" in packet.relationship_hook


def test_author_preview_from_seed_exposes_normalized_shell_metadata() -> None:
    preview = build_author_preview_from_seed("娱乐圈顶流的偷拍视频流出后，前任和经纪人都开始逼她站队。")

    assert preview.normalized_seed is not None
    assert preview.normalized_seed.accepted_shell == "entertainment_scandal"
    assert preview.story_shell_id == "entertainment_scandal"
    assert preview.story.route_fantasy is not None


def test_compile_play_plan_promotes_normalized_bundle_to_relationship_drama() -> None:
    fixture = author_fixture_bundle()
    packet = normalize_seed_packet("豪门订婚宴上，遗嘱突然公开，前任也在同一晚回来了。")
    bundle = build_design_bundle(
        fixture.story_frame,
        fixture.cast_draft,
        fixture.beat_plan,
        fixture.focused_brief,
        normalized_seed=packet,
    )

    plan = compile_play_plan(story_id="story-relationship-shell", bundle=bundle)

    assert plan.story_mode == "relationship_drama"
    assert plan.story_shell_id == "wealth_families"
    assert plan.relationship_hook == packet.relationship_hook
    assert plan.secret_hook == packet.secret_hook
    assert plan.route_target_ids
    assert {item.ending_id for item in plan.endings} == {"route_lock", "bittersweet", "breakdown", "open_loop"}
