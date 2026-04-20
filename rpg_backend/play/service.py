from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from threading import Lock
from time import perf_counter
import tempfile
from typing import Any, Callable, Literal
from uuid import uuid4
from pydantic import ValidationError

from rpg_backend.author.contracts import RouteUnlockRule
from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.benchmark.contracts import (
    BenchmarkPlaySessionDiagnosticsResponse,
    BenchmarkPlayTraceSummary,
)
from rpg_backend.config import Settings, get_settings
from rpg_backend.library.service import StoryLibraryService
from rpg_backend.play.storage import SQLitePlaySessionStorage
from rpg_backend.play.closeout import (
    EndingJudgeResult,
    PyrrhicCriticResult,
    finalize_turn_ending,
    judge_eligible,
    judge_ending_intent,
    run_pyrrhic_critic,
)
from rpg_backend.play.contracts import (
    PlayDraftIntentPreview,
    PlayDraftIntentRequest,
    PlayDraftIntentResponse,
    PlayPlan,
    PlaySessionHistoryEntry,
    PlaySessionHistoryResponse,
    PlaySessionSnapshot,
    PlaySuggestedAction,
    PlayEnding,
    PlayTurnTrace,
    PlayTurnRequest,
)
from rpg_backend.play.gateway import PlayGatewayError, PlayLLMGateway, get_play_llm_gateway
from rpg_backend.play.runtime import (
    apply_turn_resolution,
    PlaySessionState,
    build_initial_session_state,
    build_session_snapshot,
)
from rpg_backend.play.relationship_runtime import (
    RelationshipJudgeResult,
    apply_relationship_judged_ending,
    build_relationship_session_snapshot,
    heuristic_relationship_turn_intent,
    is_relationship_drama_plan,
    judge_relationship_drama_ending,
    render_relationship_turn,
)
from rpg_backend.play.stages import (
    interpret_turn,
    render_turn,
)
from rpg_backend.play_v2.contracts import UrbanWorldState
from rpg_backend.play_v2.product_api import build_v2_snapshot, build_v2_turn_trace
from rpg_backend.play_v2.delta_pack_runtime import clear_delta_pack_future
from rpg_backend.play_v2.runtime import (
    build_control_actions as build_v2_control_actions,
    build_initial_world_state,
    run_intent_stage as run_v2_intent_stage,
    run_speculative_compose_prewarm as run_v2_speculative_compose_prewarm,
    build_suggested_actions as build_v2_suggested_actions,
    run_turn as run_v2_turn,
)
from rpg_backend.play.session_handlers import LegacyPlaySessionHandler, V2PlaySessionHandler

URBAN_V2_STATE_SCHEMA_VERSION = "urban_v2_20260406_super_flagship_v4"
URBAN_PLAN_CONTRACT_VERSIONS = {4, 5}
_DRAFT_INTENT_TTL_SECONDS = 75
_DRAFT_INTENT_MAX_ENTRIES_PER_SESSION = 24
_SPEC_COMPOSE_TTL_SECONDS = 90
_SPEC_COMPOSE_PENDING_WAIT_MS_FREE_INPUT = 10
_SPEC_COMPOSE_PENDING_WAIT_MS_SELECT_ID_IDLE = 200
_SPEC_COMPOSE_PENDING_WAIT_MS_SELECT_ID_BUSY = 100
_SPEC_COMPOSE_MAX_ENTRIES_PER_SESSION = 36
_SPEC_COMPOSE_EXECUTOR_MAX_WORKERS = 6
_SPEC_COMPOSE_MAX_INFLIGHT = 8
_SPEC_COMPOSE_READ_PHASE_TOP_K = 1
_SPEC_COMPOSE_TYPING_MIN_TEXT_LEN = 18
_SPEC_COMPOSE_TYPING_HIGH_VALUE_MOVES = frozenset({"accuse", "public_reveal", "betray", "probe_secret"})
_SPEC_COMPOSE_KEY_SEGMENT_ROLES = frozenset({"pressure", "reversal", "reveal", "terminal"})
_SPEC_COMPOSE_PREWARM_ENABLED = False
_NORMALIZE_SPACES_RE = re.compile(r"\s+")


class PlayServiceError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class _PlaySessionRecord:
    owner_user_id: str
    runtime_kind: Literal["v2", "legacy"]
    plan: PlayPlan | CompiledPlayPlan
    state: PlaySessionState | UrbanWorldState
    created_at: datetime
    expires_at: datetime
    finished_at: datetime | None
    history: list[PlaySessionHistoryEntry]
    turn_traces: list[PlayTurnTrace]


@dataclass
class _DraftIntentEntry:
    draft_intent_id: str
    session_id: str
    turn_index: int
    state_snapshot_id: str
    normalized_text_hash: str
    is_final_draft: bool
    typing_scope_cleared_count: int
    intent: Any
    micro_sim: Any
    diagnostics: dict[str, Any]
    usage: dict[str, int]
    expires_at: datetime


@dataclass
class _PrewarmBundle:
    session_id: str
    turn_index: int
    state_snapshot_id: str
    suggested_actions: tuple[Any, ...]
    control_actions: tuple[Any, ...]
    created_at: datetime


@dataclass(frozen=True)
class _SpecComposeCacheKey:
    session_id: str
    turn_index: int
    state_snapshot_id: str
    normalized_text_hash: str


@dataclass
class _SpecComposeResult:
    key: _SpecComposeCacheKey
    source: str
    narration: str
    diagnostics: dict[str, int | float | str | bool]
    compose_input_tokens: int
    compose_output_tokens: int
    compose_total_tokens: int
    expires_at: datetime
    failed_reason: str = ""


@dataclass
class _SpecComposeFutureEntry:
    key: _SpecComposeCacheKey
    source: str
    generation: int
    future: Future[_SpecComposeResult]
    expires_at: datetime
    started_at: float


class PlaySessionService:
    def __init__(
        self,
        *,
        story_library_service: StoryLibraryService,
        gateway_factory: Callable[[Settings | None], PlayLLMGateway] = get_play_llm_gateway,
        settings: Settings | None = None,
        now_provider: Callable[[], datetime] | None = None,
        enable_turn_telemetry: bool = True,
        enable_interpret_repair: bool = True,
        enable_render_repair: bool = True,
        use_tuned_ending_policy: bool = True,
        enable_ending_intent_judge: bool = True,
        enable_pyrrhic_judge_relaxation: bool = True,
        storage: SQLitePlaySessionStorage | None = None,
    ) -> None:
        self._story_library_service = story_library_service
        self._gateway_factory = gateway_factory
        self._settings = settings or get_settings()
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._storage = storage or SQLitePlaySessionStorage(
            self._settings.runtime_state_db_path
            if settings is not None
            else f"{tempfile.gettempdir()}/rpg_demo_play_sessions_{uuid4()}.sqlite3"
        )
        self._lock = Lock()
        self._session_locks: dict[str, Lock] = {}
        self._sessions: dict[str, _PlaySessionRecord] = {}
        self._draft_intents_by_id: dict[str, _DraftIntentEntry] = {}
        self._draft_intent_lookup: dict[tuple[str, int, str, str], str] = {}
        self._draft_intent_ids_by_session: dict[str, list[str]] = {}
        self._prewarm_bundles: dict[str, _PrewarmBundle] = {}
        self._spec_compose_cache: dict[_SpecComposeCacheKey, _SpecComposeResult] = {}
        self._spec_compose_futures: dict[_SpecComposeCacheKey, _SpecComposeFutureEntry] = {}
        self._spec_compose_session_keys: dict[str, list[_SpecComposeCacheKey]] = {}
        self._spec_compose_latest_generation: dict[tuple[str, int, str], int] = {}
        self._spec_compose_executor: ThreadPoolExecutor | None = None
        self._enable_turn_telemetry = enable_turn_telemetry
        self._enable_interpret_repair = enable_interpret_repair
        self._enable_render_repair = enable_render_repair
        self._use_tuned_ending_policy = use_tuned_ending_policy
        self._enable_ending_intent_judge = enable_ending_intent_judge
        self._enable_pyrrhic_judge_relaxation = enable_pyrrhic_judge_relaxation

    def _now(self) -> datetime:
        return self._now_provider()

    @staticmethod
    def _serialize_state(state: PlaySessionState) -> dict[str, object]:
        if isinstance(state, UrbanWorldState):
            return {
                "state_kind": "urban_v2",
                "schema_version": URBAN_V2_STATE_SCHEMA_VERSION,
                "payload": state.model_dump(mode="json"),
            }
        return {
            "state_kind": "legacy",
            "payload": {
            "session_id": state.session_id,
            "story_id": state.story_id,
            "status": state.status,
            "turn_index": state.turn_index,
            "beat_index": state.beat_index,
            "beat_progress": state.beat_progress,
            "beat_detours_used": state.beat_detours_used,
            "axis_values": dict(state.axis_values),
            "stance_values": dict(state.stance_values),
            "flag_values": dict(state.flag_values),
            "discovered_truth_ids": list(state.discovered_truth_ids),
            "discovered_event_ids": list(state.discovered_event_ids),
            "success_ledger": dict(state.success_ledger),
            "cost_ledger": dict(state.cost_ledger),
            "last_turn_axis_deltas": dict(state.last_turn_axis_deltas),
            "last_turn_stance_deltas": dict(state.last_turn_stance_deltas),
            "last_turn_tags": list(state.last_turn_tags),
            "last_turn_consequences": list(state.last_turn_consequences),
            "narration": state.narration,
            "suggested_actions": [item.model_dump(mode="json") for item in state.suggested_actions],
            "ending": state.ending.model_dump(mode="json") if state.ending is not None else None,
            "session_response_id": state.session_response_id,
            "collapse_pressure_streak": state.collapse_pressure_streak,
            "primary_axis_history": list(state.primary_axis_history),
            "negative_stance_history": list(state.negative_stance_history),
            "scene_heat": state.scene_heat,
            "public_image": state.public_image,
            "secret_exposure": state.secret_exposure,
            "route_lock": state.route_lock,
            "current_route_target_id": state.current_route_target_id,
            "relationship_values": {key: dict(value) for key, value in state.relationship_values.items()},
            "known_secret_ids": list(state.known_secret_ids),
            "public_event_ids": list(state.public_event_ids),
            "private_scene_ids": list(state.private_scene_ids),
            "promise_ids": list(state.promise_ids),
            "betrayal_ids": list(state.betrayal_ids),
            "last_turn_global_deltas": dict(state.last_turn_global_deltas),
            "last_turn_relationship_deltas": {key: dict(value) for key, value in state.last_turn_relationship_deltas.items()},
            "last_turn_revealed_secret_ids": list(state.last_turn_revealed_secret_ids),
            },
        }

    @staticmethod
    def _deserialize_state(payload: dict[str, object]) -> PlaySessionState | UrbanWorldState:
        if str(payload.get("state_kind") or "legacy") == "urban_v2":
            return UrbanWorldState.model_validate(payload.get("payload") or {})
        payload = dict(payload.get("payload") or payload)
        return PlaySessionState(
            session_id=str(payload["session_id"]),
            story_id=str(payload["story_id"]),
            status=str(payload["status"]),
            turn_index=int(payload["turn_index"]),
            beat_index=int(payload["beat_index"]),
            beat_progress=int(payload["beat_progress"]),
            beat_detours_used=int(payload["beat_detours_used"]),
            axis_values=dict(payload.get("axis_values") or {}),
            stance_values=dict(payload.get("stance_values") or {}),
            flag_values=dict(payload.get("flag_values") or {}),
            discovered_truth_ids=list(payload.get("discovered_truth_ids") or []),
            discovered_event_ids=list(payload.get("discovered_event_ids") or []),
            success_ledger=dict(payload.get("success_ledger") or {}),
            cost_ledger=dict(payload.get("cost_ledger") or {}),
            last_turn_axis_deltas=dict(payload.get("last_turn_axis_deltas") or {}),
            last_turn_stance_deltas=dict(payload.get("last_turn_stance_deltas") or {}),
            last_turn_tags=list(payload.get("last_turn_tags") or []),
            last_turn_consequences=list(payload.get("last_turn_consequences") or []),
            narration=str(payload.get("narration") or ""),
            suggested_actions=[PlaySuggestedAction.model_validate(item) for item in (payload.get("suggested_actions") or [])],
            ending=PlayEnding.model_validate(payload["ending"]) if payload.get("ending") is not None else None,
            session_response_id=str(payload["session_response_id"]) if payload.get("session_response_id") else None,
            collapse_pressure_streak=int(payload.get("collapse_pressure_streak") or 0),
            primary_axis_history=list(payload.get("primary_axis_history") or []),
            negative_stance_history=list(payload.get("negative_stance_history") or []),
            scene_heat=int(payload.get("scene_heat") or 0),
            public_image=int(payload.get("public_image") or 0),
            secret_exposure=int(payload.get("secret_exposure") or 0),
            route_lock=int(payload.get("route_lock") or 0),
            current_route_target_id=str(payload["current_route_target_id"]) if payload.get("current_route_target_id") else None,
            relationship_values={
                str(key): {str(inner_key): int(inner_value) for inner_key, inner_value in dict(value).items()}
                for key, value in dict(payload.get("relationship_values") or {}).items()
            },
            known_secret_ids=list(payload.get("known_secret_ids") or []),
            public_event_ids=list(payload.get("public_event_ids") or []),
            private_scene_ids=list(payload.get("private_scene_ids") or []),
            promise_ids=list(payload.get("promise_ids") or []),
            betrayal_ids=list(payload.get("betrayal_ids") or []),
            last_turn_global_deltas=dict(payload.get("last_turn_global_deltas") or {}),
            last_turn_relationship_deltas={
                str(key): {str(inner_key): int(inner_value) for inner_key, inner_value in dict(value).items()}
                for key, value in dict(payload.get("last_turn_relationship_deltas") or {}).items()
            },
            last_turn_revealed_secret_ids=list(payload.get("last_turn_revealed_secret_ids") or []),
        )

    def _serialize_record(self, record: _PlaySessionRecord) -> dict[str, object]:
        return {
            "session_id": record.state.session_id,
            "owner_user_id": record.owner_user_id,
            "runtime_kind": record.runtime_kind,
            "story_id": record.plan.story_id,
            "created_at": record.created_at.isoformat(),
            "expires_at": record.expires_at.isoformat(),
            "finished_at": record.finished_at.isoformat() if record.finished_at is not None else None,
            "plan_kind": "urban_v2" if isinstance(record.plan, CompiledPlayPlan) else "legacy",
            "plan": record.plan.model_dump(mode="json"),
            "state": self._serialize_state(record.state),
            "history": [entry.model_dump(mode="json") for entry in record.history],
            "turn_traces": [trace.model_dump(mode="json") for trace in record.turn_traces],
        }

    def _deserialize_record(self, payload: dict[str, object]) -> _PlaySessionRecord:
        plan_payload = dict(payload["plan"])
        plan_kind = str(payload.get("plan_kind") or "")
        if not plan_kind:
            # Older storage rows only persist `plan` payload; infer v2 shape directly.
            if {"template_id", "segments", "ending_matrix"}.issubset(set(plan_payload.keys())):
                plan_kind = "urban_v2"
            else:
                plan_kind = "legacy"
        if plan_kind == "urban_v2":
            try:
                parsed_plan = CompiledPlayPlan.model_validate(plan_payload)
            except ValidationError as exc:
                raise PlayServiceError(
                    code="play_plan_version_unsupported",
                    message="This play plan was compiled by an older contract and can no longer be resumed. Please recompile the story and start a new session.",
                    status_code=409,
                ) from exc
            if int(getattr(parsed_plan, "delta_pack_contract_version", 0) or 0) not in URBAN_PLAN_CONTRACT_VERSIONS:
                raise PlayServiceError(
                    code="play_plan_version_unsupported",
                    message="This play plan uses an unsupported delta-pack contract version. Please recompile the story and start a new session.",
                    status_code=409,
                )
            plan = parsed_plan
        else:
            route_unlock_rules = [
                RouteUnlockRule.model_validate(item)
                for item in (plan_payload.get("route_unlock_rules") or [])
            ]
            plan_payload["route_unlock_rules"] = [rule.model_dump(mode="json") for rule in route_unlock_rules]
            legacy_plan = PlayPlan.model_validate(plan_payload)
            legacy_plan.route_unlock_rules = route_unlock_rules  # type: ignore[assignment]
            plan = legacy_plan
        state_payload = dict(payload["state"])
        if str(state_payload.get("state_kind") or "legacy") == "urban_v2":
            schema_version = str(state_payload.get("schema_version") or "").strip()
            if schema_version != URBAN_V2_STATE_SCHEMA_VERSION:
                raise PlayServiceError(
                    code="play_session_version_unsupported",
                    message="This play session was created by an older runtime version and can no longer be resumed. Please start a new session.",
                    status_code=409,
                )
        return _PlaySessionRecord(
            owner_user_id=str(payload["owner_user_id"]),
            runtime_kind=(
                "v2"
                if str(payload.get("runtime_kind") or "").strip() == "v2"
                else ("v2" if isinstance(plan, CompiledPlayPlan) else "legacy")
            ),
            plan=plan,
            state=self._deserialize_state(state_payload),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            finished_at=datetime.fromisoformat(str(payload["finished_at"])) if payload.get("finished_at") else None,
            history=[PlaySessionHistoryEntry.model_validate(item) for item in (payload.get("history") or [])],
            turn_traces=[PlayTurnTrace.model_validate(item) for item in (payload.get("turn_traces") or [])],
        )

    def _save_record(self, record: _PlaySessionRecord) -> None:
        with self._lock:
            self._sessions[record.state.session_id] = record
        self._storage.save_session(self._serialize_record(record))

    def _session_lock_for(self, session_id: str) -> Lock:
        with self._lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = Lock()
                self._session_locks[session_id] = lock
            return lock

    @staticmethod
    def _ensure_owner_access(owner_user_id: str, actor_user_id: str, *, session_id: str) -> None:
        if owner_user_id == actor_user_id:
            return
        raise PlayServiceError(
            code="play_session_not_found",
            message=f"play session '{session_id}' was not found",
            status_code=404,
        )

    def _resolve_gateway(self) -> PlayLLMGateway | None:
        try:
            return self._gateway_factory(self._settings)
        except PlayGatewayError:
            return None

    @staticmethod
    def _normalize_draft_text(input_text: str) -> str:
        return _NORMALIZE_SPACES_RE.sub(" ", str(input_text or "")).strip().casefold()

    @classmethod
    def _normalized_text_hash(cls, input_text: str) -> str:
        normalized = cls._normalize_draft_text(input_text)
        payload = normalized.encode("utf-8")
        return hashlib.sha1(payload).hexdigest()[:32] if payload else "0" * 32

    @staticmethod
    def _state_snapshot_id(state: UrbanWorldState) -> str:
        snapshot_payload = {
            "turn_index": int(state.turn_index),
            "segment_index": int(state.segment_index),
            "segment_id": str(state.segment_id),
            "scene_heat": int(state.scene_heat),
            "secret_exposure": int(state.secret_exposure),
            "route_lock": int(state.route_lock),
            "current_route_target_id": str(state.current_route_target_id or ""),
            "known_secret_ids": list(state.known_secret_ids),
            "active_character_ids": list(state.active_character_ids),
            "status": str(state.status),
        }
        raw = json.dumps(snapshot_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _diag_int(diagnostics: dict[str, Any], key: str) -> int:
        value = diagnostics.get(key, 0)
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return max(int(round(float(value))), 0)
        return 0

    @classmethod
    def _draft_usage_from_diagnostics(cls, diagnostics: dict[str, Any]) -> dict[str, int]:
        input_tokens = cls._diag_int(diagnostics, "intent_stage_input_tokens")
        output_tokens = cls._diag_int(diagnostics, "intent_stage_output_tokens")
        if input_tokens <= 0:
            input_tokens = cls._diag_int(diagnostics, "intent_llm_input_tokens") + cls._diag_int(
                diagnostics, "micro_sim_input_tokens"
            )
        if output_tokens <= 0:
            output_tokens = cls._diag_int(diagnostics, "intent_llm_output_tokens") + cls._diag_int(
                diagnostics, "micro_sim_output_tokens"
            )
        total_tokens = cls._diag_int(diagnostics, "intent_stage_total_tokens")
        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens
        return {
            "input_tokens": max(input_tokens, 0),
            "output_tokens": max(output_tokens, 0),
            "total_tokens": max(total_tokens, 0),
        }

    @staticmethod
    def _sanitize_scalar_diagnostics(diagnostics: dict[str, Any]) -> dict[str, int | float | str | bool]:
        sanitized: dict[str, int | float | str | bool] = {}
        for key, value in dict(diagnostics or {}).items():
            if isinstance(value, bool):
                sanitized[str(key)] = value
            elif isinstance(value, (int, float, str)):
                sanitized[str(key)] = value
        return sanitized

    def _spec_compose_executor_instance(self) -> ThreadPoolExecutor:
        if self._spec_compose_executor is None:
            self._spec_compose_executor = ThreadPoolExecutor(
                max_workers=_SPEC_COMPOSE_EXECUTOR_MAX_WORKERS,
                thread_name_prefix="spec-compose",
            )
        return self._spec_compose_executor

    def _spec_compose_prewarm_enabled(self) -> bool:
        if not _SPEC_COMPOSE_PREWARM_ENABLED:
            return False
        return bool(getattr(self._settings, "play_v2_spec_compose_prewarm_enabled", False))

    def _spec_compose_inflight_count(self) -> int:
        return sum(1 for entry in self._spec_compose_futures.values() if not entry.future.done())

    def _spec_compose_backpressure_active(self) -> bool:
        return self._spec_compose_inflight_count() >= _SPEC_COMPOSE_MAX_INFLIGHT

    @staticmethod
    def _current_segment_role(plan: CompiledPlayPlan, state: UrbanWorldState) -> str:
        if not plan.segments:
            return ""
        index = min(max(int(state.segment_index), 0), len(plan.segments) - 1)
        segment = plan.segments[index]
        return str(segment.segment_role or "")

    def _should_schedule_typing_phase_prewarm(
        self,
        *,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        intent: Any,
        input_text: str,
        diagnostics: dict[str, Any] | None,
    ) -> bool:
        normalized_text = _NORMALIZE_SPACES_RE.sub(" ", str(input_text or "")).strip()
        if len(normalized_text) < _SPEC_COMPOSE_TYPING_MIN_TEXT_LEN:
            return False
        move_family = str(getattr(intent, "move_family", "") or "").strip()
        compile_source = str(getattr(intent, "intent_compile_source", "") or "").strip()
        intent_confidence = getattr(intent, "intent_confidence", 0.0)
        try:
            confidence = float(intent_confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if diagnostics and compile_source == "":
            compile_source = str(diagnostics.get("intent_compile_source") or "").strip()
        segment_role = self._current_segment_role(plan, state)
        high_value = move_family in _SPEC_COMPOSE_TYPING_HIGH_VALUE_MOVES
        risky_segment = segment_role in _SPEC_COMPOSE_KEY_SEGMENT_ROLES
        risky_state = (
            int(state.scene_heat) >= 4
            or int(state.secret_exposure) >= 3
            or int(state.route_lock) >= 3
        )
        ambiguous = compile_source == "heuristic_fallback" or confidence <= 0.62
        return high_value or (ambiguous and (risky_segment or risky_state))

    def _should_schedule_read_phase_prewarm(
        self,
        *,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        previous_turn_select_id: bool,
    ) -> bool:
        if not previous_turn_select_id:
            return False
        segment_role = self._current_segment_role(plan, state)
        if segment_role in _SPEC_COMPOSE_KEY_SEGMENT_ROLES:
            return True
        return (
            int(state.scene_heat) >= 5
            or int(state.secret_exposure) >= 4
            or int(state.route_lock) >= 4
        )

    def _submit_spec_compose_pending_wait_seconds(self, *, has_selected_ids: bool) -> float:
        if not has_selected_ids:
            wait_ms = _SPEC_COMPOSE_PENDING_WAIT_MS_FREE_INPUT
        else:
            wait_ms = (
                _SPEC_COMPOSE_PENDING_WAIT_MS_SELECT_ID_BUSY
                if self._spec_compose_backpressure_active()
                else _SPEC_COMPOSE_PENDING_WAIT_MS_SELECT_ID_IDLE
            )
        return max(wait_ms / 1000.0, 0.01)

    def _evict_spec_compose_key(self, key: _SpecComposeCacheKey, *, cancel_future: bool = False) -> None:
        self._spec_compose_cache.pop(key, None)
        future_entry = self._spec_compose_futures.pop(key, None)
        if cancel_future and future_entry is not None:
            future_entry.future.cancel()
        session_keys = self._spec_compose_session_keys.get(key.session_id)
        if session_keys is not None:
            self._spec_compose_session_keys[key.session_id] = [item for item in session_keys if item != key]
            if not self._spec_compose_session_keys[key.session_id]:
                self._spec_compose_session_keys.pop(key.session_id, None)

    def _register_spec_compose_key(self, key: _SpecComposeCacheKey) -> None:
        queue = self._spec_compose_session_keys.setdefault(key.session_id, [])
        if key not in queue:
            queue.append(key)
        while len(queue) > _SPEC_COMPOSE_MAX_ENTRIES_PER_SESSION:
            stale_key = queue.pop(0)
            self._evict_spec_compose_key(stale_key, cancel_future=True)

    def _purge_expired_spec_compose(self, *, now: datetime | None = None) -> None:
        current = now or self._now()
        expired_cache_keys = [
            key
            for key, result in self._spec_compose_cache.items()
            if result.expires_at <= current
        ]
        for key in expired_cache_keys:
            self._evict_spec_compose_key(key, cancel_future=True)
        expired_future_keys = [
            key
            for key, entry in self._spec_compose_futures.items()
            if entry.expires_at <= current
        ]
        for key in expired_future_keys:
            self._evict_spec_compose_key(key, cancel_future=True)

    def _latest_generation_for_scope(
        self,
        *,
        session_id: str,
        turn_index: int,
        source_scope: str,
    ) -> int:
        scope_key = (session_id, int(turn_index), source_scope)
        generation = int(self._spec_compose_latest_generation.get(scope_key, 0)) + 1
        self._spec_compose_latest_generation[scope_key] = generation
        return generation

    def _cancel_previous_spec_compose_for_scope(
        self,
        *,
        session_id: str,
        turn_index: int,
        source_scope: str,
    ) -> int:
        removed_count = 0
        stale_keys = [
            key
            for key, entry in self._spec_compose_futures.items()
            if key.session_id == session_id
            and int(key.turn_index) == int(turn_index)
            and str(entry.source).startswith(source_scope)
        ]
        for stale_key in stale_keys:
            self._evict_spec_compose_key(stale_key, cancel_future=True)
            removed_count += 1
        stale_cache_keys = [
            key
            for key, result in self._spec_compose_cache.items()
            if key.session_id == session_id
            and int(key.turn_index) == int(turn_index)
            and str(result.source).startswith(source_scope)
        ]
        for stale_key in stale_cache_keys:
            self._evict_spec_compose_key(stale_key, cancel_future=False)
            removed_count += 1
        return removed_count

    def _clear_typing_phase_spec_compose_scope(self, *, session_id: str, turn_index: int) -> int:
        return self._cancel_previous_spec_compose_for_scope(
            session_id=session_id,
            turn_index=turn_index,
            source_scope="typing_phase",
        )

    def _run_spec_compose_job(
        self,
        *,
        key: _SpecComposeCacheKey,
        source: str,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        input_text: str,
        selected_suggestion_id: str | None,
        selected_story_action_id: str | None,
        selected_control_action_id: str | None,
        control_action: Any,
        control_target_kind: str | None,
        control_target_id: str | None,
        control_target_mode: str | None,
        precomputed_intent: Any,
        precomputed_micro_sim: Any,
        precomputed_intent_diagnostics: dict[str, Any] | None,
        prefetched_suggestions: tuple[Any, ...] | None,
        prefetched_control_actions: tuple[Any, ...] | None,
        expires_at: datetime,
    ) -> _SpecComposeResult:
        gateway = self._resolve_gateway()
        try:
            payload = run_v2_speculative_compose_prewarm(
                plan,
                state,
                input_text,
                gateway=gateway,
                selected_suggestion_id=selected_suggestion_id,
                selected_story_action_id=selected_story_action_id,
                selected_control_action_id=selected_control_action_id,
                control_action=control_action,
                control_target_kind=control_target_kind,
                control_target_id=control_target_id,
                control_target_mode=control_target_mode,
                precomputed_intent=precomputed_intent,
                precomputed_micro_sim=precomputed_micro_sim,
                precomputed_intent_diagnostics=precomputed_intent_diagnostics,
                prefetched_suggestions=prefetched_suggestions,
                prefetched_control_actions=prefetched_control_actions,
            )
            narration = _NORMALIZE_SPACES_RE.sub(" ", str(payload.get("narration") or "")).strip()
            diagnostics = self._sanitize_scalar_diagnostics(dict(payload.get("diagnostics") or {}))
            compose_input_tokens = max(int(payload.get("compose_input_tokens", 0) or 0), 0)
            compose_output_tokens = max(int(payload.get("compose_output_tokens", 0) or 0), 0)
            compose_total_tokens = max(int(payload.get("compose_total_tokens", 0) or 0), 0)
            if compose_total_tokens <= 0:
                compose_total_tokens = compose_input_tokens + compose_output_tokens
            if not narration:
                return _SpecComposeResult(
                    key=key,
                    source=source,
                    narration="",
                    diagnostics=diagnostics,
                    compose_input_tokens=compose_input_tokens,
                    compose_output_tokens=compose_output_tokens,
                    compose_total_tokens=compose_total_tokens,
                    expires_at=expires_at,
                    failed_reason="empty_narration",
                )
            return _SpecComposeResult(
                key=key,
                source=source,
                narration=narration,
                diagnostics=diagnostics,
                compose_input_tokens=compose_input_tokens,
                compose_output_tokens=compose_output_tokens,
                compose_total_tokens=compose_total_tokens,
                expires_at=expires_at,
            )
        except Exception as exc:  # noqa: BLE001
            return _SpecComposeResult(
                key=key,
                source=source,
                narration="",
                diagnostics={},
                compose_input_tokens=0,
                compose_output_tokens=0,
                compose_total_tokens=0,
                expires_at=expires_at,
                failed_reason=f"spec_compose_job_failed:{str(exc)[:120]}",
            )

    def _schedule_spec_compose_job(
        self,
        *,
        session_id: str,
        turn_index: int,
        state_snapshot_id: str,
        normalized_text_hash: str,
        source: str,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
        input_text: str,
        selected_suggestion_id: str | None = None,
        selected_story_action_id: str | None = None,
        selected_control_action_id: str | None = None,
        control_action: Any = None,
        control_target_kind: str | None = None,
        control_target_id: str | None = None,
        control_target_mode: str | None = None,
        precomputed_intent: Any = None,
        precomputed_micro_sim: Any = None,
        precomputed_intent_diagnostics: dict[str, Any] | None = None,
        prefetched_suggestions: tuple[Any, ...] | None = None,
        prefetched_control_actions: tuple[Any, ...] | None = None,
        latest_wins_scope: str | None = None,
    ) -> None:
        if not self._spec_compose_prewarm_enabled():
            return
        key = _SpecComposeCacheKey(
            session_id=session_id,
            turn_index=int(turn_index),
            state_snapshot_id=str(state_snapshot_id),
            normalized_text_hash=str(normalized_text_hash),
        )
        now = self._now()
        self._purge_expired_spec_compose(now=now)
        if self._spec_compose_backpressure_active():
            return
        if latest_wins_scope:
            self._cancel_previous_spec_compose_for_scope(
                session_id=session_id,
                turn_index=turn_index,
                source_scope=latest_wins_scope,
            )
            generation = self._latest_generation_for_scope(
                session_id=session_id,
                turn_index=turn_index,
                source_scope=latest_wins_scope,
            )
        else:
            generation = 0
        self._evict_spec_compose_key(key, cancel_future=True)
        expires_at = now + timedelta(seconds=_SPEC_COMPOSE_TTL_SECONDS)
        future = self._spec_compose_executor_instance().submit(
            self._run_spec_compose_job,
            key=key,
            source=source,
            plan=plan.model_copy(deep=True),
            state=state.model_copy(deep=True),
            input_text=input_text,
            selected_suggestion_id=selected_suggestion_id,
            selected_story_action_id=selected_story_action_id,
            selected_control_action_id=selected_control_action_id,
            control_action=control_action,
            control_target_kind=control_target_kind,
            control_target_id=control_target_id,
            control_target_mode=control_target_mode,
            precomputed_intent=precomputed_intent.model_copy(deep=True) if precomputed_intent is not None else None,
            precomputed_micro_sim=precomputed_micro_sim,
            precomputed_intent_diagnostics=dict(precomputed_intent_diagnostics or {}),
            prefetched_suggestions=tuple(prefetched_suggestions or ()),
            prefetched_control_actions=tuple(prefetched_control_actions or ()),
            expires_at=expires_at,
        )
        self._spec_compose_futures[key] = _SpecComposeFutureEntry(
            key=key,
            source=source,
            generation=generation,
            future=future,
            expires_at=expires_at,
            started_at=perf_counter(),
        )
        self._register_spec_compose_key(key)

    def _consume_ready_spec_compose_result(
        self,
        *,
        key: _SpecComposeCacheKey,
        source_scope: str | None = None,
    ) -> _SpecComposeResult | None:
        now = self._now()
        cached = self._spec_compose_cache.get(key)
        if cached is not None:
            if cached.expires_at <= now:
                self._evict_spec_compose_key(key, cancel_future=True)
                return None
            return cached
        future_entry = self._spec_compose_futures.get(key)
        if future_entry is None or not future_entry.future.done():
            return None
        try:
            result = future_entry.future.result()
        except Exception as exc:  # noqa: BLE001
            result = _SpecComposeResult(
                key=key,
                source=future_entry.source,
                narration="",
                diagnostics={},
                compose_input_tokens=0,
                compose_output_tokens=0,
                compose_total_tokens=0,
                expires_at=future_entry.expires_at,
                failed_reason=f"spec_compose_future_failed:{str(exc)[:120]}",
            )
        self._spec_compose_futures.pop(key, None)
        if source_scope:
            latest_generation = int(
                self._spec_compose_latest_generation.get((key.session_id, int(key.turn_index), source_scope), 0)
            )
            if future_entry.generation and future_entry.generation != latest_generation:
                return None
        if result.expires_at <= now:
            return None
        self._spec_compose_cache[key] = result
        return result

    def _resolve_submit_spec_compose(
        self,
        *,
        session_id: str,
        state: UrbanWorldState,
        input_text: str,
        has_selected_ids: bool,
    ) -> tuple[dict[str, Any] | None, str, float, str, int, int, int, int]:
        if not self._spec_compose_prewarm_enabled():
            return None, "disabled", 0.0, "", 0, 0, 0, 0
        now = self._now()
        self._purge_expired_spec_compose(now=now)
        key = _SpecComposeCacheKey(
            session_id=session_id,
            turn_index=int(state.turn_index),
            state_snapshot_id=self._state_snapshot_id(state),
            normalized_text_hash=self._normalized_text_hash(input_text),
        )
        result = self._consume_ready_spec_compose_result(key=key, source_scope="typing_phase")
        if result is not None:
            if result.failed_reason:
                return None, "failed", 0.0, result.source, 0, 0, 0, 0
            total_tokens = max(int(result.compose_total_tokens), 0)
            typing_tokens = total_tokens if str(result.source).startswith("typing_phase") else 0
            read_tokens = total_tokens if str(result.source).startswith("read_phase") else 0
            payload = {
                "narration": result.narration,
                "diagnostics": dict(result.diagnostics or {}),
                "compose_input_tokens": int(result.compose_input_tokens),
                "compose_output_tokens": int(result.compose_output_tokens),
                "compose_total_tokens": total_tokens,
                "source": result.source,
                "compose_prewarm_source": result.source,
            }
            return payload, "ready", 0.0, result.source, total_tokens, typing_tokens, read_tokens, 0
        pending_entry = self._spec_compose_futures.get(key)
        if pending_entry is not None:
            wait_started = perf_counter()
            try:
                wait_result = pending_entry.future.result(
                    timeout=self._submit_spec_compose_pending_wait_seconds(has_selected_ids=has_selected_ids)
                )
            except TimeoutError:
                waited_ms = max((perf_counter() - wait_started) * 1000.0, 0.0)
                return None, "pending", waited_ms, pending_entry.source, 0, 0, 0, 0
            except Exception as exc:  # noqa: BLE001
                self._evict_spec_compose_key(key, cancel_future=True)
                waited_ms = max((perf_counter() - wait_started) * 1000.0, 0.0)
                return None, f"failed:{str(exc)[:80]}", waited_ms, pending_entry.source, 0, 0, 0, 0
            waited_ms = max((perf_counter() - wait_started) * 1000.0, 0.0)
            self._spec_compose_futures.pop(key, None)
            self._spec_compose_cache[key] = wait_result
            if wait_result.failed_reason:
                return None, "failed", waited_ms, wait_result.source, 0, 0, 0, 0
            total_tokens = max(int(wait_result.compose_total_tokens), 0)
            typing_tokens = total_tokens if str(wait_result.source).startswith("typing_phase") else 0
            read_tokens = total_tokens if str(wait_result.source).startswith("read_phase") else 0
            payload = {
                "narration": wait_result.narration,
                "diagnostics": dict(wait_result.diagnostics or {}),
                "compose_input_tokens": int(wait_result.compose_input_tokens),
                "compose_output_tokens": int(wait_result.compose_output_tokens),
                "compose_total_tokens": total_tokens,
                "source": wait_result.source,
                "compose_prewarm_source": wait_result.source,
            }
            return payload, "ready", waited_ms, wait_result.source, total_tokens, typing_tokens, read_tokens, 0
        similar_keys = {
            item
            for item in self._spec_compose_cache.keys()
            if item.session_id == key.session_id
            and int(item.turn_index) == int(key.turn_index)
            and item.state_snapshot_id == key.state_snapshot_id
            and item.normalized_text_hash != key.normalized_text_hash
        } | {
            item
            for item in self._spec_compose_futures.keys()
            if item.session_id == key.session_id
            and int(item.turn_index) == int(key.turn_index)
            and item.state_snapshot_id == key.state_snapshot_id
            and item.normalized_text_hash != key.normalized_text_hash
        }
        stale_fragment_count = len(similar_keys)
        if stale_fragment_count > 0:
            return None, "stale_fragment", 0.0, "", 0, 0, 0, stale_fragment_count
        return None, "not_found", 0.0, "", 0, 0, 0, 0

    def _evict_draft_intent(self, draft_intent_id: str) -> None:
        entry = self._draft_intents_by_id.pop(draft_intent_id, None)
        if entry is None:
            return
        lookup_key = (
            entry.session_id,
            int(entry.turn_index),
            str(entry.state_snapshot_id),
            str(entry.normalized_text_hash),
        )
        if self._draft_intent_lookup.get(lookup_key) == draft_intent_id:
            self._draft_intent_lookup.pop(lookup_key, None)
        session_ids = self._draft_intent_ids_by_session.get(entry.session_id)
        if session_ids is not None:
            self._draft_intent_ids_by_session[entry.session_id] = [
                item for item in session_ids if item != draft_intent_id
            ]
            if not self._draft_intent_ids_by_session[entry.session_id]:
                self._draft_intent_ids_by_session.pop(entry.session_id, None)

    def _purge_expired_draft_intents(self, *, now: datetime | None = None) -> None:
        current = now or self._now()
        expired_ids = [
            draft_intent_id
            for draft_intent_id, entry in self._draft_intents_by_id.items()
            if entry.expires_at <= current
        ]
        for draft_intent_id in expired_ids:
            self._evict_draft_intent(draft_intent_id)

    def _store_draft_intent(self, entry: _DraftIntentEntry) -> None:
        lookup_key = (
            entry.session_id,
            int(entry.turn_index),
            str(entry.state_snapshot_id),
            str(entry.normalized_text_hash),
        )
        previous_for_key = self._draft_intent_lookup.get(lookup_key)
        if previous_for_key and previous_for_key != entry.draft_intent_id:
            self._evict_draft_intent(previous_for_key)
        self._draft_intents_by_id[entry.draft_intent_id] = entry
        self._draft_intent_lookup[lookup_key] = entry.draft_intent_id
        queue = self._draft_intent_ids_by_session.setdefault(entry.session_id, [])
        queue.append(entry.draft_intent_id)
        while len(queue) > _DRAFT_INTENT_MAX_ENTRIES_PER_SESSION:
            stale_id = queue.pop(0)
            self._evict_draft_intent(stale_id)

    def _clear_transients_for_session(self, session_id: str) -> None:
        self._prewarm_bundles.pop(session_id, None)
        draft_ids = list(self._draft_intent_ids_by_session.pop(session_id, []))
        for draft_intent_id in draft_ids:
            self._evict_draft_intent(draft_intent_id)
        spec_keys = list(self._spec_compose_session_keys.pop(session_id, []))
        for key in spec_keys:
            self._evict_spec_compose_key(key, cancel_future=True)
        stale_scope_keys = [
            scope_key
            for scope_key in self._spec_compose_latest_generation.keys()
            if scope_key[0] == session_id
        ]
        for scope_key in stale_scope_keys:
            self._spec_compose_latest_generation.pop(scope_key, None)

    def _prewarm_bundle_for_state(
        self,
        *,
        session_id: str,
        plan: CompiledPlayPlan,
        state: UrbanWorldState,
    ) -> _PrewarmBundle:
        snapshot_id = self._state_snapshot_id(state)
        existing = self._prewarm_bundles.get(session_id)
        if (
            existing is not None
            and existing.turn_index == state.turn_index
            and existing.state_snapshot_id == snapshot_id
        ):
            return existing
        bundle = _PrewarmBundle(
            session_id=session_id,
            turn_index=state.turn_index,
            state_snapshot_id=snapshot_id,
            suggested_actions=tuple(build_v2_suggested_actions(plan, state)),
            control_actions=tuple(build_v2_control_actions(plan, state)),
            created_at=self._now(),
        )
        self._prewarm_bundles[session_id] = bundle
        return bundle

    def _resolve_submit_draft(
        self,
        *,
        session_id: str,
        state: UrbanWorldState,
        input_text: str,
        draft_intent_id: str | None,
    ) -> tuple[_DraftIntentEntry | None, str]:
        if not draft_intent_id:
            return None, "not_requested"
        self._purge_expired_draft_intents()
        entry = self._draft_intents_by_id.get(str(draft_intent_id))
        if entry is None:
            return None, "id_not_found"
        if entry.session_id != session_id:
            return None, "session_mismatch"
        if int(entry.turn_index) != int(state.turn_index):
            return None, "turn_index_mismatch"
        snapshot_id = self._state_snapshot_id(state)
        if entry.state_snapshot_id != snapshot_id:
            return None, "state_snapshot_mismatch"
        if entry.normalized_text_hash != self._normalized_text_hash(input_text):
            return None, "text_mismatch"
        if entry.expires_at <= self._now():
            self._evict_draft_intent(entry.draft_intent_id)
            return None, "expired"
        return entry, "reused"

    @staticmethod
    def _draft_preview_from_intent(intent: Any) -> PlayDraftIntentPreview:
        return PlayDraftIntentPreview(
            lane_id=str(intent.lane_id),
            move_family=intent.move_family,
            target_id=intent.target_id,
            scene_frame=intent.scene_frame,
            control_action=intent.control_action,
            control_source=intent.control_source,
            control_target_kind=intent.control_target_kind,
            control_target_id=intent.control_target_id,
            control_target_mode=intent.control_target_mode,
            intent_compile_source=intent.intent_compile_source,
            intent_confidence=max(min(float(intent.intent_confidence or 0.0), 1.0), 0.0),
            deviation_type=intent.deviation_type,
            deviation_note=intent.deviation_note,
            mapped_suggestion_id=intent.mapped_suggestion_id,
            alternatives=list(intent.alternatives[:3]),
        )

    def _draft_response_from_entry(self, entry: _DraftIntentEntry) -> PlayDraftIntentResponse:
        return PlayDraftIntentResponse(
            session_id=entry.session_id,
            turn_index=int(entry.turn_index),
            draft_intent_id=entry.draft_intent_id,
            state_snapshot_id=entry.state_snapshot_id,
            normalized_text_hash=entry.normalized_text_hash,
            expires_at=entry.expires_at,
            intent=self._draft_preview_from_intent(entry.intent),
            diagnostics=self._sanitize_scalar_diagnostics(entry.diagnostics),
            usage={key: int(value) for key, value in dict(entry.usage or {}).items()},
        )

    def _get_record(self, session_id: str) -> _PlaySessionRecord:
        with self._lock:
            cached = self._sessions.get(session_id)
        if cached is not None:
            record = cached
        else:
            payload = self._storage.get_session(session_id)
            if payload is None:
                raise PlayServiceError(
                    code="play_session_not_found",
                    message=f"play session '{session_id}' was not found",
                    status_code=404,
                )
            record = self._deserialize_record(payload)
            with self._lock:
                self._sessions[session_id] = record
        return record

    def _expire_record_if_needed(self, record: _PlaySessionRecord) -> None:
        if record.state.status != "active" or self._now() < record.expires_at:
            return
        record.state.status = "expired"
        if isinstance(record.state, UrbanWorldState):
            clear_delta_pack_future(record.state.session_id)
            record.state.suggested_actions = []
            record.state.story_actions = []
            record.state.control_actions = []
            record.state.narration = "This session expired after sitting idle too long. Start a new run from the library."
        else:
            record.state.suggested_actions = []
            record.state.narration = "This session expired after sitting idle too long. Start a new run from the library."
        record.finished_at = self._now()
        self._clear_transients_for_session(record.state.session_id)
        self._save_record(record)

    def _refresh_record_expiry(self, record: _PlaySessionRecord, *, now: datetime | None = None) -> None:
        if record.state.status != "active":
            return
        current = now or self._now()
        refreshed_expires_at = current + timedelta(seconds=int(self._settings.play_session_ttl_seconds))
        if refreshed_expires_at > record.expires_at:
            record.expires_at = refreshed_expires_at

    @staticmethod
    def _snapshot_for(plan: PlayPlan | CompiledPlayPlan, state: PlaySessionState | UrbanWorldState) -> PlaySessionSnapshot:
        if isinstance(plan, CompiledPlayPlan) and isinstance(state, UrbanWorldState):
            return build_v2_snapshot(plan, state)
        if is_relationship_drama_plan(plan):
            return build_relationship_session_snapshot(plan, state)
        return build_session_snapshot(plan, state)

    @staticmethod
    def _add_usage(total: dict[str, int], usage: dict[str, int | str] | None) -> None:
        if not usage:
            return
        for key, value in usage.items():
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            total[str(key)] = total.get(str(key), 0) + int(value)

    @classmethod
    def _aggregate_trace_usage(cls, trace: PlayTurnTrace) -> dict[str, int]:
        usage: dict[str, int] = {}
        cls._add_usage(usage, trace.interpret_usage)
        cls._add_usage(usage, trace.ending_judge_usage)
        cls._add_usage(usage, trace.pyrrhic_critic_usage)
        cls._add_usage(usage, trace.render_usage)
        return usage

    @classmethod
    def _build_trace_summary(cls, traces: list[PlayTurnTrace]) -> BenchmarkPlayTraceSummary:
        interpret_source_distribution: dict[str, int] = {}
        ending_judge_source_distribution: dict[str, int] = {}
        pyrrhic_critic_source_distribution: dict[str, int] = {}
        render_source_distribution: dict[str, int] = {}
        usage_totals: dict[str, int] = {}
        heuristic_interpret_turn_count = 0
        render_fallback_turn_count = 0
        repair_turn_count = 0
        used_previous_response_turn_count = 0
        session_cache_enabled = False
        ending_id: str | None = None
        end_reason: str | None = None
        for trace in traces:
            interpret_source_distribution[trace.interpret_source] = interpret_source_distribution.get(trace.interpret_source, 0) + 1
            ending_judge_source_distribution[trace.ending_judge_source] = ending_judge_source_distribution.get(trace.ending_judge_source, 0) + 1
            pyrrhic_critic_source_distribution[trace.pyrrhic_critic_source] = pyrrhic_critic_source_distribution.get(trace.pyrrhic_critic_source, 0) + 1
            render_source_distribution[trace.render_source] = render_source_distribution.get(trace.render_source, 0) + 1
            if trace.interpret_source == "heuristic":
                heuristic_interpret_turn_count += 1
            if trace.render_source == "fallback":
                render_fallback_turn_count += 1
            if any(
                attempts > 1
                for attempts in (
                    trace.interpret_attempts,
                    trace.ending_judge_attempts,
                    trace.pyrrhic_critic_attempts,
                    trace.render_attempts,
                )
            ):
                repair_turn_count += 1
            if trace.used_previous_response_id:
                used_previous_response_turn_count += 1
            session_cache_enabled = session_cache_enabled or trace.session_cache_enabled
            cls._add_usage(usage_totals, cls._aggregate_trace_usage(trace))
            if trace.resolution.ending_id:
                ending_id = trace.resolution.ending_id
            if trace.resolution.ending_trigger_reason:
                end_reason = trace.resolution.ending_trigger_reason
        lane_usage_distribution: dict[str, int] = {}
        input_mode_distribution: dict[str, int] = {}
        for trace in traces:
            if trace.lane_id:
                lane_usage_distribution[trace.lane_id] = lane_usage_distribution.get(trace.lane_id, 0) + 1
            inferred_mode = trace.submission_input_mode
            if inferred_mode not in {"free_input", "select_id"}:
                inferred_mode = (
                    "select_id"
                    if (trace.selected_story_action_id or trace.selected_suggestion_id)
                    else "free_input"
                )
            input_mode_distribution[inferred_mode] = input_mode_distribution.get(inferred_mode, 0) + 1
        return BenchmarkPlayTraceSummary(
            turn_count=len(traces),
            total_turn_elapsed_ms=sum(trace.turn_elapsed_ms for trace in traces),
            total_interpret_elapsed_ms=sum(trace.interpret_elapsed_ms for trace in traces),
            total_ending_judge_elapsed_ms=sum(trace.ending_judge_elapsed_ms for trace in traces),
            total_pyrrhic_critic_elapsed_ms=sum(trace.pyrrhic_critic_elapsed_ms for trace in traces),
            total_render_elapsed_ms=sum(trace.render_elapsed_ms for trace in traces),
            interpret_source_distribution=interpret_source_distribution,
            ending_judge_source_distribution=ending_judge_source_distribution,
            pyrrhic_critic_source_distribution=pyrrhic_critic_source_distribution,
            render_source_distribution=render_source_distribution,
            heuristic_interpret_turn_count=heuristic_interpret_turn_count,
            render_fallback_turn_count=render_fallback_turn_count,
            repair_turn_count=repair_turn_count,
            used_previous_response_turn_count=used_previous_response_turn_count,
            session_cache_enabled=session_cache_enabled,
            usage_totals=usage_totals,
            lane_usage_distribution=lane_usage_distribution,
            input_mode_distribution=input_mode_distribution,
            ending_id=ending_id,
            ending_family=ending_id,
            end_reason=end_reason,
        )

    def create_session(self, story_id: str, *, actor_user_id: str | None = None) -> PlaySessionSnapshot:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        story = self._story_library_service.get_story_record(story_id, actor_user_id=resolved_actor_user_id)
        if not isinstance(story.bundle, RelationshipDramaV2Package):
            raise PlayServiceError(
                code="play_story_package_unsupported",
                message="only relationship_drama_v2 stories can start play sessions",
                status_code=409,
            )
        if int(getattr(story.bundle.compiled_play_plan, "semantic_strategy_version", 0) or 0) < 8:
            raise PlayServiceError(
                code="play_story_bundle_recompile_required",
                message="story bundle uses outdated play semantic schema; recompile with latest author pipeline",
                status_code=409,
            )
        return self.create_session_from_urban_plan(story.bundle.compiled_play_plan, actor_user_id=resolved_actor_user_id)

    def create_session_from_plan(self, plan: PlayPlan, *, actor_user_id: str | None = None) -> PlaySessionSnapshot:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        session_id = str(uuid4())
        state = build_initial_session_state(plan, session_id=session_id)
        now = self._now()
        record = _PlaySessionRecord(
            owner_user_id=resolved_actor_user_id,
            runtime_kind="legacy",
            plan=plan,
            state=state,
            created_at=now,
            expires_at=now + timedelta(seconds=self._settings.play_session_ttl_seconds),
            finished_at=None,
            history=[
                PlaySessionHistoryEntry(
                    speaker="gm",
                    text=state.narration,
                    created_at=now,
                    turn_index=0,
                )
            ],
            turn_traces=[],
        )
        self._session_lock_for(session_id)
        self._save_record(record)
        return self._snapshot_for(plan, state)

    def create_session_from_urban_plan(self, plan: CompiledPlayPlan, *, actor_user_id: str | None = None) -> PlaySessionSnapshot:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        if int(getattr(plan, "delta_pack_contract_version", 0) or 0) not in URBAN_PLAN_CONTRACT_VERSIONS:
            raise PlayServiceError(
                code="play_plan_version_unsupported",
                message="This play plan uses an unsupported delta-pack contract version. Please recompile the story and start a new session.",
                status_code=409,
            )
        session_id = str(uuid4())
        state = build_initial_world_state(plan, session_id=session_id)
        state.story_actions = build_v2_suggested_actions(plan, state)
        state.suggested_actions = list(state.story_actions)
        state.control_actions = build_v2_control_actions(plan, state)
        now = self._now()
        record = _PlaySessionRecord(
            owner_user_id=resolved_actor_user_id,
            runtime_kind="v2",
            plan=plan,
            state=state,
            created_at=now,
            expires_at=now + timedelta(seconds=self._settings.play_session_ttl_seconds),
            finished_at=None,
            history=[
                PlaySessionHistoryEntry(
                    speaker="gm",
                    text=state.narration,
                    created_at=now,
                    turn_index=0,
                )
            ],
            turn_traces=[],
        )
        self._session_lock_for(session_id)
        self._save_record(record)
        return self._snapshot_for(plan, state)

    def get_session(self, session_id: str, *, actor_user_id: str | None = None) -> PlaySessionSnapshot:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._session_lock_for(session_id):
            record = self._get_record(session_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, session_id=session_id)
            self._expire_record_if_needed(record)
            return self._snapshot_for(record.plan, record.state)

    def get_turn_traces(self, session_id: str, *, actor_user_id: str | None = None) -> list[PlayTurnTrace]:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._session_lock_for(session_id):
            record = self._get_record(session_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, session_id=session_id)
            self._expire_record_if_needed(record)
            return list(record.turn_traces)

    def get_session_history(self, session_id: str, *, actor_user_id: str | None = None) -> PlaySessionHistoryResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._session_lock_for(session_id):
            record = self._get_record(session_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, session_id=session_id)
            self._expire_record_if_needed(record)
            return PlaySessionHistoryResponse(
                session_id=session_id,
                story_id=record.plan.story_id,
                entries=list(record.history),
            )

    def draft_intent(
        self,
        session_id: str,
        request: PlayDraftIntentRequest,
        *,
        actor_user_id: str | None = None,
    ) -> PlayDraftIntentResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._session_lock_for(session_id):
            record = self._get_record(session_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, session_id=session_id)
            self._expire_record_if_needed(record)
            if record.state.status == "expired":
                raise PlayServiceError(
                    code="play_session_expired",
                    message="play session expired; start a new session from the library",
                    status_code=409,
                )
            if record.state.status == "completed":
                raise PlayServiceError(
                    code="play_session_completed",
                    message="play session is already complete",
                    status_code=409,
                )
            if not (isinstance(record.plan, CompiledPlayPlan) and isinstance(record.state, UrbanWorldState)):
                raise PlayServiceError(
                    code="play_session_plan_unsupported",
                    message="only urban_v2 play sessions are supported",
                    status_code=409,
                )
            now = self._now()
            self._purge_expired_draft_intents(now=now)
            state_snapshot_id = self._state_snapshot_id(record.state)
            normalized_text_hash = self._normalized_text_hash(request.input_text)
            typing_scope_cleared_count = self._clear_typing_phase_spec_compose_scope(
                session_id=session_id,
                turn_index=int(record.state.turn_index),
            )
            cache_key = (session_id, int(record.state.turn_index), state_snapshot_id, normalized_text_hash)
            cached_id = self._draft_intent_lookup.get(cache_key)
            if cached_id:
                cached_entry = self._draft_intents_by_id.get(cached_id)
                if (
                    cached_entry is not None
                    and cached_entry.expires_at > now
                    and bool(cached_entry.is_final_draft) == bool(request.is_final_draft)
                ):
                    return self._draft_response_from_entry(cached_entry)

            prewarm = self._prewarm_bundle_for_state(
                session_id=session_id,
                plan=record.plan,
                state=record.state,
            )
            # Non-final typing fragments should stay lightweight and avoid live LLM load.
            # Only final draft (or explicit non-typing callers) uses gateway-backed compile.
            gateway: PlayLLMGateway | None = None
            if bool(request.is_final_draft):
                gateway = self._resolve_gateway()
            intent, micro_sim, diagnostics = run_v2_intent_stage(
                record.plan,
                record.state,
                request.input_text,
                gateway=gateway,
                selected_suggestion_id=request.selected_suggestion_id,
                selected_story_action_id=request.selected_story_action_id,
                selected_control_action_id=request.selected_control_action_id,
                control_action=request.control_action,
                control_target_kind=request.control_target_kind,
                control_target_id=request.control_target_id,
                control_target_mode=request.control_target_mode,
                prefetched_suggestions=prewarm.suggested_actions,
                prefetched_control_actions=prewarm.control_actions,
            )
            usage = self._draft_usage_from_diagnostics(diagnostics)
            draft_diagnostics = dict(diagnostics or {})
            draft_diagnostics["typing_final_draft_seen"] = bool(request.is_final_draft)
            draft_diagnostics["typing_scope_cleared_count"] = max(int(typing_scope_cleared_count), 0)
            draft_entry = _DraftIntentEntry(
                draft_intent_id=f"draft_{uuid4().hex[:24]}",
                session_id=session_id,
                turn_index=int(record.state.turn_index),
                state_snapshot_id=state_snapshot_id,
                normalized_text_hash=normalized_text_hash,
                is_final_draft=bool(request.is_final_draft),
                typing_scope_cleared_count=max(int(typing_scope_cleared_count), 0),
                intent=intent,
                micro_sim=micro_sim,
                diagnostics=draft_diagnostics,
                usage=usage,
                expires_at=now + timedelta(seconds=_DRAFT_INTENT_TTL_SECONDS),
            )
            self._store_draft_intent(draft_entry)
            if (
                bool(request.is_final_draft)
                and self._spec_compose_prewarm_enabled()
                and self._should_schedule_typing_phase_prewarm(
                plan=record.plan,
                state=record.state,
                intent=draft_entry.intent,
                input_text=request.input_text,
                diagnostics=draft_entry.diagnostics,
                )
            ):
                self._schedule_spec_compose_job(
                    session_id=session_id,
                    turn_index=int(record.state.turn_index),
                    state_snapshot_id=state_snapshot_id,
                    normalized_text_hash=normalized_text_hash,
                    source="typing_phase:draft_intent",
                    plan=record.plan,
                    state=record.state,
                    input_text=request.input_text,
                    selected_suggestion_id=request.selected_suggestion_id,
                    selected_story_action_id=request.selected_story_action_id,
                    selected_control_action_id=request.selected_control_action_id,
                    control_action=request.control_action,
                    control_target_kind=request.control_target_kind,
                    control_target_id=request.control_target_id,
                    control_target_mode=request.control_target_mode,
                    precomputed_intent=draft_entry.intent,
                    precomputed_micro_sim=draft_entry.micro_sim,
                    precomputed_intent_diagnostics=draft_entry.diagnostics,
                    prefetched_suggestions=prewarm.suggested_actions,
                    prefetched_control_actions=prewarm.control_actions,
                    latest_wins_scope="typing_phase",
                )
            return self._draft_response_from_entry(draft_entry)

    def get_session_diagnostics(self, session_id: str, *, actor_user_id: str | None = None) -> BenchmarkPlaySessionDiagnosticsResponse:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._session_lock_for(session_id):
            record = self._get_record(session_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, session_id=session_id)
            self._expire_record_if_needed(record)
            traces = list(record.turn_traces)
            return BenchmarkPlaySessionDiagnosticsResponse(
                session_id=session_id,
                story_id=record.plan.story_id,
                status=record.state.status,  # type: ignore[arg-type]
                created_at=record.created_at,
                expires_at=record.expires_at,
                finished_at=record.finished_at,
                turn_traces=[trace.model_dump(mode="json") for trace in traces],
                summary=self._build_trace_summary(traces),
            )

    def submit_turn(self, session_id: str, request: PlayTurnRequest, *, actor_user_id: str | None = None) -> PlaySessionSnapshot:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._session_lock_for(session_id):
            record = self._get_record(session_id)
            self._ensure_owner_access(record.owner_user_id, resolved_actor_user_id, session_id=session_id)
            self._expire_record_if_needed(record)
            if record.state.status == "expired":
                raise PlayServiceError(
                    code="play_session_expired",
                    message="play session expired; start a new session from the library",
                    status_code=409,
                )
            if record.state.status == "completed":
                raise PlayServiceError(
                    code="play_session_completed",
                    message="play session is already complete",
                    status_code=409,
                )
            handler = self._resolve_turn_handler(record)
            return handler.submit_turn(session_id=session_id, record=record, request=request)

    def _resolve_turn_handler(self, record: _PlaySessionRecord):
        if record.runtime_kind == "v2":
            return V2PlaySessionHandler(self)
        return LegacyPlaySessionHandler(self)

    def _submit_turn_v2(self, *, session_id: str, record: _PlaySessionRecord, request: PlayTurnRequest) -> PlaySessionSnapshot:
        if not (isinstance(record.plan, CompiledPlayPlan) and isinstance(record.state, UrbanWorldState)):
            raise PlayServiceError(
                code="play_session_plan_unsupported",
                message="only urban_v2 play sessions are supported",
                status_code=409,
            )
        before_state = record.state.model_copy(deep=True)
        prewarm = self._prewarm_bundle_for_state(
            session_id=session_id,
            plan=record.plan,
            state=record.state,
        )
        draft_entry, draft_status = self._resolve_submit_draft(
            session_id=session_id,
            state=record.state,
            input_text=request.input_text,
            draft_intent_id=request.draft_intent_id,
        )
        precomputed_intent = draft_entry.intent if draft_entry is not None else None
        precomputed_micro_sim = draft_entry.micro_sim if draft_entry is not None else None
        precomputed_diagnostics = dict(draft_entry.diagnostics or {}) if draft_entry is not None else None
        typing_final_draft_seen = bool(draft_entry.is_final_draft) if draft_entry is not None else False
        typing_scope_cleared_count = (
            max(int(draft_entry.typing_scope_cleared_count), 0) if draft_entry is not None else 0
        )
        draft_usage = dict(draft_entry.usage or {}) if draft_entry is not None else {}
        draft_call_count = 1 if draft_entry is not None else 0
        has_selected_ids = bool((request.selected_story_action_id or "").strip() or (request.selected_suggestion_id or "").strip())
        (
            precomputed_compose,
            compose_prewarm_status,
            compose_prewarm_wait_ms,
            compose_prewarm_source,
            compose_prewarm_total_tokens,
            typing_phase_prewarm_tokens,
            read_phase_prewarm_tokens,
            compose_prewarm_stale_fragment_count,
        ) = self._resolve_submit_spec_compose(
            session_id=session_id,
            state=record.state,
            input_text=request.input_text,
            has_selected_ids=has_selected_ids,
        )
        turn_started_at = perf_counter()
        try:
            # Story suggestions remain hints for free-input play; when provided explicitly,
            # they are forwarded so intent compilation can bypass unnecessary re-interpretation.
            result = run_v2_turn(
                record.plan,
                record.state,
                request.input_text,
                selected_suggestion_id=request.selected_suggestion_id,
                selected_story_action_id=request.selected_story_action_id,
                selected_control_action_id=request.selected_control_action_id,
                control_action=request.control_action,
                control_target_kind=request.control_target_kind,
                control_target_id=request.control_target_id,
                control_target_mode=request.control_target_mode,
                precomputed_intent=precomputed_intent,
                precomputed_micro_sim=precomputed_micro_sim,
                precomputed_intent_diagnostics=precomputed_diagnostics,
                precomputed_compose=precomputed_compose,
                prefetched_suggestions=prewarm.suggested_actions,
                prefetched_control_actions=prewarm.control_actions,
                draft_usage=draft_usage,
                draft_call_count=draft_call_count,
                draft_intent_status=draft_status,
                compose_prewarm_status=compose_prewarm_status,
                compose_prewarm_wait_ms=compose_prewarm_wait_ms,
                compose_prewarm_source=compose_prewarm_source,
                compose_prewarm_total_tokens=compose_prewarm_total_tokens,
                typing_phase_prewarm_tokens=typing_phase_prewarm_tokens,
                read_phase_prewarm_tokens=read_phase_prewarm_tokens,
                typing_final_draft_seen=typing_final_draft_seen,
                typing_scope_cleared_count=typing_scope_cleared_count,
                compose_prewarm_stale_fragment_count=compose_prewarm_stale_fragment_count,
            )
        except ValueError as exc:
            raise PlayServiceError(
                code="play_turn_invalid_control_target",
                message=str(exc),
                status_code=400,
            ) from exc
        turn_elapsed_ms = max(int((perf_counter() - turn_started_at) * 1000), 0)
        record.state = result.state
        record.history.append(
            PlaySessionHistoryEntry(
                speaker="player",
                text=request.input_text,
                created_at=self._now(),
                turn_index=record.state.turn_index,
            )
        )
        record.history.append(
            PlaySessionHistoryEntry(
                speaker="gm",
                text=result.narration,
                created_at=self._now(),
                turn_index=record.state.turn_index,
            )
        )
        if record.state.status != "active" and record.finished_at is None:
            record.finished_at = self._now()
        if self._enable_turn_telemetry:
            trace, payload = build_v2_turn_trace(
                plan=record.plan,
                before_state=before_state,
                result=result,
                player_input=request.input_text,
                selected_suggestion_id=request.selected_suggestion_id,
                selected_story_action_id=request.selected_story_action_id,
                selected_control_action_id=request.selected_control_action_id,
                turn_elapsed_ms=turn_elapsed_ms,
            )
            trace.lane_id = payload.lane_id
            if payload.ending_family:
                trace.resolution.ending_id = payload.ending_family
            record.turn_traces.append(trace)
        self._prewarm_bundle_for_state(
            session_id=session_id,
            plan=record.plan,
            state=record.state,
        )
        previous_turn_select_id = has_selected_ids
        if (
            record.state.status == "active"
            and self._spec_compose_prewarm_enabled()
            and self._should_schedule_read_phase_prewarm(
            plan=record.plan,
            state=record.state,
            previous_turn_select_id=previous_turn_select_id,
            )
        ):
            refreshed_prewarm = self._prewarm_bundle_for_state(
                session_id=session_id,
                plan=record.plan,
                state=record.state,
            )
            state_snapshot_id = self._state_snapshot_id(record.state)
            for action in list(record.state.story_actions[:_SPEC_COMPOSE_READ_PHASE_TOP_K]):
                action_prompt = str(action.prompt or "").strip()
                if not action_prompt:
                    continue
                self._schedule_spec_compose_job(
                    session_id=session_id,
                    turn_index=int(record.state.turn_index),
                    state_snapshot_id=state_snapshot_id,
                    normalized_text_hash=self._normalized_text_hash(action_prompt),
                    source="read_phase:auto_top1",
                    plan=record.plan,
                    state=record.state,
                    input_text=action_prompt,
                    selected_suggestion_id=action.suggestion_id,
                    selected_story_action_id=action.suggestion_id,
                    selected_control_action_id=None,
                    control_action="none",
                    control_target_kind=None,
                    control_target_id=None,
                    control_target_mode=None,
                    precomputed_intent=None,
                    precomputed_micro_sim=None,
                    precomputed_intent_diagnostics=None,
                    prefetched_suggestions=refreshed_prewarm.suggested_actions,
                    prefetched_control_actions=refreshed_prewarm.control_actions,
                    latest_wins_scope=None,
                )
        self._refresh_record_expiry(record)
        self._save_record(record)
        return self._snapshot_for(record.plan, record.state)

    def _submit_turn_legacy(self, *, session_id: str, record: _PlaySessionRecord, request: PlayTurnRequest) -> PlaySessionSnapshot:
        if isinstance(record.plan, CompiledPlayPlan) or isinstance(record.state, UrbanWorldState):
            raise PlayServiceError(
                code="play_session_plan_unsupported",
                message=f"legacy runtime handler received unsupported session '{session_id}'",
                status_code=409,
            )
        selected_action = next(
            (item for item in record.state.suggested_actions if item.suggestion_id == request.selected_suggestion_id),
            None,
        )
        if is_relationship_drama_plan(record.plan):
            turn_started_at = perf_counter()
            beat_index_before = record.state.beat_index + 1
            beat_before = record.plan.beats[record.state.beat_index]
            interpret_started_at = perf_counter()
            interpret_result = heuristic_relationship_turn_intent(
                input_text=request.input_text,
                plan=record.plan,
                state=record.state,
                selected_action=selected_action,
            )
            interpret_elapsed_ms = max(int((perf_counter() - interpret_started_at) * 1000), 0)
            record.state.turn_index += 1
            resolution, _ending_context = apply_turn_resolution(
                plan=record.plan,
                state=record.state,
                intent=interpret_result.intent,
                use_tuned_ending_policy=False,
            )
            judge_started_at = perf_counter()
            judge_result = judge_relationship_drama_ending(
                plan=record.plan,
                state=record.state,
                resolution=resolution,
            )
            ending_judge_elapsed_ms = max(int((perf_counter() - judge_started_at) * 1000), 0)
            resolution = apply_relationship_judged_ending(
                plan=record.plan,
                state=record.state,
                resolution=resolution,
                judge_result=judge_result,
            )
            pyrrhic_critic_result = RelationshipJudgeResult(proposed_ending_id=None, source="skipped", attempts=0)
            pyrrhic_critic_elapsed_ms = 0
            render_started_at = perf_counter()
            render_result = render_relationship_turn(
                plan=record.plan,
                state=record.state,
                resolution=resolution,
                input_text=request.input_text,
                selected_action=selected_action,
            )
            render_elapsed_ms = max(int((perf_counter() - render_started_at) * 1000), 0)
            record.state.session_response_id = None
            record.state.narration = render_result.narration
            record.state.suggested_actions = [] if record.state.status != "active" else render_result.suggestions
            player_entry_created_at = self._now()
            gm_entry_created_at = self._now()
            record.history.append(
                PlaySessionHistoryEntry(
                    speaker="player",
                    text=request.input_text,
                    created_at=player_entry_created_at,
                    turn_index=record.state.turn_index,
                )
            )
            record.history.append(
                PlaySessionHistoryEntry(
                    speaker="gm",
                    text=render_result.narration,
                    created_at=gm_entry_created_at,
                    turn_index=record.state.turn_index,
                )
            )
            if record.state.status != "active" and record.finished_at is None:
                record.finished_at = self._now()
            if self._enable_turn_telemetry:
                beat_after = record.plan.beats[record.state.beat_index]
                record.turn_traces.append(
                    PlayTurnTrace(
                        turn_index=record.state.turn_index,
                        created_at=self._now(),
                        player_input=request.input_text,
                        selected_suggestion_id=request.selected_suggestion_id,
                        interpret_source=interpret_result.source,  # type: ignore[arg-type]
                        render_source=render_result.source,  # type: ignore[arg-type]
                        execution_frame="public" if interpret_result.intent.scene_frame == "public" else "procedural",
                        interpret_attempts=interpret_result.attempts,
                        ending_judge_source=judge_result.source,  # type: ignore[arg-type]
                        pyrrhic_critic_source=pyrrhic_critic_result.source,  # type: ignore[arg-type]
                        ending_judge_attempts=judge_result.attempts,
                        pyrrhic_critic_attempts=pyrrhic_critic_result.attempts,
                        ending_judge_proposed_id=judge_result.proposed_ending_id,
                        pyrrhic_critic_proposed_id=pyrrhic_critic_result.proposed_ending_id,
                        ending_judge_failure_reason=judge_result.failure_reason,
                        pyrrhic_critic_failure_reason=pyrrhic_critic_result.failure_reason,
                        ending_judge_response_id=judge_result.response_id,
                        pyrrhic_critic_response_id=pyrrhic_critic_result.response_id,
                        ending_judge_usage=judge_result.usage or {},
                        pyrrhic_critic_usage=pyrrhic_critic_result.usage or {},
                        render_attempts=render_result.attempts,
                        interpret_failure_reason=interpret_result.failure_reason,
                        render_failure_reason=render_result.failure_reason,
                        interpret_response_id=interpret_result.response_id,
                        render_response_id=render_result.response_id,
                        interpret_usage=interpret_result.usage or {},
                        render_usage=render_result.usage or {},
                        turn_elapsed_ms=max(int((perf_counter() - turn_started_at) * 1000), 0),
                        interpret_elapsed_ms=interpret_elapsed_ms,
                        ending_judge_elapsed_ms=ending_judge_elapsed_ms,
                        pyrrhic_critic_elapsed_ms=pyrrhic_critic_elapsed_ms,
                        render_elapsed_ms=render_elapsed_ms,
                        session_cache_enabled=False,
                        used_previous_response_id=False,
                        beat_index_before=beat_index_before,
                        beat_title_before=beat_before.title,
                        beat_index_after=record.state.beat_index + 1,
                        beat_title_after=beat_after.title,
                        status_after=record.state.status,  # type: ignore[arg-type]
                        move_family=interpret_result.intent.move_family,
                        scene_frame=interpret_result.intent.scene_frame,
                        target_character_ids=list(interpret_result.intent.target_character_ids),
                        global_state_changes=dict(resolution.global_state_changes),
                        relationship_state_changes={key: dict(value) for key, value in resolution.relationship_state_changes.items()},
                        revealed_secret_ids=list(resolution.revealed_secret_ids),
                        resolution=resolution,
                    )
                )
            self._refresh_record_expiry(record)
            self._save_record(record)
            return self._snapshot_for(record.plan, record.state)
        gateway = self._resolve_gateway()
        latest_response_id = record.state.session_response_id
        turn_started_at = perf_counter()
        beat_index_before = record.state.beat_index + 1
        beat_before = record.plan.beats[record.state.beat_index]
        interpret_previous_response_id = latest_response_id
        interpret_started_at = perf_counter()
        interpret_result = interpret_turn(
            plan=record.plan,
            state=record.state,
            input_text=request.input_text,
            selected_action=selected_action,
            gateway=gateway,
            previous_response_id=interpret_previous_response_id,
            enable_interpret_repair=self._enable_interpret_repair,
        )
        interpret_elapsed_ms = max(int((perf_counter() - interpret_started_at) * 1000), 0)
        if interpret_result.response_id:
            latest_response_id = interpret_result.response_id
        record.state.turn_index += 1
        resolution, ending_context = apply_turn_resolution(
            plan=record.plan,
            state=record.state,
            intent=interpret_result.intent,
            use_tuned_ending_policy=self._use_tuned_ending_policy,
        )
        judge_previous_response_id = latest_response_id
        judge_started_at = perf_counter()
        skip_first_turn_judge = record.state.turn_index <= 1
        if skip_first_turn_judge:
            judge_result = EndingJudgeResult(proposed_ending_id=None, source="skipped", attempts=0)
        else:
            judge_result = judge_ending_intent(
                plan=record.plan,
                state=record.state,
                resolution=resolution,
                ending_context=ending_context,
                input_text=request.input_text,
                selected_action=selected_action,
                gateway=gateway,
                previous_response_id=judge_previous_response_id,
                enable_ending_intent_judge=self._enable_ending_intent_judge,
            )
        ending_judge_elapsed_ms = max(int((perf_counter() - judge_started_at) * 1000), 0)
        if judge_result.response_id:
            latest_response_id = judge_result.response_id
        pyrrhic_previous_response_id = latest_response_id
        pyrrhic_started_at = perf_counter()
        if skip_first_turn_judge:
            pyrrhic_critic_result = PyrrhicCriticResult(proposed_ending_id=None, source="skipped", attempts=0)
        else:
            pyrrhic_critic_result = run_pyrrhic_critic(
                plan=record.plan,
                state=record.state,
                resolution=resolution,
                ending_context=ending_context,
                judge_result=judge_result,
                gateway=gateway,
                previous_response_id=pyrrhic_previous_response_id,
            )
        pyrrhic_critic_elapsed_ms = max(int((perf_counter() - pyrrhic_started_at) * 1000), 0)
        if pyrrhic_critic_result.response_id:
            latest_response_id = pyrrhic_critic_result.response_id
        proposed_ending_id = pyrrhic_critic_result.proposed_ending_id or judge_result.proposed_ending_id
        resolution = finalize_turn_ending(
            plan=record.plan,
            state=record.state,
            resolution=resolution,
            ending_context=ending_context,
            proposed_ending_id=proposed_ending_id,
            use_tuned_ending_policy=self._use_tuned_ending_policy,
            enable_pyrrhic_judge_relaxation=self._enable_pyrrhic_judge_relaxation,
        )
        render_previous_response_id = latest_response_id
        render_started_at = perf_counter()
        render_result = render_turn(
            plan=record.plan,
            state=record.state,
            resolution=resolution,
            input_text=request.input_text,
            selected_action=selected_action,
            gateway=gateway,
            previous_response_id=render_previous_response_id,
            enable_render_repair=self._enable_render_repair,
        )
        render_elapsed_ms = max(int((perf_counter() - render_started_at) * 1000), 0)
        if render_result.response_id:
            latest_response_id = render_result.response_id
        record.state.session_response_id = latest_response_id
        record.state.narration = render_result.narration
        record.state.suggested_actions = [] if record.state.status != "active" else render_result.suggestions
        player_entry_created_at = self._now()
        gm_entry_created_at = self._now()
        record.history.append(
            PlaySessionHistoryEntry(
                speaker="player",
                text=request.input_text,
                created_at=player_entry_created_at,
                turn_index=record.state.turn_index,
            )
        )
        record.history.append(
            PlaySessionHistoryEntry(
                speaker="gm",
                text=render_result.narration,
                created_at=gm_entry_created_at,
                turn_index=record.state.turn_index,
            )
        )
        if record.state.status != "active" and record.finished_at is None:
            record.finished_at = self._now()
        if self._enable_turn_telemetry:
            beat_after = record.plan.beats[record.state.beat_index]
            used_previous_response_id = any(
                response_id is not None
                for response_id in (
                    interpret_previous_response_id,
                    judge_previous_response_id,
                    pyrrhic_previous_response_id,
                    render_previous_response_id,
                )
            )
            usage_totals: dict[str, int] = {}
            self._add_usage(usage_totals, interpret_result.usage or {})
            self._add_usage(usage_totals, judge_result.usage or {})
            self._add_usage(usage_totals, pyrrhic_critic_result.usage or {})
            self._add_usage(usage_totals, render_result.usage or {})
            record.turn_traces.append(
                PlayTurnTrace(
                    turn_index=record.state.turn_index,
                    created_at=self._now(),
                    player_input=request.input_text,
                    selected_suggestion_id=request.selected_suggestion_id,
                    interpret_source=interpret_result.source,  # type: ignore[arg-type]
                    ending_judge_source=judge_result.source,  # type: ignore[arg-type]
                    execution_frame=interpret_result.intent.execution_frame,
                    ending_judge_attempts=judge_result.attempts,
                    ending_judge_proposed_id=judge_result.proposed_ending_id,  # type: ignore[arg-type]
                    ending_judge_failure_reason=judge_result.failure_reason,
                    ending_judge_response_id=judge_result.response_id,
                    ending_judge_usage=judge_result.usage or {},
                    pyrrhic_critic_source=pyrrhic_critic_result.source,  # type: ignore[arg-type]
                    pyrrhic_critic_attempts=pyrrhic_critic_result.attempts,
                    pyrrhic_critic_proposed_id=pyrrhic_critic_result.proposed_ending_id,  # type: ignore[arg-type]
                    pyrrhic_critic_failure_reason=pyrrhic_critic_result.failure_reason,
                    pyrrhic_critic_response_id=pyrrhic_critic_result.response_id,
                    pyrrhic_critic_usage=pyrrhic_critic_result.usage or {},
                    render_source=render_result.source,  # type: ignore[arg-type]
                    interpret_attempts=interpret_result.attempts,
                    render_attempts=render_result.attempts,
                    interpret_failure_reason=interpret_result.failure_reason,
                    render_failure_reason=render_result.failure_reason,
                    interpret_response_id=interpret_result.response_id,
                    render_response_id=render_result.response_id,
                    interpret_usage=interpret_result.usage or {},
                    render_usage=render_result.usage or {},
                    turn_elapsed_ms=max(int((perf_counter() - turn_started_at) * 1000), 0),
                    interpret_elapsed_ms=interpret_elapsed_ms,
                    ending_judge_elapsed_ms=ending_judge_elapsed_ms,
                    pyrrhic_critic_elapsed_ms=pyrrhic_critic_elapsed_ms,
                    render_elapsed_ms=render_elapsed_ms,
                    session_cache_enabled=bool(getattr(gateway, "use_session_cache", False)),
                    used_previous_response_id=used_previous_response_id,
                    input_tokens=usage_totals.get("input_tokens"),
                    output_tokens=usage_totals.get("output_tokens"),
                    total_tokens=usage_totals.get("total_tokens"),
                    cached_input_tokens=usage_totals.get("cached_input_tokens"),
                    cache_creation_input_tokens=usage_totals.get("cache_creation_input_tokens"),
                    beat_index_before=beat_index_before,
                    beat_title_before=beat_before.title,
                    beat_index_after=record.state.beat_index + 1,
                    beat_title_after=beat_after.title,
                    status_after=record.state.status,  # type: ignore[arg-type]
                    resolution=resolution,
                )
            )
        self._refresh_record_expiry(record)
        self._save_record(record)
        return self._snapshot_for(record.plan, record.state)

    def delete_sessions_for_story(self, *, actor_user_id: str | None = None, story_id: str) -> int:
        resolved_actor_user_id = actor_user_id or self._settings.default_actor_id
        with self._lock:
            deleted = self._storage.delete_sessions_for_story(
                story_id=story_id,
                owner_user_id=resolved_actor_user_id if actor_user_id is not None else None,
            )
            stale_session_ids = [
                session_id
                for session_id, record in self._sessions.items()
                if record.plan.story_id == story_id and (actor_user_id is None or record.owner_user_id == resolved_actor_user_id)
            ]
            for session_id in stale_session_ids:
                self._sessions.pop(session_id, None)
                self._session_locks.pop(session_id, None)
                self._clear_transients_for_session(session_id)
            return deleted
