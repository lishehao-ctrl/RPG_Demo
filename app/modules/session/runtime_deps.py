from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.models import Session as StorySession, Story
from app.modules.narrative.state_engine import normalize_state
from app.modules.session import fallback as runtime_fallback, runtime_pack, selection
from app.modules.session.story_choice_gating import evaluate_choice_availability
from app.modules.session.story_runtime.models import SelectionResult
from app.modules.session.story_runtime.pipeline import StoryRuntimePipelineDeps


def load_story_pack(db: Session, story_id: str, version: int | None = None) -> Story:
    if version is not None:
        row = db.execute(select(Story).where(Story.story_id == story_id, Story.version == version)).scalar_one_or_none()
    else:
        row = db.execute(
            select(Story)
            .where(Story.story_id == story_id, Story.is_published.is_(True))
            .order_by(Story.version.desc())
        ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "STORY_NOT_FOUND"})
    return row


def story_node(pack: dict, node_id: str) -> dict | None:
    return runtime_pack.story_node(pack, node_id)


def normalize_pack_for_runtime(pack_json: dict | None) -> dict:
    errors = runtime_pack.validate_runtime_pack_v10_strict(pack_json)
    if errors:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "RUNTIME_PACK_V10_REQUIRED",
                "message": "Stored story pack is not StoryPack v10 strict compatible.",
                "errors": errors,
            },
        )
    return runtime_pack.normalize_pack_for_runtime(pack_json)


def assert_stored_storypacks_v10_strict(*, sample_limit: int = 20) -> None:
    sample_cap = max(1, int(sample_limit))
    offenders: list[dict[str, object]] = []
    with db_session.SessionLocal() as db:
        rows = db.execute(
            select(Story.story_id, Story.version, Story.pack_json).order_by(Story.story_id.asc(), Story.version.asc())
        ).all()

    for story_id, version, pack_json in rows:
        errors = runtime_pack.validate_runtime_pack_v10_strict(pack_json if isinstance(pack_json, dict) else {})
        if not errors:
            continue
        offenders.append(
            {
                "story_id": str(story_id),
                "version": int(version),
                "errors": errors,
            }
        )
        if len(offenders) >= sample_cap:
            break

    if not offenders:
        return

    rendered = "; ".join(
        f"{item['story_id']}@{item['version']} -> {', '.join((item['errors'] or [])[:2])}"
        for item in offenders
    )
    raise RuntimeError(
        "LEGACY_STORYPACKS_BLOCK_STARTUP: incompatible stored story packs detected. "
        f"samples={rendered}"
    )


def resolve_runtime_fallback(node: dict, current_node_id: str, node_ids: set[str]) -> tuple[dict, str, list[str]]:
    return runtime_fallback.resolve_runtime_fallback(node, current_node_id, node_ids)


def fallback_executed_choice_id(fallback: dict, current_node_id: str) -> str:
    return runtime_fallback.fallback_executed_choice_id(fallback, current_node_id)


def select_fallback_text_variant(
    fallback: dict,
    reason_code: str | None,
    locale: str | None = None,
) -> str | None:
    return runtime_fallback.select_fallback_text_variant(fallback, reason_code, locale)


def select_story_choice(
    *,
    db: Session,
    sess: StorySession,
    llm_runtime_getter,
    player_input: str,
    visible_choices: list[dict],
    intents: list[dict] | None,
    current_story_state: dict,
    stage_emitter: Callable[[object], None] | None = None,
) -> SelectionResult:
    return selection.select_story_choice(
        db=db,
        sess=sess,
        player_input=player_input,
        visible_choices=visible_choices,
        intents=intents,
        current_story_state=current_story_state,
        llm_runtime_getter=llm_runtime_getter,
        stage_emitter=stage_emitter,
    )


def story_choices_for_response(node: dict, state_json: dict | None) -> list[dict]:
    out = []
    state = normalize_state(state_json)
    for choice in (node.get("choices") or []):
        action_id = ((choice.get("action") or {}).get("action_id") or "action")
        is_available, unavailable_reason = evaluate_choice_availability(choice, state)
        item = {
            "id": str(choice.get("choice_id")),
            "text": str(choice.get("display_text", "")),
            "type": str(action_id),
            "is_available": bool(is_available),
        }
        if not is_available and unavailable_reason:
            item["unavailable_reason"] = unavailable_reason
        out.append(item)
    return out


def apply_choice_effects(state: dict, effects: dict | None) -> dict:
    if not effects:
        return normalize_state(state)
    out = dict(state)
    for key in ("energy", "money", "knowledge", "affection"):
        if key in effects and effects.get(key) is not None:
            out[key] = int(out.get(key, 0)) + int(effects.get(key) or 0)
    return normalize_state(out)


def compute_state_delta(before: dict, after: dict) -> dict:
    delta: dict = {}
    for key, before_value in before.items():
        after_value = after.get(key)
        if before_value == after_value:
            continue
        if isinstance(before_value, int) and isinstance(after_value, int):
            delta[key] = after_value - before_value
        else:
            delta[key] = after_value
    return delta


def format_effects_suffix(effects: dict | None) -> str:
    if not isinstance(effects, dict):
        return ""
    parts: list[str] = []
    for key in sorted(effects.keys(), key=lambda item: str(item)):
        value = effects.get(key)
        if value is None:
            continue
        try:
            numeric = int(value)
        except Exception:  # noqa: BLE001
            continue
        if numeric == 0:
            continue
        sign = "+" if numeric > 0 else ""
        parts.append(f"{key} {sign}{numeric}")
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def build_story_runtime_pipeline_deps(
    *,
    db: Session,
    sess: StorySession,
    llm_runtime_getter,
    advance_quest_state,
    advance_runtime_events,
    resolve_run_ending,
    summarize_quest_for_narration,
    stage_emitter: Callable[[object], None] | None = None,
) -> StoryRuntimePipelineDeps:
    def _bound_select_story_choice(
        *,
        player_input: str,
        visible_choices: list[dict],
        intents: list[dict] | None,
        current_story_state: dict,
    ) -> SelectionResult:
        return select_story_choice(
            db=db,
            sess=sess,
            llm_runtime_getter=llm_runtime_getter,
            player_input=player_input,
            visible_choices=visible_choices,
            intents=intents,
            current_story_state=current_story_state,
            stage_emitter=stage_emitter,
        )

    return StoryRuntimePipelineDeps(
        load_story_pack=load_story_pack,
        normalize_pack_for_runtime=normalize_pack_for_runtime,
        story_node=story_node,
        resolve_runtime_fallback=resolve_runtime_fallback,
        select_story_choice=_bound_select_story_choice,
        fallback_executed_choice_id=fallback_executed_choice_id,
        select_fallback_text_variant=select_fallback_text_variant,
        apply_choice_effects=apply_choice_effects,
        compute_state_delta=compute_state_delta,
        format_effects_suffix=format_effects_suffix,
        story_choices_for_response=story_choices_for_response,
        advance_quest_state=advance_quest_state,
        advance_runtime_events=advance_runtime_events,
        resolve_run_ending=resolve_run_ending,
        summarize_quest_for_narration=summarize_quest_for_narration,
        llm_runtime_getter=llm_runtime_getter,
    )
