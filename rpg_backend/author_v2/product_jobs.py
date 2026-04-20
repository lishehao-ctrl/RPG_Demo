from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import tempfile
from typing import Any
from uuid import uuid4

from rpg_backend.author.contracts import (
    AuthorCacheMetrics,
    AuthorJobCreateRequest,
    AuthorJobProgress,
    AuthorJobProgressSnapshot,
    AuthorJobResultResponse,
    AuthorJobStatusResponse,
    AuthorPreviewRequest,
    AuthorPreviewResponse,
    AuthorStorySummary,
)
from rpg_backend.author.display import build_progress_snapshot
from rpg_backend.author.gateway import AuthorGatewayError
from rpg_backend.author.jobs import AuthorJobPublishSource
from rpg_backend.author.metrics import estimate_token_cost, summarize_cache_metrics
from rpg_backend.author.storage import SQLiteAuthorJobStorage
from rpg_backend.author_v2.preview import apply_blueprint_edits, normalize_preview_blueprint, run_preview_blueprint_graph
from rpg_backend.author_v2.product_adapters import (
    author_preview_from_blueprint,
    author_story_summary_from_package,
    package_from_pipeline,
)
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.author_v2.quality_gates import (
    evaluate_ending_payoff_gate,
    evaluate_preview_promise_gate,
    evaluate_seed_preservation_gate,
    evaluate_segment_tension_gate,
    evaluate_surface_signal_readability,
)
from rpg_backend.author_v2.workflow import run_author_play_graph
from rpg_backend.benchmark.contracts import (
    BenchmarkAuthorJobDiagnosticsResponse,
    BenchmarkAuthorJobEvent,
    BenchmarkStageTiming,
)
from rpg_backend.config import Settings, get_settings


@dataclass
class _ProductAuthorJobRecord:
    job_id: str
    owner_user_id: str
    prompt_seed: str
    preview: AuthorPreviewResponse
    preview_blueprint: Any
    status: str
    progress: AuthorJobProgress
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    cache_metrics: AuthorCacheMetrics | None = None
    llm_call_trace: list[dict[str, Any]] = field(default_factory=list)
    quality_trace: list[dict[str, Any]] = field(default_factory=list)
    source_summary: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    bundle: RelationshipDramaV2Package | None = None
    summary: AuthorStorySummary | None = None
    error: dict[str, str] | None = None


class ProductAuthorJobService:
    def __init__(
        self,
        *,
        storage: SQLiteAuthorJobStorage | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._storage = storage or SQLiteAuthorJobStorage(
            self._settings.runtime_state_db_path
            if settings is not None
            else f"{tempfile.gettempdir()}/rpg_demo_author_jobs_v2_{uuid4()}.sqlite3"
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, _ProductAuthorJobRecord] = {}
        self._conditions: dict[str, threading.Condition] = {}
        self._reconcile_interrupted_jobs()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _apply_requested_preview_edits(preview_blueprint, request):  # noqa: ANN001, ANN202
        updates: dict[str, Any] = {}
        play_length_preset = getattr(request, "play_length_preset", None)
        if play_length_preset:
            updates["play_length_preset"] = play_length_preset
        target_gender_pref = getattr(request, "target_gender_pref", None)
        if target_gender_pref in {"male", "female"}:
            updates["target_gender_pref"] = target_gender_pref
        if not updates:
            return preview_blueprint
        normalized = normalize_preview_blueprint(
            {
                "preview_blueprint": preview_blueprint.model_copy(update=updates),
                "quality_trace": [],
                "llm_call_trace": [],
            }
        )
        return normalized["preview_blueprint"]

    def _run_mode(self) -> str:
        return str(getattr(self._settings, "author_product_run_mode", "deterministic") or "deterministic")

    @staticmethod
    def _progress_for_stage(stage: str) -> AuthorJobProgress:
        public_stage_to_index = {
            "queued": 1,
            "running": 2,
            "theme_confirmed": 3,
            "cast_planned": 4,
            "beat_plan_ready": 5,
            "ending_ready": 6,
            "completed": 7,
            "failed": 7,
        }
        stage_index = public_stage_to_index.get(stage, 1)
        return AuthorJobProgress(stage=stage, stage_index=stage_index, stage_total=max(public_stage_to_index.values()))

    def _condition_for(self, job_id: str) -> threading.Condition:
        condition = self._conditions.get(job_id)
        if condition is None:
            condition = threading.Condition()
            self._conditions[job_id] = condition
        return condition

    @staticmethod
    def _serialize_preview_payload(*, preview: AuthorPreviewResponse, preview_blueprint) -> dict[str, Any]:  # noqa: ANN001
        return {
            "preview_response": preview.model_dump(mode="json"),
            "preview_blueprint": preview_blueprint.model_dump(mode="json"),
        }

    @staticmethod
    def _deserialize_preview_payload(payload: dict[str, Any]) -> tuple[AuthorPreviewResponse, Any]:
        from rpg_backend.author_v2.contracts import UrbanPreviewBlueprint

        if "preview_response" in payload and "preview_blueprint" in payload:
            return (
                AuthorPreviewResponse.model_validate(payload["preview_response"]),
                UrbanPreviewBlueprint.model_validate(payload["preview_blueprint"]),
            )
        preview = AuthorPreviewResponse.model_validate(payload)
        return preview, None

    def _serialize_job_record(self, record: _ProductAuthorJobRecord) -> dict[str, Any]:
        return {
            "job_id": record.job_id,
            "owner_user_id": record.owner_user_id,
            "prompt_seed": record.prompt_seed,
            "preview": self._serialize_preview_payload(preview=record.preview, preview_blueprint=record.preview_blueprint),
            "status": record.status,
            "progress": record.progress.model_dump(mode="json"),
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "finished_at": record.finished_at.isoformat() if record.finished_at is not None else None,
            "cache_metrics": record.cache_metrics.model_dump(mode="json") if record.cache_metrics is not None else None,
            "llm_call_trace": list(record.llm_call_trace),
            "quality_trace": list(record.quality_trace),
            "source_summary": dict(record.source_summary),
            "events": [
                {**event, "emitted_at": event["emitted_at"].isoformat()}
                for event in record.events
            ],
            "bundle": record.bundle.model_dump(mode="json") if record.bundle is not None else None,
            "summary": record.summary.model_dump(mode="json") if record.summary is not None else None,
            "error": record.error,
        }

    @classmethod
    def _deserialize_job_record(cls, payload: dict[str, Any]) -> _ProductAuthorJobRecord:
        preview, preview_blueprint = cls._deserialize_preview_payload(dict(payload["preview"]))
        return _ProductAuthorJobRecord(
            job_id=str(payload["job_id"]),
            owner_user_id=str(payload["owner_user_id"]),
            prompt_seed=str(payload["prompt_seed"]),
            preview=preview,
            preview_blueprint=preview_blueprint,
            status=str(payload["status"]),
            progress=AuthorJobProgress.model_validate(payload["progress"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
            finished_at=datetime.fromisoformat(str(payload["finished_at"])) if payload.get("finished_at") else None,
            cache_metrics=AuthorCacheMetrics.model_validate(payload["cache_metrics"]) if payload.get("cache_metrics") else None,
            llm_call_trace=list(payload.get("llm_call_trace") or []),
            quality_trace=list(payload.get("quality_trace") or []),
            source_summary=dict(payload.get("source_summary") or {}),
            events=[
                {**event, "emitted_at": datetime.fromisoformat(str(event["emitted_at"]))}
                for event in (payload.get("events") or [])
            ],
            condition=threading.Condition(),
            bundle=RelationshipDramaV2Package.model_validate(payload["bundle"]) if payload.get("bundle") is not None else None,
            summary=AuthorStorySummary.model_validate(payload["summary"]) if payload.get("summary") is not None else None,
            error=payload.get("error"),
        )

    def _save_record(self, record: _ProductAuthorJobRecord) -> None:
        self._jobs[record.job_id] = record
        self._storage.save_job(self._serialize_job_record(record))

    def _get_record(self, job_id: str) -> _ProductAuthorJobRecord:
        cached = self._jobs.get(job_id)
        if cached is not None:
            cached.condition = self._condition_for(job_id)
            return cached
        payload = self._storage.get_job(job_id)
        if payload is None:
            raise AuthorGatewayError(
                code="author_job_not_found",
                message=f"author job '{job_id}' was not found",
                status_code=404,
            )
        record = self._deserialize_job_record(payload)
        record.condition = self._condition_for(job_id)
        self._jobs[job_id] = record
        return record

    @staticmethod
    def _ensure_owner_access(owner_user_id: str, actor_user_id: str, *, resource: str, resource_id: str) -> None:
        if owner_user_id == actor_user_id:
            return
        raise AuthorGatewayError(
            code=f"{resource}_not_found",
            message=f"{resource} '{resource_id}' was not found",
            status_code=404,
        )

    def _build_status_event_payload(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._get_record(job_id)
            payload = {
                "job_id": record.job_id,
                "status": record.status,
                "prompt_seed": record.prompt_seed,
                "preview": record.preview.model_dump(mode="json"),
                "progress": record.progress.model_dump(mode="json"),
                "cache_metrics": record.cache_metrics.model_dump(mode="json") if record.cache_metrics else None,
                "error": record.error,
                "progress_snapshot": self._progress_snapshot(record).model_dump(mode="json"),
            }
            payload.update(self._build_token_snapshot_payload(record))
            return payload

    def _build_result_event_payload(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._get_record(job_id)
            payload = {
                "job_id": record.job_id,
                "status": record.status,
                "progress": record.progress.model_dump(mode="json"),
                "summary": record.summary.model_dump(mode="json") if record.summary else None,
                "bundle": record.bundle.model_dump(mode="json") if record.bundle else None,
                "cache_metrics": record.cache_metrics.model_dump(mode="json") if record.cache_metrics else None,
                "progress_snapshot": self._progress_snapshot(record).model_dump(mode="json"),
            }
            payload.update(self._build_token_snapshot_payload(record))
            return payload

    def _emit_event(self, job_id: str, event_name: str, payload: dict[str, Any]) -> None:
        with self._lock:
            record = self._get_record(job_id)
            event_id = len(record.events) + 1
            emitted_at = self._now()
            event = {"id": event_id, "event": event_name, "emitted_at": emitted_at, "data": payload}
            record.events.append(event)
            record.updated_at = emitted_at
            self._save_record(record)
            condition = self._condition_for(job_id)
        with condition:
            condition.notify_all()

    def _progress_snapshot(self, record: _ProductAuthorJobRecord) -> AuthorJobProgressSnapshot:
        token_usage = record.cache_metrics or summarize_cache_metrics(record.llm_call_trace)
        return build_progress_snapshot(
            preview=record.preview,
            progress=record.progress,
            token_usage=token_usage,
            token_cost_estimate=estimate_token_cost(token_usage),
        )

    def _build_token_snapshot_payload(self, record: _ProductAuthorJobRecord) -> dict[str, Any]:
        token_usage = record.cache_metrics or summarize_cache_metrics(record.llm_call_trace)
        token_cost_estimate = estimate_token_cost(token_usage)
        return {
            "token_usage": token_usage.model_dump(mode="json"),
            "token_cost_estimate": token_cost_estimate.model_dump(mode="json") if token_cost_estimate else None,
        }

    def create_preview(
        self,
        request: AuthorPreviewRequest | AuthorJobCreateRequest,
        *,
        actor_user_id: str | None = None,
    ) -> AuthorPreviewResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        preview_blueprint, _state = run_preview_blueprint_graph(request.prompt_seed, live_mode=self._run_mode())  # type: ignore[arg-type]
        preview_blueprint = self._apply_requested_preview_edits(preview_blueprint, request)
        preview = author_preview_from_blueprint(preview_blueprint)
        self._storage.save_preview(
            preview.preview_id,
            self._serialize_preview_payload(preview=preview, preview_blueprint=preview_blueprint),
            owner_user_id=resolved_actor_user_id,
            created_at=self._now(),
        )
        return preview

    def _resolve_preview_for_job(self, request: AuthorJobCreateRequest, *, actor_user_id: str) -> tuple[AuthorPreviewResponse, Any]:
        preview_payload = self._storage.get_preview(request.preview_id) if request.preview_id else None
        if preview_payload is not None:
            self._ensure_owner_access(
                str(preview_payload["owner_user_id"]),
                actor_user_id,
                resource="author_preview",
                resource_id=str(request.preview_id),
            )
            preview, preview_blueprint = self._deserialize_preview_payload(dict(preview_payload["preview"]))
            if preview_blueprint is not None:
                preview_blueprint = self._apply_requested_preview_edits(preview_blueprint, request)
                preview = author_preview_from_blueprint(preview_blueprint)
            return preview, preview_blueprint
        preview_blueprint, _state = run_preview_blueprint_graph(request.prompt_seed, live_mode=self._run_mode())
        preview_blueprint = self._apply_requested_preview_edits(preview_blueprint, request)
        return author_preview_from_blueprint(preview_blueprint), preview_blueprint

    def create_job(self, request: AuthorJobCreateRequest, *, actor_user_id: str | None = None) -> AuthorJobStatusResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        preview, preview_blueprint = self._resolve_preview_for_job(request, actor_user_id=resolved_actor_user_id)
        job_id = str(uuid4())
        record = _ProductAuthorJobRecord(
            job_id=job_id,
            owner_user_id=resolved_actor_user_id,
            prompt_seed=request.prompt_seed,
            preview=preview,
            preview_blueprint=preview_blueprint,
            status="running",
            progress=self._progress_for_stage("running"),
        )
        with self._lock:
            record.condition = self._condition_for(job_id)
            self._save_record(record)
        self._emit_event(job_id, "job_created", self._build_status_event_payload(job_id))
        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return self.get_job(job_id, actor_user_id=resolved_actor_user_id)

    def get_job(self, job_id: str, *, actor_user_id: str | None = None) -> AuthorJobStatusResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._lock:
            record = self._get_record(job_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, resource="author_job", resource_id=job_id)
        return AuthorJobStatusResponse(
            job_id=record.job_id,
            status=record.status,  # type: ignore[arg-type]
            prompt_seed=record.prompt_seed,
            preview=record.preview,
            progress=record.progress,
            progress_snapshot=self._progress_snapshot(record),
            cache_metrics=record.cache_metrics,
            error=record.error,
        )

    def get_job_result(self, job_id: str, *, actor_user_id: str | None = None) -> AuthorJobResultResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._lock:
            record = self._get_record(job_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, resource="author_job", resource_id=job_id)
        return AuthorJobResultResponse(
            job_id=record.job_id,
            status=record.status,  # type: ignore[arg-type]
            summary=record.summary,
            bundle=record.bundle.model_dump(mode="json") if record.bundle is not None else None,
            progress_snapshot=self._progress_snapshot(record),
            cache_metrics=record.cache_metrics,
        )

    def get_publishable_job_source(self, job_id: str, *, actor_user_id: str | None = None) -> AuthorJobPublishSource:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._lock:
            record = self._get_record(job_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, resource="author_job", resource_id=job_id)
            if record.status != "completed" or record.summary is None or record.bundle is None:
                raise AuthorGatewayError(
                    code="author_job_not_publishable",
                    message=f"author job '{job_id}' is not completed and publishable",
                    status_code=409,
                )
            return AuthorJobPublishSource(
                source_job_id=record.job_id,
                owner_user_id=record.owner_user_id,
                prompt_seed=record.prompt_seed,
                preview=record.preview,
                summary=record.summary,
                bundle=record.bundle,
            )

    def get_job_diagnostics(self, job_id: str, *, actor_user_id: str | None = None) -> BenchmarkAuthorJobDiagnosticsResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._lock:
            record = self._get_record(job_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, resource="author_job", resource_id=job_id)
            token_usage = record.cache_metrics or summarize_cache_metrics(record.llm_call_trace)
        return BenchmarkAuthorJobDiagnosticsResponse(
            job_id=record.job_id,
            status=record.status,  # type: ignore[arg-type]
            prompt_seed=record.prompt_seed,
            created_at=record.created_at,
            updated_at=record.updated_at,
            finished_at=record.finished_at,
            summary=record.summary,
            error=record.error,
            cache_metrics=record.cache_metrics,
            token_cost_estimate=estimate_token_cost(token_usage),
            llm_call_trace=list(record.llm_call_trace),
            quality_trace=list(record.quality_trace),
            source_summary=dict(record.source_summary),
            stage_timings=self._build_stage_timings(record.events),
            events=self._build_diagnostic_events(record.events),
        )

    def stream_job_events(
        self,
        job_id: str,
        *,
        actor_user_id: str | None = None,
        last_event_id: int | None = None,
        heartbeat_seconds: float = 15.0,
    ):
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        cursor = last_event_id or 0
        while True:
            with self._lock:
                record = self._get_record(job_id)
                self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, resource="author_job", resource_id=job_id)
                pending = [event for event in record.events if event["id"] > cursor]
                terminal = record.status in {"completed", "failed"}
                condition = self._condition_for(job_id)
            if pending:
                for event in pending:
                    cursor = event["id"]
                    yield self._encode_sse_event(event)
                if terminal:
                    break
                continue
            if terminal:
                break
            with condition:
                notified = condition.wait(timeout=heartbeat_seconds)
            if not notified:
                yield ": keep-alive\n\n"

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            record = self._get_record(job_id)
            record.status = "running"
            record.progress = self._progress_for_stage("cast_planned")
            record.error = None
            record.updated_at = self._now()
            self._save_record(record)
        self._emit_event(job_id, "job_started", self._build_status_event_payload(job_id))
        try:
            self._emit_event(job_id, "stage_changed", self._build_status_event_payload(job_id))
            accepted_blueprint = apply_blueprint_edits(record.preview_blueprint)
            if self._settings.author_v3_enabled:
                self._run_job_v3(job_id, record, accepted_blueprint)
                return
            pipeline = run_author_play_graph(accepted_blueprint, live_mode=self._run_mode())  # type: ignore[arg-type]
            package = package_from_pipeline(
                preview_blueprint=record.preview_blueprint,
                accepted_blueprint=accepted_blueprint,
                pipeline=pipeline,
            )
            preview_failures = evaluate_preview_promise_gate(package)
            preservation_failures = evaluate_seed_preservation_gate(package)
            segment_failures = evaluate_segment_tension_gate(package)
            surface_failures = evaluate_surface_signal_readability(package)
            ending_failures = evaluate_ending_payoff_gate(package)
            quality_trace = list(package.quality_trace)
            quality_trace.extend(
                [
                    {
                        "stage": "preview_promise_gate",
                        "source": "relationship_drama_v2",
                        "outcome": "accepted" if not preview_failures else "failed",
                        "reasons": preview_failures,
                    },
                    {
                        "stage": "seed_preservation_gate",
                        "source": "relationship_drama_v2",
                        "outcome": "accepted" if not preservation_failures else "failed",
                        "reasons": preservation_failures,
                    },
                    {
                        "stage": "segment_tension_gate",
                        "source": "relationship_drama_v2",
                        "outcome": "accepted" if not segment_failures else "failed",
                        "reasons": segment_failures,
                    },
                    {
                        "stage": "surface_signal_readability_gate",
                        "source": "relationship_drama_v2",
                        "outcome": "accepted" if not surface_failures else "failed",
                        "reasons": surface_failures,
                    },
                    {
                        "stage": "ending_payoff_gate",
                        "source": "relationship_drama_v2",
                        "outcome": "accepted" if not ending_failures else "failed",
                        "reasons": ending_failures,
                    },
                ]
            )
            gate_failures = [*preview_failures, *preservation_failures, *segment_failures, *surface_failures, *ending_failures]
            summary = author_story_summary_from_package(package)
            cache_metrics = summarize_cache_metrics(package.llm_call_trace)
            with self._lock:
                current = self._get_record(job_id)
                current.preview = author_preview_from_blueprint(
                    package.preview_blueprint,
                    bound_cast=package.urban_bundle.bound_cast,
                    arc_template_id=package.urban_bundle.arc_template_id,
                )
                current.preview_blueprint = package.preview_blueprint
                current.summary = summary
                current.bundle = package
                current.llm_call_trace = list(package.llm_call_trace)
                current.quality_trace = quality_trace
                current.source_summary = {
                    "package_version": package.package_version,
                    "story_frame_source": "author_v2",
                    "beat_plan_source": "author_v2",
                    "route_affordance_source": "author_v2",
                    "ending_source": "author_v2",
                    "gameplay_semantics_source": "play_v2",
                    "preview_promise_gate": "accepted" if not preview_failures else "failed",
                    "seed_preservation_gate": "accepted" if not preservation_failures else "failed",
                    "segment_tension_gate": "accepted" if not segment_failures else "failed",
                    "surface_signal_readability_gate": "accepted" if not surface_failures else "failed",
                    "ending_payoff_gate": "accepted" if not ending_failures else "failed",
                }
                current.cache_metrics = cache_metrics
                current.updated_at = self._now()
                current.finished_at = self._now()
                if gate_failures:
                    current.status = "failed"
                    current.progress = self._progress_for_stage("failed")
                    current.error = {
                        "code": "author_quality_gate_failed",
                        "message": "; ".join(gate_failures[:8]),
                    }
                else:
                    current.status = "completed"
                    current.progress = self._progress_for_stage("completed")
                self._save_record(current)
            self._emit_event(job_id, "job_failed" if gate_failures else "job_completed", self._build_result_event_payload(job_id))
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                current = self._get_record(job_id)
                current.status = "failed"
                current.progress = self._progress_for_stage("failed")
                current.error = {
                    "code": "author_job_failed",
                    "message": str(exc),
                }
                current.updated_at = self._now()
                current.finished_at = self._now()
                self._save_record(current)
            self._emit_event(job_id, "job_failed", self._build_status_event_payload(job_id))

    def _run_job_v3(self, job_id: str, record: _ProductAuthorJobRecord, accepted_blueprint) -> None:
        from rpg_backend.author_v3.plan_bridge import package_from_v3_pipeline
        from rpg_backend.author_v3.workflow import run_author_v3_pipeline

        v3_result = run_author_v3_pipeline(
            record.prompt_seed,
            run_mode=self._run_mode(),
            settings=self._settings,
        )
        plan = v3_result["plan"]
        quality_report = v3_result["quality_report"]
        package = package_from_v3_pipeline(
            preview_blueprint=record.preview_blueprint,
            accepted_blueprint=accepted_blueprint,
            plan=plan,
        )
        summary = author_story_summary_from_package(package)
        quality_trace = list(package.quality_trace)
        quality_trace.append({
            "stage": "author_v3_quality_report",
            "source": "author_v3",
            "outcome": "accepted" if quality_report.passed else "failed",
            "overall_score": quality_report.overall_score,
            "weakest_dimension": quality_report.weakest_dimension,
        })
        with self._lock:
            current = self._get_record(job_id)
            current.preview = author_preview_from_blueprint(
                package.preview_blueprint,
                bound_cast=package.urban_bundle.bound_cast,
                arc_template_id=package.urban_bundle.arc_template_id,
            )
            current.preview_blueprint = package.preview_blueprint
            current.summary = summary
            current.bundle = package
            current.quality_trace = quality_trace
            current.source_summary = {
                "package_version": package.package_version,
                "story_frame_source": "author_v3",
                "beat_plan_source": "author_v3",
                "route_affordance_source": "author_v3",
                "ending_source": "author_v3",
                "gameplay_semantics_source": "play_v2",
                "author_v3_quality_passed": "yes" if quality_report.passed else "no",
            }
            current.updated_at = self._now()
            current.finished_at = self._now()
            if not quality_report.passed:
                current.status = "failed"
                current.progress = self._progress_for_stage("failed")
                current.error = {
                    "code": "author_v3_quality_gate_failed",
                    "message": quality_report.improvement_suggestion,
                }
            else:
                current.status = "completed"
                current.progress = self._progress_for_stage("completed")
            self._save_record(current)
        self._emit_event(
            job_id,
            "job_failed" if not quality_report.passed else "job_completed",
            self._build_result_event_payload(job_id),
        )

    def _reconcile_interrupted_jobs(self) -> None:
        for payload in self._storage.list_jobs():
            if payload.get("status") not in {"queued", "running"}:
                continue
            record = self._deserialize_job_record(payload)
            with self._lock:
                record.condition = self._condition_for(record.job_id)
                self._save_record(record)
            thread = threading.Thread(target=self._run_job, args=(record.job_id,), daemon=True)
            thread.start()

    @staticmethod
    def _encode_sse_event(event: dict[str, Any]) -> str:
        return (
            f"id: {event['id']}\n"
            f"event: {event['event']}\n"
            f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        )

    @staticmethod
    def _build_diagnostic_events(events: list[dict[str, Any]]) -> list[BenchmarkAuthorJobEvent]:
        payloads: list[BenchmarkAuthorJobEvent] = []
        for event in events:
            progress = dict(event.get("data", {}).get("progress") or {})
            payloads.append(
                BenchmarkAuthorJobEvent(
                    id=int(event["id"]),
                    event=str(event["event"]),
                    emitted_at=event["emitted_at"],
                    status=event.get("data", {}).get("status"),
                    stage=progress.get("stage"),
                    stage_index=progress.get("stage_index"),
                    stage_total=progress.get("stage_total"),
                )
            )
        return payloads

    @staticmethod
    def _build_stage_timings(events: list[dict[str, Any]]) -> list[BenchmarkStageTiming]:
        stage_events: list[tuple[str, datetime]] = []
        for event in events:
            progress = dict(event.get("data", {}).get("progress") or {})
            stage = progress.get("stage")
            emitted_at = event.get("emitted_at")
            if not isinstance(stage, str) or not isinstance(emitted_at, datetime):
                continue
            if stage_events and stage_events[-1][0] == stage:
                continue
            stage_events.append((stage, emitted_at))
        timings: list[BenchmarkStageTiming] = []
        for index, (stage, started_at) in enumerate(stage_events):
            ended_at = stage_events[index + 1][1] if index + 1 < len(stage_events) else None
            elapsed_ms = max(int((ended_at - started_at).total_seconds() * 1000), 0) if ended_at is not None else None
            timings.append(
                BenchmarkStageTiming(
                    stage=stage,
                    started_at=started_at,
                    ended_at=ended_at,
                    elapsed_ms=elapsed_ms,
                )
            )
        return timings
