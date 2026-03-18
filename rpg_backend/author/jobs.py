from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from rpg_backend.author.checkpointer import graph_config
from rpg_backend.author.contracts import (
    AuthorCacheMetrics,
    AuthorJobCreateRequest,
    AuthorJobProgress,
    AuthorJobResultResponse,
    AuthorJobStatusResponse,
    AuthorPreviewRequest,
    AuthorPreviewResponse,
)
from rpg_backend.author.display import (
    build_progress_snapshot,
)
from rpg_backend.author.gateway import get_author_llm_gateway
from rpg_backend.author.metrics import (
    estimate_token_cost,
    summarize_cache_metrics,
)
from rpg_backend.author.preview import build_author_preview_from_seed, build_author_story_summary, build_generation_state_from_preview
from rpg_backend.author.workflow import build_author_graph

PUBLIC_STAGE_FLOW = [
    ("focus_brief", "brief_parsed"),
    ("plan_brief_theme", "brief_classified"),
    ("generate_story_frame", "story_frame_ready"),
    ("plan_story_theme", "theme_confirmed"),
    ("derive_cast_overview", "cast_planned"),
    ("generate_cast_members", "cast_ready"),
    ("generate_beat_plan", "beat_plan_ready"),
    ("compile_route_affordance_pack", "route_ready"),
    ("generate_ending_rules", "ending_ready"),
    ("merge_rule_pack", "completed"),
]

STAGE_INDEX_BY_NODE = {
    node_name: index + 1
    for index, (node_name, _public_stage) in enumerate(PUBLIC_STAGE_FLOW)
}

PUBLIC_STAGE_BY_NODE = {
    node_name: public_stage
    for node_name, public_stage in PUBLIC_STAGE_FLOW
}


@dataclass
class _AuthorJobRecord:
    job_id: str
    prompt_seed: str
    preview: AuthorPreviewResponse
    status: str
    progress: AuthorJobProgress
    cache_metrics: AuthorCacheMetrics | None = None
    llm_call_trace: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=threading.Condition)
    bundle: Any = None
    summary: Any = None
    error: dict[str, str] | None = None


class AuthorJobService:
    def __init__(self) -> None:
        self._jobs: dict[str, _AuthorJobRecord] = {}
        self._previews: dict[str, AuthorPreviewResponse] = {}
        self._lock = threading.Lock()

    def create_preview(self, request: AuthorPreviewRequest | AuthorJobCreateRequest) -> AuthorPreviewResponse:
        preview = build_author_preview_from_seed(request.prompt_seed)
        with self._lock:
            self._previews[preview.preview_id] = preview
        return preview

    def create_job(self, request: AuthorJobCreateRequest) -> AuthorJobStatusResponse:
        with self._lock:
            preview = self._previews.get(request.preview_id) if request.preview_id else None
        if preview is None:
            preview = build_author_preview_from_seed(request.prompt_seed)
        job_id = str(uuid4())
        record = _AuthorJobRecord(
            job_id=job_id,
            prompt_seed=request.prompt_seed,
            preview=preview,
            status="queued",
            progress=AuthorJobProgress(stage="queued", stage_index=1, stage_total=len(PUBLIC_STAGE_FLOW)),
        )
        with self._lock:
            self._jobs[job_id] = record
        self._emit_event(job_id, "job_created", self._build_status_event_payload(job_id))
        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> AuthorJobStatusResponse:
        with self._lock:
            record = self._jobs[job_id]
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

    def get_job_result(self, job_id: str) -> AuthorJobResultResponse:
        with self._lock:
            record = self._jobs[job_id]
            return AuthorJobResultResponse(
                job_id=record.job_id,
                status=record.status,  # type: ignore[arg-type]
                summary=record.summary,
                bundle=record.bundle,
                progress_snapshot=self._progress_snapshot(record),
                cache_metrics=record.cache_metrics,
            )

    def stream_job_events(
        self,
        job_id: str,
        *,
        last_event_id: int | None = None,
        heartbeat_seconds: float = 15.0,
    ):
        cursor = last_event_id or 0
        while True:
            with self._lock:
                record = self._jobs[job_id]
                pending = [event for event in record.events if event["id"] > cursor]
                terminal = record.status in {"completed", "failed"}
                condition = record.condition
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
            record = self._jobs[job_id]
            record.status = "running"
            record.progress = AuthorJobProgress(
                stage="running",
                stage_index=1,
                stage_total=len(PUBLIC_STAGE_FLOW),
            )
            record.cache_metrics = summarize_cache_metrics(None)
            record.llm_call_trace = []
        self._emit_event(job_id, "job_started", self._build_status_event_payload(job_id))
        gateway = None
        try:
            gateway = get_author_llm_gateway()
            graph = build_author_graph(gateway=gateway)
            config = graph_config(run_id=job_id)
            for update in graph.stream(
                {
                    "run_id": job_id,
                    "raw_brief": record.prompt_seed,
                    **build_generation_state_from_preview(record.preview),
                },
                config=config,
                stream_mode="updates",
            ):
                node_name = next(iter(update.keys()))
                if node_name not in PUBLIC_STAGE_BY_NODE:
                    continue
                public_stage = PUBLIC_STAGE_BY_NODE[node_name]
                stage_index = STAGE_INDEX_BY_NODE[node_name]
                with self._lock:
                    current = self._jobs[job_id]
                    current.progress = AuthorJobProgress(
                        stage=public_stage,
                        stage_index=stage_index,
                        stage_total=len(PUBLIC_STAGE_FLOW),
                    )
                    current.llm_call_trace = list(gateway.call_trace)
                    current.cache_metrics = summarize_cache_metrics(current.llm_call_trace)
                self._emit_event(job_id, "stage_changed", self._build_status_event_payload(job_id))
            snapshot = graph.get_state(config)
            state = snapshot.values
            bundle = state["design_bundle"]
            summary = build_author_story_summary(
                bundle,
                primary_theme=state.get("primary_theme") or record.preview.theme.primary_theme,
            )
            cache_metrics = summarize_cache_metrics(
                list(gateway.call_trace) if hasattr(gateway, "call_trace") else state.get("llm_call_trace")
            )
            with self._lock:
                current = self._jobs[job_id]
                current.status = "completed"
                current.progress = AuthorJobProgress(
                    stage="completed",
                    stage_index=len(PUBLIC_STAGE_FLOW),
                    stage_total=len(PUBLIC_STAGE_FLOW),
                )
                current.bundle = bundle
                current.summary = summary
                current.llm_call_trace = list(gateway.call_trace)
                current.cache_metrics = cache_metrics
            self._emit_event(job_id, "job_completed", self._build_result_event_payload(job_id))
        except Exception as exc:  # noqa: BLE001
            llm_call_trace = list(gateway.call_trace) if gateway is not None else []
            cache_metrics = summarize_cache_metrics(llm_call_trace)
            with self._lock:
                current = self._jobs[job_id]
                current.status = "failed"
                current.error = {
                    "code": "author_job_failed",
                    "message": str(exc),
                }
                current.progress = AuthorJobProgress(
                    stage="failed",
                    stage_index=len(PUBLIC_STAGE_FLOW),
                    stage_total=len(PUBLIC_STAGE_FLOW),
                )
                current.llm_call_trace = llm_call_trace
                current.cache_metrics = cache_metrics
            self._emit_event(job_id, "job_failed", self._build_status_event_payload(job_id))

    @staticmethod
    def _encode_sse_event(event: dict[str, Any]) -> str:
        return (
            f"id: {event['id']}\n"
            f"event: {event['event']}\n"
            f"data: {event['data']}\n\n"
        )

    @staticmethod
    def _dump_value(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    def _build_token_snapshot_payload(self, record: _AuthorJobRecord) -> dict[str, Any]:
        token_usage = record.cache_metrics or summarize_cache_metrics(record.llm_call_trace)
        token_cost_estimate = estimate_token_cost(token_usage)
        return {
            "token_usage": token_usage.model_dump(mode="json"),
            "token_cost_estimate": token_cost_estimate.model_dump(mode="json") if token_cost_estimate else None,
        }

    def _progress_snapshot(self, record: _AuthorJobRecord):
        token_usage = record.cache_metrics or summarize_cache_metrics(record.llm_call_trace)
        return build_progress_snapshot(
            preview=record.preview,
            progress=record.progress,
            token_usage=token_usage,
            token_cost_estimate=estimate_token_cost(token_usage),
        )

    def _build_status_event_payload(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._jobs[job_id]
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
            record = self._jobs[job_id]
            payload = {
                "job_id": record.job_id,
                "status": record.status,
                "summary": self._dump_value(record.summary),
                "bundle": self._dump_value(record.bundle),
                "cache_metrics": record.cache_metrics.model_dump(mode="json") if record.cache_metrics else None,
                "progress_snapshot": self._progress_snapshot(record).model_dump(mode="json"),
            }
            payload.update(self._build_token_snapshot_payload(record))
            return payload

    def _emit_event(self, job_id: str, event_name: str, payload: dict[str, Any]) -> None:
        with self._lock:
            record = self._jobs[job_id]
            event_id = len(record.events) + 1
            event = {
                "id": event_id,
                "event": event_name,
                "data": payload,
            }
            record.events.append(event)
            condition = record.condition
        with condition:
            condition.notify_all()
