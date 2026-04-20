from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from rpg_backend.author.contracts import AuthorPreviewResponse
from rpg_backend.author.preview import build_author_story_summary
from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.product_adapters import (
    author_preview_from_blueprint,
    author_story_summary_from_package,
    package_from_pipeline,
)
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.library.service import LibraryServiceError, StoryLibraryService
from rpg_backend.library.storage import SQLiteStoryLibraryStorage
from rpg_backend.play.contracts import PlayTurnRequest
from rpg_backend.play.contracts import PlayDraftIntentRequest
from rpg_backend.play.compiler import compile_play_plan
from rpg_backend.play.gateway import PlayGatewayError
import rpg_backend.play.service as play_service_module
from rpg_backend.play.service import PlayServiceError, PlaySessionService
from rpg_backend.play.session_handlers import LegacyPlaySessionHandler, V2PlaySessionHandler
from rpg_backend.play_v2.contracts import UrbanWorldState
from rpg_backend.config import Settings
from tests.author_fixtures import author_fixture_bundle


def _legacy_preview_response() -> AuthorPreviewResponse:
    fixture = author_fixture_bundle()
    bundle = fixture.design_bundle
    return AuthorPreviewResponse.model_validate(
        {
            "preview_id": "preview-play-legacy-1",
            "prompt_seed": "An envoy tries to hold an archive city together.",
            "focused_brief": fixture.focused_brief.model_dump(mode="json"),
            "theme": {
                "primary_theme": "legitimacy_crisis",
                "modifiers": ["succession", "blackout"],
                "router_reason": "test_fixture",
            },
            "strategies": {
                "story_frame_strategy": "legitimacy_story",
                "cast_strategy": "legitimacy_cast",
                "beat_plan_strategy": "single_semantic_compile",
            },
            "structure": {
                "cast_topology": "three_slot",
                "expected_npc_count": len(bundle.story_bible.cast),
                "expected_beat_count": len(bundle.beat_spine),
            },
            "story": {
                "title": bundle.story_bible.title,
                "premise": bundle.story_bible.premise,
                "tone": bundle.story_bible.tone,
                "stakes": bundle.story_bible.stakes,
            },
            "cast_slots": [
                {"slot_label": member.name, "public_role": member.role}
                for member in bundle.story_bible.cast
            ],
            "beats": [
                {
                    "title": beat.title,
                    "goal": beat.goal,
                    "milestone_kind": beat.milestone_kind,
                }
                for beat in bundle.beat_spine
            ],
            "flashcards": [],
            "stage": "brief_parsed",
        }
    )


def _publish_v2_story(
    tmp_path,
    *,
    seed: str = "董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。想要一个12到15分钟的职场修罗场。",
):
    preview_blueprint, _ = run_preview_blueprint_graph(seed, live_mode="deterministic")
    accepted = apply_blueprint_edits(preview_blueprint)
    pipeline = run_author_play_graph(accepted, live_mode="deterministic")
    package = package_from_pipeline(
        preview_blueprint=preview_blueprint,
        accepted_blueprint=accepted,
        pipeline=pipeline,
    )
    library_service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories_v2.sqlite3")))
    story = library_service.publish_story(
        owner_user_id="local-dev",
        source_job_id="job-play-v2-1",
        prompt_seed=seed,
        summary=author_story_summary_from_package(package),
        preview=author_preview_from_blueprint(
            preview_blueprint,
            bound_cast=package.urban_bundle.bound_cast,
            arc_template_id=package.urban_bundle.arc_template_id,
        ),
        bundle=package,
        visibility="public",
    )
    return library_service, story


def _publish_story(tmp_path):
    return _publish_v2_story(tmp_path)


def _no_gateway(_settings=None):
    raise PlayGatewayError(code="play_llm_config_missing", message="disabled_for_test", status_code=500)


def test_story_library_rejects_legacy_bundle_publish(tmp_path) -> None:
    fixture = author_fixture_bundle()
    bundle = fixture.design_bundle
    service = StoryLibraryService(SQLiteStoryLibraryStorage(str(tmp_path / "stories.sqlite3")))
    summary = build_author_story_summary(bundle, primary_theme="legitimacy_crisis")
    with pytest.raises(LibraryServiceError) as exc_info:
        service.publish_story(
            owner_user_id="local-dev",
            source_job_id="legacy-job-1",
            prompt_seed="legacy seed",
            summary=summary,
            preview=_legacy_preview_response(),
            bundle=bundle,
            visibility="public",
        )
    assert exc_info.value.code == "story_package_unsupported"


def test_play_service_create_session_for_v2_story_and_submit_turn(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    snapshot = service.create_session(story.story_id)
    assert snapshot.status == "active"
    assert snapshot.story_shell_id
    assert snapshot.story_actions
    assert snapshot.control_actions
    assert snapshot.latent_radar
    selected = snapshot.story_actions[0]
    next_snapshot = service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(input_text=selected.prompt),
    )
    assert next_snapshot.turn_index == 1
    assert next_snapshot.narration
    assert next_snapshot.feedback is not None
    trace = service.get_turn_traces(snapshot.session_id)[-1]
    assert trace.submission_input_mode == "free_input"


def test_play_service_submit_turn_refreshes_session_expiry(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    clock = {"now": datetime(2026, 4, 7, 10, 0, tzinfo=timezone.utc)}

    def _now() -> datetime:
        return clock["now"]

    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
        settings=Settings(play_session_ttl_seconds=60),
        now_provider=_now,
    )
    snapshot = service.create_session(story.story_id)
    with service._session_lock_for(snapshot.session_id):
        initial_expires_at = service._get_record(snapshot.session_id).expires_at
    clock["now"] = clock["now"] + timedelta(seconds=50)
    _ = service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(input_text=snapshot.story_actions[0].prompt),
    )
    with service._session_lock_for(snapshot.session_id):
        refreshed_expires_at = service._get_record(snapshot.session_id).expires_at
    assert refreshed_expires_at > initial_expires_at
    assert refreshed_expires_at == clock["now"] + timedelta(seconds=60)


def test_play_service_draft_intent_reuse_on_submit_turn(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    snapshot = service.create_session(story.story_id)
    draft = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="我先稳住她，再慢慢追问。", is_final_draft=True),
    )
    assert draft.draft_intent_id
    assert draft.turn_index == 0

    _ = service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(
            input_text="我先稳住她，再慢慢追问。",
            draft_intent_id=draft.draft_intent_id,
        ),
    )
    trace = service.get_turn_traces(snapshot.session_id)[-1]
    usage = dict(trace.interpret_usage or {})
    assert usage.get("draft_intent_status") == "reused"
    assert int(usage.get("draft_call_count") or 0) >= 1


def test_play_service_draft_intent_uses_gateway_only_for_final_fragment(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    sentinel_gateway = object()
    observed_gateways: list[object | None] = []
    original_run_intent_stage = play_service_module.run_v2_intent_stage

    def _capture_run_intent_stage(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        observed_gateways.append(kwargs.get("gateway"))
        # Keep the stage deterministic in test by forcing heuristic path.
        kwargs["gateway"] = None
        return original_run_intent_stage(*args, **kwargs)

    monkeypatch.setattr(service, "_resolve_gateway", lambda: sentinel_gateway)
    monkeypatch.setattr(play_service_module, "run_v2_intent_stage", _capture_run_intent_stage)
    snapshot = service.create_session(story.story_id)

    _ = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="我先稳住局面，别让她当场破防。", is_final_draft=False),
    )
    _ = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="我先稳住局面，别让她当场破防。", is_final_draft=True),
    )

    assert observed_gateways[0] is None
    assert observed_gateways[1] is sentinel_gateway


def test_play_service_draft_intent_compose_prewarm_forced_disabled_even_if_setting_enabled(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
        settings=Settings(play_v2_spec_compose_prewarm_enabled=True),
    )
    snapshot = service.create_session(story.story_id)
    draft = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="我先稳住她，再慢慢追问。", is_final_draft=True),
    )
    _ = service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(
            input_text="我先稳住她，再慢慢追问。",
            draft_intent_id=draft.draft_intent_id,
        ),
    )
    trace = service.get_turn_traces(snapshot.session_id)[-1]
    usage = dict(trace.interpret_usage or {})
    assert usage.get("compose_prewarm_status") == "disabled"
    assert int(usage.get("compose_prewarm_hit") or 0) == 0
    assert int(usage.get("compose_prewarm_total_tokens") or 0) == 0
    assert int(usage.get("typing_phase_prewarm_tokens") or 0) == 0
    assert int(usage.get("submit_phase_tokens") or 0) >= 0
    assert int(usage.get("post_submit_llm_calls") or 0) >= 0


def test_play_service_spec_compose_backpressure_skips_schedule(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    snapshot = service.create_session(story.story_id)
    with service._session_lock_for(snapshot.session_id):
        record = service._get_record(snapshot.session_id)
        assert isinstance(record.plan, CompiledPlayPlan)
        assert isinstance(record.state, UrbanWorldState)
        monkeypatch.setattr(service, "_spec_compose_backpressure_active", lambda: True)
        service._schedule_spec_compose_job(
            session_id=snapshot.session_id,
            turn_index=int(record.state.turn_index),
            state_snapshot_id=service._state_snapshot_id(record.state),
            normalized_text_hash=service._normalized_text_hash("我要当众翻牌让所有人站队"),
            source="typing_phase:draft_intent",
            plan=record.plan,
            state=record.state,
            input_text="我要当众翻牌让所有人站队",
            selected_suggestion_id=None,
            selected_story_action_id=None,
            selected_control_action_id=None,
            control_action="none",
            control_target_kind=None,
            control_target_id=None,
            control_target_mode=None,
            precomputed_intent=None,
            precomputed_micro_sim=None,
            precomputed_intent_diagnostics=None,
            prefetched_suggestions=tuple(record.state.story_actions),
            prefetched_control_actions=tuple(record.state.control_actions),
            latest_wins_scope="typing_phase",
        )
        assert service._spec_compose_futures == {}


def test_play_service_spec_compose_disabled_by_default(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    scheduled: list[dict[str, object]] = []

    def _capture_schedule(**kwargs):  # noqa: ANN003, ANN202
        scheduled.append(dict(kwargs))

    monkeypatch.setattr(service, "_schedule_spec_compose_job", _capture_schedule)
    monkeypatch.setattr(
        service,
        "_should_schedule_typing_phase_prewarm",
        lambda **kwargs: True,  # noqa: ARG005
    )
    snapshot = service.create_session(story.story_id)
    draft = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="我先稳住她，再慢慢追问。", is_final_draft=True),
    )
    assert scheduled == []

    _ = service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(
            input_text="我先稳住她，再慢慢追问。",
            draft_intent_id=draft.draft_intent_id,
        ),
    )
    trace = service.get_turn_traces(snapshot.session_id)[-1]
    usage = dict(trace.interpret_usage or {})
    assert usage.get("compose_prewarm_status") == "disabled"


def test_play_service_non_final_draft_does_not_schedule_compose_prewarm(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    scheduled: list[dict[str, object]] = []

    def _capture_schedule(**kwargs):  # noqa: ANN003, ANN202
        scheduled.append(dict(kwargs))

    monkeypatch.setattr(service, "_schedule_spec_compose_job", _capture_schedule)
    monkeypatch.setattr(
        service,
        "_should_schedule_typing_phase_prewarm",
        lambda **kwargs: True,  # noqa: ARG005
    )
    snapshot = service.create_session(story.story_id)
    draft = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="我会先稳住场面，再慢慢挑破。", is_final_draft=False),
    )
    assert scheduled == []
    assert bool(draft.diagnostics.get("typing_final_draft_seen")) is False


def test_play_service_draft_intent_records_scope_cleared_count(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    monkeypatch.setattr(service, "_clear_typing_phase_spec_compose_scope", lambda **kwargs: 2)  # noqa: ARG005
    snapshot = service.create_session(story.story_id)
    draft = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="先稳住，再逼他给证据。", is_final_draft=True),
    )
    assert bool(draft.diagnostics.get("typing_final_draft_seen")) is True
    assert int(draft.diagnostics.get("typing_scope_cleared_count") or 0) == 2


def test_play_service_submit_ignores_stale_fragment_when_prewarm_forced_disabled(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
        settings=Settings(play_v2_spec_compose_prewarm_enabled=True),
    )
    snapshot = service.create_session(story.story_id)
    with service._session_lock_for(snapshot.session_id):
        record = service._get_record(snapshot.session_id)
        assert isinstance(record.state, UrbanWorldState)
        state_snapshot_id = service._state_snapshot_id(record.state)
        stale_key = play_service_module._SpecComposeCacheKey(
            session_id=snapshot.session_id,
            turn_index=int(record.state.turn_index),
            state_snapshot_id=state_snapshot_id,
            normalized_text_hash=service._normalized_text_hash("旧片段草稿"),
        )
        service._spec_compose_cache[stale_key] = play_service_module._SpecComposeResult(
            key=stale_key,
            source="typing_phase:draft_intent",
            narration="旧片段",
            diagnostics={},
            compose_input_tokens=1,
            compose_output_tokens=1,
            compose_total_tokens=2,
            expires_at=service._now() + timedelta(seconds=30),
        )
    service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(input_text="新输入会导致旧草稿哈希失效"),
    )
    trace = service.get_turn_traces(snapshot.session_id)[-1]
    usage = dict(trace.interpret_usage or {})
    assert usage.get("compose_prewarm_status") == "disabled"
    assert int(usage.get("compose_prewarm_stale_fragment_count") or 0) == 0


def test_play_service_submit_pending_wait_split_by_input_mode(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    monkeypatch.setattr(service, "_spec_compose_backpressure_active", lambda: False)
    free_input_wait = service._submit_spec_compose_pending_wait_seconds(has_selected_ids=False)
    select_id_wait_idle = service._submit_spec_compose_pending_wait_seconds(has_selected_ids=True)
    assert 0.0 < free_input_wait <= 0.02
    assert 0.1 <= select_id_wait_idle <= 0.2
    monkeypatch.setattr(service, "_spec_compose_backpressure_active", lambda: True)
    select_id_wait_busy = service._submit_spec_compose_pending_wait_seconds(has_selected_ids=True)
    assert 0.09 <= select_id_wait_busy <= 0.12


def test_play_service_read_phase_prewarm_uses_top1_only(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
        settings=Settings(play_v2_spec_compose_prewarm_enabled=True),
    )
    captured: list[dict[str, object]] = []

    def _capture_schedule(**kwargs):  # noqa: ANN003, ANN202
        captured.append(dict(kwargs))

    monkeypatch.setattr(service, "_schedule_spec_compose_job", _capture_schedule)
    monkeypatch.setattr(
        service,
        "_should_schedule_read_phase_prewarm",
        lambda **kwargs: True,  # noqa: ARG005
    )
    snapshot = service.create_session(story.story_id)
    service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(input_text=snapshot.story_actions[0].prompt),
    )
    read_phase_calls = [item for item in captured if str(item.get("source", "")).startswith("read_phase:")]
    assert read_phase_calls == []


def test_play_service_read_phase_prewarm_requires_previous_select_id(tmp_path, monkeypatch) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
        settings=Settings(play_v2_spec_compose_prewarm_enabled=True),
    )
    captured: list[dict[str, object]] = []

    def _capture_schedule(**kwargs):  # noqa: ANN003, ANN202
        captured.append(dict(kwargs))

    monkeypatch.setattr(service, "_schedule_spec_compose_job", _capture_schedule)
    monkeypatch.setattr(
        service,
        "_should_schedule_read_phase_prewarm",
        lambda **kwargs: bool(kwargs.get("previous_turn_select_id")),  # noqa: ARG005
    )
    snapshot = service.create_session(story.story_id)
    service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(input_text=snapshot.story_actions[0].prompt),
    )
    assert [item for item in captured if str(item.get("source", "")).startswith("read_phase:")] == []

    snapshot2 = service.create_session(story.story_id)
    first_action = snapshot2.story_actions[0]
    service.submit_turn(
        snapshot2.session_id,
        PlayTurnRequest(
            input_text=first_action.prompt,
            selected_suggestion_id=first_action.suggestion_id,
            selected_story_action_id=first_action.suggestion_id,
        ),
    )
    read_phase_calls = [item for item in captured if str(item.get("source", "")).startswith("read_phase:")]
    assert read_phase_calls == []


def test_play_service_draft_intent_rejects_mismatch_and_falls_back(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    snapshot = service.create_session(story.story_id)
    draft = service.draft_intent(
        snapshot.session_id,
        PlayDraftIntentRequest(input_text="我先稳住她。"),
    )

    _ = service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(
            input_text="我要当众翻牌。",
            draft_intent_id=draft.draft_intent_id,
        ),
    )
    trace = service.get_turn_traces(snapshot.session_id)[-1]
    usage = dict(trace.interpret_usage or {})
    assert usage.get("draft_intent_status") in {"text_mismatch", "turn_index_mismatch", "state_snapshot_mismatch"}


def test_play_service_can_progress_with_suggested_story_actions(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    snapshot = service.create_session(story.story_id)
    guard = 0
    while snapshot.status == "active" and guard < 20:
        selected = snapshot.story_actions[0]
        snapshot = service.submit_turn(
            snapshot.session_id,
            PlayTurnRequest(input_text=selected.prompt),
        )
        guard += 1
    assert guard >= 1
    assert snapshot.turn_index >= 1
    assert snapshot.status in {"active", "completed"}


def test_play_service_uses_input_text_even_when_selected_suggestion_id_is_mismatched(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    snapshot = service.create_session(story.story_id)
    assert snapshot.story_actions
    assert snapshot.relationship_state is not None
    target_name = snapshot.relationship_state.targets[0].name
    mismatched = snapshot.story_actions[0]

    service.submit_turn(
        snapshot.session_id,
        PlayTurnRequest(
            input_text=f"我现在就要当众曝光{target_name}手里的录音，不再给台阶。",
            selected_suggestion_id=mismatched.suggestion_id,
            selected_story_action_id=mismatched.suggestion_id,
        ),
    )

    trace = service.get_turn_traces(snapshot.session_id)[-1]
    assert trace.selected_suggestion_id == mismatched.suggestion_id
    assert trace.selected_story_action_id is None or isinstance(trace.selected_story_action_id, str)
    assert trace.submission_input_mode == "select_id"
    assert trace.move_family in {"public_reveal", "comfort", "ally_with", "deflect", "probe_secret", "accuse", "flirt", "private_confession", "betray", "jealousy_trigger"}
    assert trace.deviation_type in {"none", "scope_shift", "target_shift", "move_downgrade"}


def test_play_service_create_session_rejects_non_v2_package_version() -> None:
    class _LegacyLibraryService:
        def get_story_record(self, story_id: str, *, actor_user_id: str | None = None):  # noqa: ANN001
            del story_id, actor_user_id
            return SimpleNamespace(package_version="legacy_design_bundle", bundle=None)

    service = PlaySessionService(
        story_library_service=_LegacyLibraryService(),  # type: ignore[arg-type]
        gateway_factory=_no_gateway,
    )
    with pytest.raises(PlayServiceError) as exc_info:
        service.create_session("legacy-story-1")
    assert exc_info.value.code == "play_story_package_unsupported"


def test_play_service_enforces_session_owner_scope(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    snapshot = service.create_session(story.story_id, actor_user_id="owner-a")
    with pytest.raises(PlayServiceError) as exc_info:
        service.get_session(snapshot.session_id, actor_user_id="owner-b")
    assert exc_info.value.code == "play_session_not_found"


def test_play_service_routes_runtime_handlers_by_session_kind(tmp_path) -> None:
    library_service, story = _publish_v2_story(tmp_path)
    service = PlaySessionService(
        story_library_service=library_service,
        gateway_factory=_no_gateway,
    )
    v2_snapshot = service.create_session(story.story_id)
    with service._session_lock_for(v2_snapshot.session_id):
        v2_record = service._get_record(v2_snapshot.session_id)
        v2_handler = service._resolve_turn_handler(v2_record)
    assert isinstance(v2_handler, V2PlaySessionHandler)

    fixture = author_fixture_bundle()
    legacy_plan = compile_play_plan(story_id="legacy_story_for_handler_split", bundle=fixture.design_bundle)
    legacy_snapshot = service.create_session_from_plan(legacy_plan)
    with service._session_lock_for(legacy_snapshot.session_id):
        legacy_record = service._get_record(legacy_snapshot.session_id)
        legacy_handler = service._resolve_turn_handler(legacy_record)
    assert isinstance(legacy_handler, LegacyPlaySessionHandler)
