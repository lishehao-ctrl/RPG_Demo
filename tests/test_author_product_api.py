from __future__ import annotations

import re

from fastapi.testclient import TestClient

from rpg_backend.author.jobs import AuthorJobService
from rpg_backend.author_v2.product_jobs import ProductAuthorJobService
from rpg_backend.author.contracts import (
    AuthorCacheMetrics,
    AuthorJobProgress,
    AuthorJobProgressSnapshot,
    AuthorJobResultResponse,
    AuthorJobStatusResponse,
    AuthorLoadingCard,
    AuthorPreviewFlashcard,
    AuthorPreviewResponse,
)
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.config import get_settings
from rpg_backend.main import app
from tests.author_fixtures import FakeGateway
from tests.auth_helpers import ensure_authenticated_client


class _FakeAuthorJobService:
    def create_preview(self, payload, *, actor_user_id=None):  # noqa: ANN001
        del actor_user_id
        return _preview_response(payload.prompt_seed)

    def create_job(self, payload, *, actor_user_id=None):  # noqa: ANN001
        del actor_user_id
        return AuthorJobStatusResponse(
            job_id="job-123",
            status="queued",
            prompt_seed=payload.prompt_seed,
            preview=_preview_response(payload.prompt_seed),
            progress=AuthorJobProgress(stage="queued", stage_index=1, stage_total=10),
            progress_snapshot=_progress_snapshot(stage="queued", stage_index=1, total_tokens=150),
            cache_metrics=AuthorCacheMetrics(
                session_cache_enabled=True,
                cache_path_used=True,
                total_call_count=2,
                previous_response_call_count=1,
                total_input_characters=400,
                estimated_input_tokens_from_chars=100,
                provider_usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
                input_tokens=120,
                output_tokens=30,
                total_tokens=150,
                reasoning_tokens=18,
                cached_input_tokens=80,
                cache_creation_input_tokens=20,
                cache_type="ephemeral",
                billing_type="response_api",
                cache_metrics_source="provider_usage_no_cache_breakdown",
            ),
        )

    def get_job(self, job_id: str, *, actor_user_id=None) -> AuthorJobStatusResponse:
        del actor_user_id
        return AuthorJobStatusResponse(
            job_id=job_id,
            status="running",
            prompt_seed="seed",
            preview=_preview_response("seed"),
            progress=AuthorJobProgress(stage="story_frame_ready", stage_index=3, stage_total=10),
            progress_snapshot=_progress_snapshot(stage="story_frame_ready", stage_index=3, total_tokens=225),
            cache_metrics=AuthorCacheMetrics(
                session_cache_enabled=True,
                cache_path_used=True,
                total_call_count=3,
                previous_response_call_count=2,
                total_input_characters=640,
                estimated_input_tokens_from_chars=160,
                provider_usage={"input_tokens": 180, "output_tokens": 45, "total_tokens": 225},
                input_tokens=180,
                output_tokens=45,
                total_tokens=225,
                reasoning_tokens=22,
                cached_input_tokens=120,
                cache_creation_input_tokens=30,
                cache_type="ephemeral",
                billing_type="response_api",
                cache_metrics_source="provider_usage_no_cache_breakdown",
            ),
        )

    def get_job_result(self, job_id: str, *, actor_user_id=None) -> AuthorJobResultResponse:
        del actor_user_id
        return AuthorJobResultResponse(
            job_id=job_id,
            status="completed",
            summary={
                "title": "The Harbor Compact",
                "one_liner": "A harbor inspector keeps a city from splintering during quarantine.",
                "premise": "A harbor inspector keeps a city from splintering during quarantine.",
                "tone": "Tense civic fantasy",
                "theme": "Logistics quarantine crisis",
                "npc_count": 4,
                "beat_count": 3,
            },
            bundle=None,
            progress_snapshot=_progress_snapshot(stage="completed", stage_index=10, total_tokens=570),
            cache_metrics=AuthorCacheMetrics(
                session_cache_enabled=True,
                cache_path_used=True,
                total_call_count=7,
                previous_response_call_count=6,
                total_input_characters=1800,
                estimated_input_tokens_from_chars=450,
                provider_usage={"input_tokens": 480, "output_tokens": 90, "total_tokens": 570},
                input_tokens=480,
                output_tokens=90,
                total_tokens=570,
                reasoning_tokens=55,
                cached_input_tokens=360,
                cache_creation_input_tokens=40,
                cache_type="ephemeral",
                billing_type="response_api",
                cache_metrics_source="provider_usage_no_cache_breakdown",
            ),
        )

    def stream_job_events(self, job_id: str, *, actor_user_id=None, last_event_id: int | None = None, heartbeat_seconds: float = 15.0):  # noqa: ANN001
        del job_id, actor_user_id, last_event_id, heartbeat_seconds
        yield (
            "id: 1\n"
            "event: job_started\n"
            "data: {\"status\":\"running\",\"progress_snapshot\":{\"primary_theme\":\"logistics_quarantine_crisis\",\"cast_topology\":\"four_slot\",\"completion_ratio\":0.1,\"stage_label\":\"Starting generation\",\"loading_cards\":[{\"card_id\":\"theme\",\"label\":\"Theme\",\"value\":\"Logistics quarantine crisis\",\"emphasis\":\"stable\"},{\"card_id\":\"generation_status\",\"label\":\"Generation Status\",\"value\":\"Starting generation.\",\"emphasis\":\"live\"}]},\"token_usage\":{\"total_tokens\":150},\"token_cost_estimate\":{\"estimated_total_cost_rmb\":0.00009}}\n\n"
        )
        yield (
            "id: 2\n"
            "event: stage_changed\n"
            "data: {\"progress\":{\"stage\":\"story_frame_ready\"},\"progress_snapshot\":{\"primary_theme\":\"logistics_quarantine_crisis\",\"cast_topology\":\"four_slot\",\"completion_ratio\":0.3,\"stage_label\":\"Story frame drafted\",\"loading_cards\":[{\"card_id\":\"generation_status\",\"label\":\"Generation Status\",\"value\":\"Story frame drafted. Title, premise, and stakes are set.\",\"emphasis\":\"live\"},{\"card_id\":\"beat_count\",\"label\":\"Beat Count\",\"value\":\"3 planned beats\",\"emphasis\":\"stable\"}]},\"token_usage\":{\"total_tokens\":225},\"token_cost_estimate\":{\"estimated_total_cost_rmb\":0.00012}}\n\n"
        )

    def get_publishable_job_source(self, job_id: str, *, actor_user_id=None):  # noqa: ANN001
        del actor_user_id
        from tests.test_story_library_api import _publish_source

        return _publish_source(job_id)


def _preview_response(prompt_seed: str) -> AuthorPreviewResponse:
    return AuthorPreviewResponse.model_validate(
        {
            "preview_id": "preview-123",
            "prompt_seed": prompt_seed,
            "focused_brief": {
                "story_kernel": "a harbor inspector preventing collapse",
                "setting_signal": "port city under quarantine and supply panic",
                "core_conflict": "keep the harbor operating while quarantine politics escalate",
                "tone_signal": "tense civic fantasy",
                "hard_constraints": [],
                "forbidden_tones": ["graphic cruelty", "sadistic evil"],
            },
            "theme": {
                "primary_theme": "logistics_quarantine_crisis",
                "modifiers": ["harbor", "quarantine", "public_panic"],
                "router_reason": "matched_brief_logistics_quarantine_keywords",
            },
            "strategies": {
                "story_frame_strategy": "harbor_quarantine_story",
                "cast_strategy": "harbor_quarantine_cast",
                "beat_plan_strategy": "harbor_quarantine_compile",
            },
            "structure": {
                "cast_topology": "four_slot",
                "expected_npc_count": 4,
                "expected_beat_count": 3,
            },
            "story": {
                "title": "The Harbor Compact",
                "premise": "In a harbor city under quarantine, an inspector must keep supply lines open before panic hardens into factional seizure.",
                "tone": "tense civic fantasy",
                "stakes": "If the harbor fails, the city fractures around scarcity and emergency power.",
            },
            "cast_slots": [
                {"slot_label": "Mediator Anchor", "public_role": "Harbor inspector"},
                {"slot_label": "Institutional Guardian", "public_role": "Port authority"},
                {"slot_label": "Leverage Broker", "public_role": "Trade bloc rival"},
                {"slot_label": "Civic Witness", "public_role": "Dock delegate"},
            ],
            "beats": [
                {"title": "The Quarantine Line", "goal": "Stabilize the harbor perimeter.", "milestone_kind": "reveal"},
                {"title": "The Dockside Audit", "goal": "Expose who profits from scarcity.", "milestone_kind": "fracture"},
                {"title": "The Harbor Compact", "goal": "Lock in a recovery bargain.", "milestone_kind": "commitment"},
            ],
            "flashcards": [
                AuthorPreviewFlashcard(card_id="theme", kind="stable", label="Theme", value="Logistics quarantine crisis").model_dump(mode="json"),
                AuthorPreviewFlashcard(card_id="tone", kind="stable", label="Tone", value="tense civic fantasy").model_dump(mode="json"),
                AuthorPreviewFlashcard(card_id="npc_count", kind="stable", label="NPC Count", value="4").model_dump(mode="json"),
                AuthorPreviewFlashcard(card_id="beat_count", kind="stable", label="Beat Count", value="3").model_dump(mode="json"),
                AuthorPreviewFlashcard(card_id="cast_topology", kind="stable", label="Cast Structure", value="4-slot civic web").model_dump(mode="json"),
                AuthorPreviewFlashcard(card_id="title", kind="draft", label="Working Title", value="The Harbor Compact").model_dump(mode="json"),
                AuthorPreviewFlashcard(
                    card_id="conflict",
                    kind="draft",
                    label="Core Conflict",
                    value="trade pressure and quarantine politics keep turning relief into factional leverage",
                ).model_dump(mode="json"),
            ],
            "stage": "brief_parsed",
        }
    )


def test_auth_session_and_me_route_reflect_logged_in_user() -> None:
    client = TestClient(app)
    ensure_authenticated_client(client, email="author-me@example.com", display_name="Alice")

    session_response = client.get("/auth/session")
    response = client.get("/me")

    assert session_response.status_code == 200
    assert session_response.json()["authenticated"] is True
    assert session_response.json()["user"]["display_name"] == "Alice"
    assert response.status_code == 200
    assert response.json()["display_name"] == "Alice"
    assert response.json()["email"] == "author-me@example.com"
    assert response.json()["is_default"] is False


def test_product_author_service_returns_v2_canonical_package(tmp_path, monkeypatch) -> None:
    service = ProductAuthorJobService(
        settings=get_settings().model_copy(
            update={
                "runtime_state_db_path": str(tmp_path / "runtime.sqlite3"),
                "author_product_run_mode": "deterministic",
            }
        )
    )

    preview = service.create_preview(type("PreviewRequest", (), {"prompt_seed": "董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。", "random_seed": None})(), actor_user_id="usr_v2")
    response = service.create_job(
        type("JobRequest", (), {"prompt_seed": "董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。", "preview_id": preview.preview_id, "random_seed": None})(),
        actor_user_id="usr_v2",
    )
    for _ in range(100):
        status = service.get_job(response.job_id, actor_user_id="usr_v2")
        if status.status in {"completed", "failed"}:
            break
        import time

        time.sleep(0.01)
    assert status.status == "completed"
    result = service.get_job_result(response.job_id, actor_user_id="usr_v2")
    assert result.bundle is not None
    assert result.bundle["package_version"] == "relationship_drama_v2"
    package = RelationshipDramaV2Package.model_validate(result.bundle)
    assert package.preview_blueprint.story_shell_id == "office_power"
    assert package.compiled_play_plan.play_length_preset == "12_15"
    diagnostics = service.get_job_diagnostics(response.job_id, actor_user_id="usr_v2")
    assert diagnostics.source_summary["package_version"] == "relationship_drama_v2"
    assert diagnostics.source_summary["preview_promise_gate"] == "accepted"
    assert diagnostics.source_summary["surface_signal_readability_gate"] == "accepted"


def test_product_author_service_honors_play_length_preset_override(tmp_path, monkeypatch) -> None:
    service = ProductAuthorJobService(
        settings=get_settings().model_copy(
            update={
                "runtime_state_db_path": str(tmp_path / "runtime.sqlite3"),
                "author_product_run_mode": "deterministic",
            }
        )
    )

    preview = service.create_preview(
        type(
            "PreviewRequest",
            (),
            {"prompt_seed": "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。", "random_seed": None, "play_length_preset": "20_25"},
        )(),
        actor_user_id="usr_v2",
    )
    response = service.create_job(
        type(
            "JobRequest",
            (),
            {"prompt_seed": preview.prompt_seed, "preview_id": preview.preview_id, "random_seed": None, "play_length_preset": "20_25"},
        )(),
        actor_user_id="usr_v2",
    )
    for _ in range(100):
        status = service.get_job(response.job_id, actor_user_id="usr_v2")
        if status.status in {"completed", "failed"}:
            break
        import time

        time.sleep(0.01)

    assert preview.play_length_preset == "20_25"
    assert status.status == "completed"
    result = service.get_job_result(response.job_id, actor_user_id="usr_v2")
    package = RelationshipDramaV2Package.model_validate(result.bundle)
    assert package.preview_blueprint.play_length_preset == "20_25"
    assert package.compiled_play_plan.play_length_preset == "20_25"


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _progress_snapshot(stage: str, stage_index: int, total_tokens: int) -> AuthorJobProgressSnapshot:
    estimated_total_rmb = {
        150: 0.00009,
        225: 0.00012,
        300: 0.000141,
        360: 0.000141,
        570: 0.000141,
    }.get(total_tokens, 0.000141)
    estimated_total_usd = estimated_total_rmb * get_settings().responses_usd_per_rmb
    loading_cards = [
        AuthorLoadingCard(card_id="structure", emphasis="stable", label="Story Shape", value="4-slot civic web"),
        AuthorLoadingCard(card_id="theme", emphasis="stable", label="Theme", value="Logistics quarantine crisis"),
    ]
    if stage in {"story_frame_ready", "cast_ready", "beat_plan_ready", "completed"}:
        loading_cards.extend(
            [
                AuthorLoadingCard(card_id="working_title", emphasis="draft", label="Working Title", value="The Harbor Compact"),
                AuthorLoadingCard(card_id="tone", emphasis="stable", label="Tone", value="Tense civic fantasy"),
                AuthorLoadingCard(
                    card_id="story_premise",
                    emphasis="draft",
                    label="Story Premise",
                    value="In a harbor city under quarantine, an inspector must keep supply lines open before panic hardens into factional seizure.",
                ),
                AuthorLoadingCard(
                    card_id="story_stakes",
                    emphasis="draft",
                    label="Story Stakes",
                    value="If the harbor fails, the city fractures around scarcity and emergency power.",
                ),
            ]
        )
    if stage in {"cast_ready", "beat_plan_ready", "completed"}:
        loading_cards.extend(
            [
                AuthorLoadingCard(
                    card_id="cast_count",
                    emphasis="stable",
                    label="NPC Count",
                    value="4 NPCs drafted",
                ),
                AuthorLoadingCard(
                    card_id="cast_anchor",
                    emphasis="draft",
                    label="Cast Anchor",
                    value="Mediator Anchor · Harbor inspector",
                ),
            ]
        )
    if stage in {"beat_plan_ready", "completed"}:
        loading_cards.extend(
            [
                AuthorLoadingCard(
                    card_id="beat_count",
                    emphasis="stable",
                    label="Beat Count",
                    value="3 beats drafted",
                ),
                AuthorLoadingCard(
                    card_id="opening_beat",
                    emphasis="draft",
                    label="Opening Beat",
                    value="The Quarantine Line: Stabilize the harbor perimeter.",
                ),
                AuthorLoadingCard(
                    card_id="final_beat",
                    emphasis="draft",
                    label="Final Beat",
                    value="The Harbor Compact: Lock in a recovery bargain.",
                ),
            ]
        )
    loading_cards.extend(
        [
            AuthorLoadingCard(
                card_id="generation_status",
                emphasis="live",
                label="Generation Status",
                value=(
                    "Story frame drafted. Title, premise, and stakes are set."
                    if stage == "story_frame_ready"
                    else "Beat plan drafted. Main progression is mapped."
                    if stage == "beat_plan_ready"
                    else "Cast roster drafted. NPC tensions are in place."
                    if stage == "cast_ready"
                    else "Bundle complete. Story package is ready."
                    if stage == "completed"
                    else "Queued. Preparing generation graph."
                ),
            ),
            AuthorLoadingCard(
                card_id="token_budget",
                emphasis="live",
                label="Token Budget",
                value=f"{total_tokens} total tokens · USD {estimated_total_usd:.6f} est.",
            ),
        ]
    )
    return AuthorJobProgressSnapshot(
        stage=stage,
        stage_label=(
            "Story frame drafted"
            if stage == "story_frame_ready"
            else "Beat plan drafted"
            if stage == "beat_plan_ready"
            else "Cast roster drafted"
            if stage == "cast_ready"
            else "Bundle complete"
            if stage == "completed"
            else "Queued for generation"
        ),
        stage_index=stage_index,
        stage_total=10,
        completion_ratio=round(stage_index / 10, 3),
        primary_theme="logistics_quarantine_crisis",
        cast_topology="four_slot",
        expected_npc_count=4,
        expected_beat_count=3,
        preview_title="The Harbor Compact",
        preview_premise="In a harbor city under quarantine, an inspector must keep supply lines open before panic hardens into factional seizure.",
        flashcards=[
            AuthorPreviewFlashcard(card_id="theme", kind="stable", label="Theme", value="Logistics quarantine crisis"),
        ],
        loading_cards=loading_cards,
    )


def test_story_preview_api_returns_preview_payload() -> None:
    import rpg_backend.main as main_module

    original = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService()
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, email="author-preview@example.com", display_name="Author Preview")
        response = client.post(
            "/author/story-previews",
            json={"prompt_seed": "A harbor quarantine officer tries to stop a port city from collapsing into panic."},
        )
    finally:
        main_module.author_job_service = original

    assert response.status_code == 200
    body = response.json()
    assert body["preview_id"]
    assert body["theme"]["primary_theme"]
    assert body["structure"]["expected_npc_count"] >= 3
    assert body["flashcards"]
    assert [card["label"] for card in body["flashcards"]] == [
        "Theme",
        "Tone",
        "NPC Count",
        "Beat Count",
        "Cast Structure",
        "Working Title",
        "Core Conflict",
    ]
    assert body["flashcards"][0]["value"] == "Logistics quarantine crisis"
    for card in body["flashcards"]:
        assert not _contains_cjk(card["label"])
        assert not _contains_cjk(card["value"])


def test_author_job_service_reuses_registered_preview(monkeypatch) -> None:
    import rpg_backend.author.jobs as jobs_module

    original_gateway_factory = jobs_module.get_author_llm_gateway
    jobs_module.get_author_llm_gateway = lambda: FakeGateway()
    service = AuthorJobService()
    monkeypatch.setattr(service, "_start_background_job", lambda job_id, resume_from_checkpoint: None)
    preview = service.create_preview(type("PreviewRequest", (), {"prompt_seed": "seed", "random_seed": None})(), actor_user_id="usr_preview")
    try:
        response = service.create_job(
            type("JobRequest", (), {"prompt_seed": "different-seed", "random_seed": None, "preview_id": preview.preview_id})(),
            actor_user_id="usr_preview",
        )
    finally:
        jobs_module.get_author_llm_gateway = original_gateway_factory

    assert response.preview.preview_id == preview.preview_id
    assert response.preview.prompt_seed == preview.prompt_seed
    assert response.progress.stage == "cast_planned"
    assert response.status == "running"


def test_author_job_routes_are_scoped_to_actor(monkeypatch) -> None:
    import rpg_backend.author.jobs as jobs_module
    import rpg_backend.main as main_module

    original_gateway_factory = jobs_module.get_author_llm_gateway
    original_author_service = main_module.author_job_service
    jobs_module.get_author_llm_gateway = lambda: FakeGateway()
    service = AuthorJobService()
    monkeypatch.setattr(service, "_start_background_job", lambda job_id, resume_from_checkpoint: None)
    main_module.author_job_service = service
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    try:
        ensure_authenticated_client(alice_client, email="alice-author@example.com", display_name="Alice")
        ensure_authenticated_client(bob_client, email="bob-author@example.com", display_name="Bob")
        preview = alice_client.post("/author/story-previews", json={"prompt_seed": "seed"})
        created = alice_client.post(
            "/author/jobs",
            json={"prompt_seed": "seed", "preview_id": preview.json()["preview_id"]},
        )
        hidden = bob_client.get(f"/author/jobs/{created.json()['job_id']}")
        visible = alice_client.get(f"/author/jobs/{created.json()['job_id']}")
    finally:
        main_module.author_job_service = original_author_service
        jobs_module.get_author_llm_gateway = original_gateway_factory

    assert preview.status_code == 200
    assert created.status_code == 200
    assert hidden.status_code == 404
    assert visible.status_code == 200


def test_author_job_service_event_payload_includes_token_snapshot() -> None:
    import rpg_backend.author.jobs as jobs_module

    service = AuthorJobService()
    service._jobs["job-123"] = jobs_module._AuthorJobRecord(
        job_id="job-123",
        owner_user_id="local-dev",
        prompt_seed="seed",
        preview=_preview_response("seed"),
        status="running",
        progress=AuthorJobProgress(stage="cast_ready", stage_index=6, stage_total=10),
        cache_metrics=AuthorCacheMetrics(
            session_cache_enabled=True,
            cache_path_used=True,
            total_call_count=4,
            previous_response_call_count=3,
            total_input_characters=920,
            estimated_input_tokens_from_chars=230,
            provider_usage={"input_tokens": 240, "output_tokens": 60, "total_tokens": 300},
            input_tokens=240,
            output_tokens=60,
            total_tokens=300,
            reasoning_tokens=28,
            cached_input_tokens=160,
            cache_creation_input_tokens=30,
            cache_type="ephemeral",
            billing_type="response_api",
            cache_metrics_source="provider_usage_no_cache_breakdown",
        ),
    )

    payload = service._build_status_event_payload("job-123")

    assert payload["status"] == "running"
    assert payload["progress"]["stage"] == "cast_ready"
    assert payload["progress_snapshot"]["stage_label"] == "Cast roster drafted"
    assert payload["progress_snapshot"]["primary_theme"] == "logistics_quarantine_crisis"
    assert payload["progress_snapshot"]["cast_topology"] == "four_slot"
    cards = {card["card_id"]: card for card in payload["progress_snapshot"]["loading_cards"]}
    assert set(cards) == {
        "theme",
        "structure",
        "working_title",
        "tone",
        "story_premise",
        "story_stakes",
        "cast_count",
        "cast_anchor",
        "generation_status",
        "token_budget",
    }
    assert cards["cast_count"]["value"] == "4 NPCs drafted"
    assert cards["cast_anchor"]["value"] == "Mediator Anchor · Harbor inspector"
    assert cards["generation_status"]["value"] == "Cast roster drafted. NPC tensions are in place."
    assert payload["token_usage"]["total_tokens"] == 300
    assert payload["token_cost_estimate"]["estimated_total_cost_rmb"] > 0


def test_author_job_service_loading_cards_are_stage_adaptive() -> None:
    import rpg_backend.author.jobs as jobs_module

    service = AuthorJobService()

    def build_record(stage: str, stage_index: int, total_tokens: int | None) -> jobs_module._AuthorJobRecord:
        metrics = None
        if total_tokens is not None:
            metrics = AuthorCacheMetrics(
                session_cache_enabled=True,
                cache_path_used=True,
                total_call_count=4,
                previous_response_call_count=3,
                total_input_characters=920,
                estimated_input_tokens_from_chars=230,
                provider_usage={"input_tokens": 240, "output_tokens": 60, "total_tokens": total_tokens},
                input_tokens=240,
                output_tokens=60,
                total_tokens=total_tokens,
                reasoning_tokens=28,
                cached_input_tokens=160,
                cache_creation_input_tokens=30,
                cache_type="ephemeral",
                billing_type="response_api",
                cache_metrics_source="provider_usage_no_cache_breakdown",
            )
        return jobs_module._AuthorJobRecord(
            job_id=f"job-{stage}",
            owner_user_id="local-dev",
            prompt_seed="seed",
            preview=_preview_response("seed"),
            status="running" if stage != "completed" else "completed",
            progress=AuthorJobProgress(stage=stage, stage_index=stage_index, stage_total=10),
            cache_metrics=metrics,
        )

    scenarios = [
        ("queued", 1, None, {"theme", "structure", "generation_status", "token_budget"}, "Queued. Preparing generation graph.", "Waiting for first model call"),
        (
            "story_frame_ready",
            3,
            225,
            {"theme", "structure", "working_title", "tone", "story_premise", "story_stakes", "generation_status", "token_budget"},
            "Story frame drafted. Title, premise, and stakes are set.",
            "225 total tokens · USD 0.000020 est.",
        ),
        (
            "cast_ready",
            6,
            300,
            {"theme", "structure", "working_title", "tone", "story_premise", "story_stakes", "cast_count", "cast_anchor", "generation_status", "token_budget"},
            "Cast roster drafted. NPC tensions are in place.",
            "300 total tokens · USD 0.000020 est.",
        ),
        (
            "beat_plan_ready",
            7,
            360,
            {"theme", "structure", "working_title", "tone", "story_premise", "story_stakes", "cast_count", "cast_anchor", "beat_count", "opening_beat", "final_beat", "generation_status", "token_budget"},
            "Beat plan drafted. Main progression is mapped.",
            "360 total tokens · USD 0.000020 est.",
        ),
        (
            "completed",
            10,
            570,
            {"theme", "structure", "working_title", "tone", "story_premise", "story_stakes", "cast_count", "cast_anchor", "beat_count", "opening_beat", "final_beat", "generation_status", "token_budget"},
            "Bundle complete. Story package is ready.",
            "570 total tokens · USD 0.000020 est.",
        ),
    ]

    for stage, stage_index, total_tokens, expected_card_ids, status_value, token_value in scenarios:
        snapshot = service._progress_snapshot(build_record(stage, stage_index, total_tokens))
        cards = {card.card_id: card for card in snapshot.loading_cards}
        assert set(cards) == expected_card_ids
        assert cards["generation_status"].value == status_value
        assert cards["token_budget"].value == token_value
        if stage in {"cast_ready", "beat_plan_ready", "completed"}:
            assert cards["cast_count"].value == "4 NPCs drafted"
            assert cards["cast_anchor"].value == "Mediator Anchor · Harbor inspector"
        if stage in {"beat_plan_ready", "completed"}:
            assert cards["beat_count"].value == "3 beats drafted"
            assert cards["opening_beat"].value == "The Quarantine Line: Stabilize the harbor perimeter."
            assert cards["final_beat"].value == "The Harbor Compact: Lock in a recovery bargain."


def test_author_job_routes_use_job_service(monkeypatch) -> None:
    import rpg_backend.main as main_module

    original = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService()
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, email="author-job-routes@example.com", display_name="Author Routes")
        create_response = client.post(
            "/author/jobs",
            json={"prompt_seed": "港口检疫官阻止城市崩溃"},
        )
        status_response = client.get("/author/jobs/job-123")
        result_response = client.get("/author/jobs/job-123/result")
    finally:
        main_module.author_job_service = original

    assert create_response.status_code == 200
    assert create_response.json()["job_id"] == "job-123"
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "running"
    assert status_response.json()["cache_metrics"]["session_cache_enabled"] is True
    stage_cards = {card["card_id"]: card for card in status_response.json()["progress_snapshot"]["loading_cards"]}
    assert {"theme", "structure", "working_title", "tone", "story_premise", "story_stakes", "generation_status", "token_budget"} <= set(stage_cards)
    assert stage_cards["generation_status"]["value"] == "Story frame drafted. Title, premise, and stakes are set."
    assert result_response.status_code == 200
    assert result_response.json()["summary"]["title"] == "The Harbor Compact"
    assert result_response.json()["progress_snapshot"]["stage_label"] == "Bundle complete"
    assert result_response.json()["summary"]["theme"] == "Logistics quarantine crisis"
    assert result_response.json()["cache_metrics"]["total_call_count"] == 7


def test_author_job_events_route_streams_sse(monkeypatch) -> None:
    import rpg_backend.main as main_module

    original = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService()
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, email="author-events@example.com", display_name="Author Events")
        response = client.get("/author/jobs/job-123/events")
    finally:
        main_module.author_job_service = original

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: job_started" in response.text
    assert "event: stage_changed" in response.text
    assert "\"progress_snapshot\"" in response.text
    assert "\"loading_cards\"" in response.text
    assert "\"cast_topology\":\"four_slot\"" in response.text
    assert "\"token_usage\"" in response.text
    assert "\"estimated_total_cost_rmb\"" in response.text
    assert "Story frame drafted. Title, premise, and stakes are set." in response.text


def test_product_api_loading_copy_is_english_only(monkeypatch) -> None:
    import rpg_backend.main as main_module

    original = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService()
    client = TestClient(app)
    try:
        ensure_authenticated_client(client, email="author-copy@example.com", display_name="Author Copy")
        preview_response = client.post(
            "/author/story-previews",
            json={"prompt_seed": "A harbor quarantine officer tries to stop a port city from collapsing into panic."},
        )
        status_response = client.get("/author/jobs/job-123")
        result_response = client.get("/author/jobs/job-123/result")
    finally:
        main_module.author_job_service = original

    assert preview_response.status_code == 200
    assert status_response.status_code == 200
    assert result_response.status_code == 200

    display_strings = []
    display_strings.extend(card["label"] for card in preview_response.json()["flashcards"])
    display_strings.extend(card["value"] for card in preview_response.json()["flashcards"])
    display_strings.extend(card["label"] for card in status_response.json()["progress_snapshot"]["loading_cards"])
    display_strings.extend(card["value"] for card in status_response.json()["progress_snapshot"]["loading_cards"])
    display_strings.append(result_response.json()["summary"]["theme"])

    for value in display_strings:
        assert not _contains_cjk(value)
