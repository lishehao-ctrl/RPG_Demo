from __future__ import annotations

import re

from fastapi.testclient import TestClient

from rpg_backend.author.jobs import AuthorJobService
from rpg_backend.author.preview import build_generation_state_from_preview
from rpg_backend.author.contracts import (
    AuthorCacheMetrics,
    AuthorJobProgress,
    AuthorJobProgressSnapshot,
    AuthorJobResultResponse,
    AuthorJobStatusResponse,
    AuthorJobTokenUsageDetailResponse,
    AuthorJobTokenUsageResponse,
    AuthorLoadingCard,
    AuthorTokenCostEstimate,
    AuthorTokenUsageBucket,
    AuthorPreviewFlashcard,
    AuthorPreviewResponse,
)
from rpg_backend.main import app


class _FakeAuthorJobService:
    def create_preview(self, payload):  # noqa: ANN001
        return _preview_response(payload.prompt_seed)

    def create_job(self, payload):  # noqa: ANN001
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

    def get_job(self, job_id: str) -> AuthorJobStatusResponse:
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

    def get_job_result(self, job_id: str) -> AuthorJobResultResponse:
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

    def get_job_token_usage(self, job_id: str) -> AuthorJobTokenUsageResponse:
        return AuthorJobTokenUsageResponse(
            job_id=job_id,
            status="running",
            progress=AuthorJobProgress(stage="cast_ready", stage_index=6, stage_total=10),
            token_usage=AuthorCacheMetrics(
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

    def get_job_token_usage_detail(self, job_id: str) -> AuthorJobTokenUsageDetailResponse:
        summary = self.get_job_token_usage(job_id)
        return AuthorJobTokenUsageDetailResponse(
            job_id=job_id,
            status="running",
            progress=summary.progress,
            total_token_usage=summary.token_usage,
            operation_breakdown=[
                AuthorTokenUsageBucket(
                    bucket_id="story_frame_semantics",
                    token_usage=AuthorCacheMetrics(
                        session_cache_enabled=True,
                        cache_path_used=True,
                        total_call_count=1,
                        previous_response_call_count=0,
                        total_input_characters=280,
                        estimated_input_tokens_from_chars=70,
                        provider_usage={"input_tokens": 90, "output_tokens": 24, "total_tokens": 114},
                        input_tokens=90,
                        output_tokens=24,
                        total_tokens=114,
                        reasoning_tokens=10,
                        cached_input_tokens=0,
                        cache_creation_input_tokens=20,
                        cache_type="ephemeral",
                        billing_type="response_api",
                        cache_metrics_source="provider_usage_no_cache_breakdown",
                    ),
                ),
                AuthorTokenUsageBucket(
                    bucket_id="cast_member_semantics",
                    token_usage=AuthorCacheMetrics(
                        session_cache_enabled=True,
                        cache_path_used=True,
                        total_call_count=3,
                        previous_response_call_count=3,
                        total_input_characters=640,
                        estimated_input_tokens_from_chars=160,
                        provider_usage={"input_tokens": 150, "output_tokens": 36, "total_tokens": 186},
                        input_tokens=150,
                        output_tokens=36,
                        total_tokens=186,
                        reasoning_tokens=18,
                        cached_input_tokens=160,
                        cache_creation_input_tokens=10,
                        cache_type="ephemeral",
                        billing_type="response_api",
                        cache_metrics_source="provider_usage_no_cache_breakdown",
                    ),
                ),
            ],
            stage_breakdown=[
                AuthorTokenUsageBucket(
                    bucket_id="story_frame",
                    token_usage=AuthorCacheMetrics(
                        session_cache_enabled=True,
                        cache_path_used=True,
                        total_call_count=1,
                        previous_response_call_count=0,
                        total_input_characters=280,
                        estimated_input_tokens_from_chars=70,
                        provider_usage={"input_tokens": 90, "output_tokens": 24, "total_tokens": 114},
                        input_tokens=90,
                        output_tokens=24,
                        total_tokens=114,
                        reasoning_tokens=10,
                        cached_input_tokens=0,
                        cache_creation_input_tokens=20,
                        cache_type="ephemeral",
                        billing_type="response_api",
                        cache_metrics_source="provider_usage_no_cache_breakdown",
                    ),
                ),
                AuthorTokenUsageBucket(
                    bucket_id="cast_member",
                    token_usage=AuthorCacheMetrics(
                        session_cache_enabled=True,
                        cache_path_used=True,
                        total_call_count=3,
                        previous_response_call_count=3,
                        total_input_characters=640,
                        estimated_input_tokens_from_chars=160,
                        provider_usage={"input_tokens": 150, "output_tokens": 36, "total_tokens": 186},
                        input_tokens=150,
                        output_tokens=36,
                        total_tokens=186,
                        reasoning_tokens=18,
                        cached_input_tokens=160,
                        cache_creation_input_tokens=10,
                        cache_type="ephemeral",
                        billing_type="response_api",
                        cache_metrics_source="provider_usage_no_cache_breakdown",
                    ),
                ),
            ],
            cost_estimate=AuthorTokenCostEstimate(
                model="qwen3.5-flash",
                currency="RMB",
                input_price_per_million_tokens_rmb=0.2,
                output_price_per_million_tokens_rmb=2.0,
                session_cache_hit_multiplier=0.1,
                session_cache_creation_multiplier=1.25,
                uncached_input_tokens=50,
                cached_input_tokens=160,
                cache_creation_input_tokens=30,
                output_tokens=60,
                estimated_input_cost_rmb=0.00002,
                estimated_output_cost_rmb=0.00012,
                estimated_total_cost_rmb=0.00014,
                notes=None,
            ),
        )

    def stream_job_events(self, job_id: str, *, last_event_id: int | None = None, heartbeat_seconds: float = 15.0):  # noqa: ANN001
        del job_id, last_event_id, heartbeat_seconds
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
                "story_frame_strategy": "logistics_story",
                "cast_strategy": "logistics_cast",
                "beat_plan_strategy": "single_semantic_compile",
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
            ],
            "stage": "brief_parsed",
        }
    )


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _progress_snapshot(stage: str, stage_index: int, total_tokens: int) -> AuthorJobProgressSnapshot:
    loading_cards = [
        AuthorLoadingCard(card_id="theme", emphasis="stable", label="Theme", value="Logistics quarantine crisis"),
        AuthorLoadingCard(card_id="tone", emphasis="stable", label="Tone", value="Tense civic fantasy"),
        AuthorLoadingCard(card_id="structure", emphasis="stable", label="Story Shape", value="4-slot civic web"),
        AuthorLoadingCard(
            card_id="cast_count",
            emphasis="stable",
            label="NPC Count",
            value="4 NPCs drafted" if stage in {"cast_ready", "beat_plan_ready", "completed"} else "4 planned NPCs",
        ),
        AuthorLoadingCard(
            card_id="beat_count",
            emphasis="stable",
            label="Beat Count",
            value="3 beats drafted" if stage in {"beat_plan_ready", "completed"} else "3 planned beats",
        ),
        AuthorLoadingCard(card_id="working_title", emphasis="draft", label="Working Title", value="The Harbor Compact"),
        AuthorLoadingCard(
            card_id="core_conflict",
            emphasis="draft",
            label="Core Conflict",
            value="keep the harbor operating while quarantine politics escalate",
        ),
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
        AuthorLoadingCard(card_id="token_budget", emphasis="live", label="Token Budget", value=f"{total_tokens} total tokens"),
    ]
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
    client = TestClient(app)
    response = client.post(
        "/author/story-previews",
        json={"prompt_seed": "A harbor quarantine officer tries to stop a port city from collapsing into panic."},
    )

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


def test_generation_state_is_locked_from_preview() -> None:
    preview = _preview_response("seed")
    state = build_generation_state_from_preview(preview)

    assert state["brief_primary_theme"] == "logistics_quarantine_crisis"
    assert state["story_frame_strategy"] == "logistics_story"
    assert state["cast_strategy"] == "logistics_cast"
    assert state["beat_plan_strategy"] == "single_semantic_compile"
    assert state["cast_topology"] == "four_slot"


def test_author_job_service_reuses_registered_preview(monkeypatch) -> None:
    import rpg_backend.author.jobs as jobs_module

    class _FakeThread:
        def __init__(self, target=None, args=None, daemon=None):  # noqa: ANN001
            self.target = target
            self.args = args or ()

        def start(self) -> None:
            return None

    monkeypatch.setattr(jobs_module.threading, "Thread", _FakeThread)
    service = AuthorJobService()
    preview = service.create_preview(type("PreviewRequest", (), {"prompt_seed": "seed", "random_seed": None})())

    response = service.create_job(
        type("JobRequest", (), {"prompt_seed": "different-seed", "random_seed": None, "preview_id": preview.preview_id})()
    )

    assert response.preview.preview_id == preview.preview_id
    assert response.preview.prompt_seed == preview.prompt_seed


def test_author_job_service_event_payload_includes_token_snapshot() -> None:
    import rpg_backend.author.jobs as jobs_module

    service = AuthorJobService()
    service._jobs["job-123"] = jobs_module._AuthorJobRecord(
        job_id="job-123",
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
    assert [card["card_id"] for card in payload["progress_snapshot"]["loading_cards"]] == [
        "theme",
        "tone",
        "structure",
        "cast_count",
        "beat_count",
        "working_title",
        "core_conflict",
        "generation_status",
        "token_budget",
    ]
    assert payload["progress_snapshot"]["loading_cards"][3]["value"] == "4 NPCs drafted"
    assert payload["progress_snapshot"]["loading_cards"][4]["value"] == "3 planned beats"
    assert payload["progress_snapshot"]["loading_cards"][7]["value"] == "Cast roster drafted. NPC tensions are in place."
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
            prompt_seed="seed",
            preview=_preview_response("seed"),
            status="running" if stage != "completed" else "completed",
            progress=AuthorJobProgress(stage=stage, stage_index=stage_index, stage_total=10),
            cache_metrics=metrics,
        )

    scenarios = [
        ("queued", 1, None, "4 planned NPCs", "3 planned beats", "Queued. Preparing generation graph.", "Waiting for first model call"),
        (
            "story_frame_ready",
            3,
            225,
            "4 planned NPCs",
            "3 planned beats",
            "Story frame drafted. Title, premise, and stakes are set.",
            "225 total tokens · RMB 0.000141 est.",
        ),
        (
            "cast_ready",
            6,
            300,
            "4 NPCs drafted",
            "3 planned beats",
            "Cast roster drafted. NPC tensions are in place.",
            "300 total tokens · RMB 0.000141 est.",
        ),
        (
            "beat_plan_ready",
            7,
            360,
            "4 NPCs drafted",
            "3 beats drafted",
            "Beat plan drafted. Main progression is mapped.",
            "360 total tokens · RMB 0.000141 est.",
        ),
        (
            "completed",
            10,
            570,
            "4 NPCs drafted",
            "3 beats drafted",
            "Bundle complete. Story package is ready.",
            "570 total tokens · RMB 0.000141 est.",
        ),
    ]

    for stage, stage_index, total_tokens, cast_value, beat_value, status_value, token_value in scenarios:
        snapshot = service._build_progress_snapshot(build_record(stage, stage_index, total_tokens))
        assert [card.card_id for card in snapshot.loading_cards] == [
            "theme",
            "tone",
            "structure",
            "cast_count",
            "beat_count",
            "working_title",
            "core_conflict",
            "generation_status",
            "token_budget",
        ]
        cards = {card.card_id: card for card in snapshot.loading_cards}
        assert cards["cast_count"].value == cast_value
        assert cards["beat_count"].value == beat_value
        assert cards["generation_status"].value == status_value
        assert cards["token_budget"].value == token_value


def test_author_job_routes_use_job_service(monkeypatch) -> None:
    import rpg_backend.main as main_module

    original = main_module.author_job_service
    main_module.author_job_service = _FakeAuthorJobService()
    client = TestClient(app)
    try:
        create_response = client.post(
            "/author/jobs",
            json={"prompt_seed": "港口检疫官阻止城市崩溃"},
        )
        status_response = client.get("/author/jobs/job-123")
        usage_response = client.get("/author/jobs/job-123/token-usage")
        usage_detail_response = client.get("/author/jobs/job-123/token-usage/detail")
        result_response = client.get("/author/jobs/job-123/result")
    finally:
        main_module.author_job_service = original

    assert create_response.status_code == 200
    assert create_response.json()["job_id"] == "job-123"
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "running"
    assert status_response.json()["cache_metrics"]["session_cache_enabled"] is True
    assert status_response.json()["progress_snapshot"]["loading_cards"][0]["card_id"] == "theme"
    assert status_response.json()["progress_snapshot"]["loading_cards"][7]["value"] == "Story frame drafted. Title, premise, and stakes are set."
    assert usage_response.status_code == 200
    assert usage_response.json()["token_usage"]["input_tokens"] == 240
    assert usage_response.json()["progress"]["stage"] == "cast_ready"
    assert usage_detail_response.status_code == 200
    assert usage_detail_response.json()["total_token_usage"]["total_tokens"] == 300
    assert usage_detail_response.json()["operation_breakdown"][0]["bucket_id"] == "story_frame_semantics"
    assert usage_detail_response.json()["stage_breakdown"][1]["bucket_id"] == "cast_member"
    assert usage_detail_response.json()["cost_estimate"]["estimated_total_cost_rmb"] == 0.00014
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
