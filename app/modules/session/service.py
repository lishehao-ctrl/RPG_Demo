import re
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    ActionLog,
    Branch,
    Character,
    DialogueNode,
    LLMUsageLog,
    Session as StorySession,
    SessionCharacterState,
    SessionSnapshot,
    Story,
    User,
)
from app.modules.affection.engine import apply_affection
from app.modules.branch.engine import build_branch_context, resolve_branch
from app.modules.llm.adapter import get_llm_runtime
from app.modules.narrative.emotion_state import DEFAULT_EMOTION_WINDOW, build_emotion_state, select_behavior_policy
from app.modules.narrative.prompt_builder import build_step_prompt
from app.modules.replay.engine import ReplayEngine, upsert_replay_report
from app.modules.session.action_compiler import ActionCompiler
from app.modules.session.schemas import ChoiceOut, SessionStateOut

replay_engine = ReplayEngine()
action_compiler = ActionCompiler()


def _story_id_for_session(sess: StorySession) -> str:
    route_flags = sess.route_flags or {}
    global_flags = sess.global_flags or {}
    story_id = route_flags.get("story_id") or global_flags.get("story_id") or "default"
    return str(story_id)


def _resolve_active_character_state(
    db: Session,
    sess: StorySession,
    choice_id: str | None,
) -> tuple[SessionCharacterState | None, Character | None]:
    rows = db.execute(
        select(SessionCharacterState, Character)
        .join(Character, Character.id == SessionCharacterState.character_id)
        .where(SessionCharacterState.session_id == sess.id)
        .order_by(Character.name.asc(), SessionCharacterState.character_id.asc())
        # Stable ordering: first by name, then by id for deterministic active-character selection.
    ).all()
    if not rows:
        return None, None

    target_candidates = [
        choice_id,
        (sess.route_flags or {}).get("target_character_id"),
        (sess.route_flags or {}).get("character_id"),
        (sess.global_flags or {}).get("target_character_id"),
    ]
    for candidate in target_candidates:
        if not candidate:
            continue
        candidate_text = str(candidate)
        for cs, character in rows:
            if str(cs.character_id) == candidate_text or str(character.name) == candidate_text:
                return cs, character

    return rows[0]


def classify_input_stub(input_text: str | None, choice_id: str | None) -> dict:
    text = (input_text or "").lower()
    tags = []

    if re.search(r"\b(thank|please|sorry|help)\b", text):
        tags.append("kind")
    if re.search(r"\b(love|date|cute|kiss)\b", text):
        tags.append("flirt")
    if re.search(r"\b(stupid|hate|kill|idiot|shut up)\b", text):
        tags.append("aggressive")
    if re.search(r"\b(respect|honor|promise)\b", text):
        tags.append("respectful")
    if re.search(r"\b(lie|cheat|fake)\b", text):
        tags.append("deceptive")

    if not tags:
        tags = ["kind"]

    intent = "neutral"
    tone = "calm"
    if "aggressive" in tags:
        intent = "hostile"
        tone = "harsh"
    elif "flirt" in tags:
        intent = "romantic"
        tone = "warm"
    elif "kind" in tags:
        intent = "friendly"

    return {"behavior_tags": sorted(set(tags)), "intent": intent, "tone": tone, "choice_id": choice_id, "risk_tags": [], "confidence": 0.6}


def _ensure_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user:
        return user
    user = User(id=user_id, google_sub=f"dev-{user_id}", email=f"{user_id}@dev.local", display_name="Dev User")
    db.add(user)
    db.flush()
    return user


def _get_or_create_default_character(db: Session) -> Character:
    char = db.execute(select(Character).where(Character.name == "Default Heroine")).scalar_one_or_none()
    if char:
        return char
    char = Character(
        name="Default Heroine",
        base_personality={"kind": 0.7},
        initial_relation_vector={"trust": 0.5, "respect": 0.5, "fear": 0.1, "attraction": 0.2},
        initial_visible_score=50,
    )
    db.add(char)
    db.flush()
    return char


def _require_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> StorySession:
    sess = db.get(StorySession, session_id)
    if not sess or sess.user_id != user_id:
        raise HTTPException(status_code=404, detail="session not found")
    return sess


def _serialize_state(db: Session, sess: StorySession) -> SessionStateOut:
    char_states = db.execute(
        select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
    ).scalars().all()

    current_node = None
    if sess.current_node_id:
        node = db.get(DialogueNode, sess.current_node_id)
        if node:
            current_node = {
                "id": node.id,
                "parent_node_id": node.parent_node_id,
                "narrative_text": node.narrative_text,
                "choices": [ChoiceOut(**c) for c in (node.choices or [])],
                "created_at": node.created_at,
            }

    return SessionStateOut(
        id=sess.id,
        user_id=sess.user_id,
        status=sess.status,
        current_node_id=sess.current_node_id,
        story_id=sess.story_id,
        story_version=sess.story_version,
        global_flags=sess.global_flags,
        route_flags=sess.route_flags,
        active_characters=sess.active_characters,
        memory_summary=sess.memory_summary,
        token_budget_used=sess.token_budget_used,
        token_budget_remaining=sess.token_budget_remaining,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        character_states=[
            {
                "id": cs.id,
                "character_id": cs.character_id,
                "score_visible": cs.score_visible,
                "relation_vector": cs.relation_vector,
                "personality_drift": cs.personality_drift,
                "updated_at": cs.updated_at,
            }
            for cs in char_states
        ],
        current_node=current_node,
    )


def _load_story_pack(db: Session, story_id: str, version: int | None = None) -> Story:
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


def _story_node(pack: dict, node_id: str) -> dict | None:
    for node in (pack.get("nodes") or []):
        if str(node.get("node_id")) == str(node_id):
            return node
    return None


def _story_choices_for_response(node: dict) -> list[dict]:
    out = []
    for choice in (node.get("choices") or []):
        action_id = ((choice.get("action") or {}).get("action_id") or "action")
        out.append({"id": str(choice.get("choice_id")), "text": str(choice.get("display_text", "")), "type": str(action_id)})
    return out


def create_session(db: Session, user_id: uuid.UUID, story_id: str | None = None, version: int | None = None) -> StorySession:
    with db.begin():
        _ensure_user(db, user_id)
        char = _get_or_create_default_character(db)
        story_row = _load_story_pack(db, story_id, version) if story_id else None
        start_node = None
        if story_row:
            try:
                start_node = uuid.UUID(str((story_row.pack_json or {}).get("start_node_id")))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail={"code": "INVALID_STORY_START_NODE"}) from exc

        sess = StorySession(
            user_id=user_id,
            status="active",
            current_node_id=start_node,
            global_flags={},
            route_flags={},
            active_characters=[str(char.id)],
            memory_summary="",
            token_budget_used=0,
            token_budget_remaining=settings.session_token_budget_total,
            story_id=(story_row.story_id if story_row else None),
            story_version=(story_row.version if story_row else None),
        )
        db.add(sess)
        db.flush()

        scs = SessionCharacterState(
            session_id=sess.id,
            character_id=char.id,
            score_visible=char.initial_visible_score,
            relation_vector=char.initial_relation_vector,
            personality_drift={},
        )
        db.add(scs)
    db.refresh(sess)
    return sess


def get_session_state(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> SessionStateOut:
    sess = _require_session(db, session_id, user_id)
    return _serialize_state(db, sess)


def _preflight_required_budget(input_text: str | None) -> int:
    conservative_cost = 20 + (len(input_text or "") // 4)
    return (
        conservative_cost
        + settings.llm_preflight_classify_max_tokens
        + settings.llm_preflight_generate_prompt_max_tokens
        + settings.llm_preflight_generate_completion_max_tokens
    )


def _sum_step_tokens(db: Session, session_id: uuid.UUID, step_id: uuid.UUID) -> tuple[int, int]:
    prompt_tokens = (
        db.execute(
            select(func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0)).where(
                LLMUsageLog.session_id == session_id,
                LLMUsageLog.step_id == step_id,
            )
        ).scalar_one()
        or 0
    )
    completion_tokens = (
        db.execute(
            select(func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0)).where(
                LLMUsageLog.session_id == session_id,
                LLMUsageLog.step_id == step_id,
            )
        ).scalar_one()
        or 0
    )
    return int(prompt_tokens), int(completion_tokens)


def step_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID, input_text: str | None, choice_id: str | None, player_input: str | None = None):
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        if sess.status != "active":
            raise HTTPException(status_code=409, detail={"code": "SESSION_NOT_ACTIVE"})

        if sess.story_id:
            story_row = _load_story_pack(db, sess.story_id, sess.story_version)
            pack = story_row.pack_json or {}
            if not sess.current_node_id:
                raise HTTPException(status_code=400, detail={"code": "STORY_NODE_MISSING"})
            current_node_id = str(sess.current_node_id)
            node = _story_node(pack, current_node_id)
            if not node:
                raise HTTPException(status_code=400, detail={"code": "STORY_NODE_MISSING"})

            compiled_action = None
            selected_choice = None
            choices = node.get("choices") or []
            if choice_id is not None:
                selected_choice = next((c for c in choices if str(c.get("choice_id")) == str(choice_id)), None)
                if not selected_choice:
                    raise HTTPException(status_code=400, detail={"code": "INVALID_CHOICE_FOR_NODE"})
            elif player_input is not None:
                char_lookup = {str(c.get("name", "")).lower(): str(c.get("id")) for c in (pack.get("characters") or []) if c.get("id")}
                compiled_action = action_compiler.compile(
                    player_input,
                    {"active_characters": [str(c.get("id")) for c in (pack.get("characters") or []) if c.get("id")], "character_lookup": char_lookup, "route_flags": sess.route_flags or {}},
                )
                if not compiled_action.fallback_used:
                    selected_choice = next(
                        (
                            c
                            for c in choices
                            if (c.get("action") or {}).get("action_id") == (compiled_action.final_action or {}).get("action_id")
                            and (c.get("action") or {}).get("params", {}) == (compiled_action.final_action or {}).get("params", {})
                        ),
                        None,
                    )
                if selected_choice is None:
                    response_choices = _story_choices_for_response(node)
                    log = ActionLog(
                        session_id=sess.id,
                        node_id=None,
                        story_node_id=current_node_id,
                        story_choice_id=None,
                        player_input=(player_input or ""),
                        user_raw_input=(compiled_action.user_raw_input if compiled_action else player_input),
                        proposed_action=(compiled_action.proposed_action if compiled_action else {}),
                        final_action=(compiled_action.final_action if compiled_action else {"action_id": "clarify", "params": {}}),
                        fallback_used=True,
                        fallback_reasons=(compiled_action.reasons if compiled_action else ["UNMAPPED_INPUT"]),
                        action_confidence=(compiled_action.confidence if compiled_action else 0.0),
                        key_decision=False,
                        classification={},
                        matched_rules=[],
                        affection_delta=[],
                        branch_evaluation=[],
                    )
                    db.add(log)
                    return {
                        "node_id": uuid.uuid4(),
                        "narrative_text": "Please pick one of the available choices.",
                        "choices": response_choices,
                        "affection_delta": [],
                        "cost": {"tokens_in": 0, "tokens_out": 0, "provider": "none"},
                    }
            else:
                raise HTTPException(status_code=400, detail={"code": "CHOICE_OR_PLAYER_INPUT_REQUIRED"})

            next_node_id = str(selected_choice.get("next_node_id"))
            next_node = _story_node(pack, next_node_id)
            if not next_node:
                raise HTTPException(status_code=400, detail={"code": "INVALID_NEXT_NODE"})

            llm_runtime = get_llm_runtime()
            llm_narrative, _ = llm_runtime.narrative_with_fallback(
                db,
                prompt=f"Story node transition: {node.get('scene_brief','')} -> {next_node.get('scene_brief','')}",
                session_id=sess.id,
                step_id=uuid.uuid4(),
            )
            narrative_text = llm_narrative.narrative_text
            response_choices = _story_choices_for_response(next_node)

            try:
                sess.current_node_id = uuid.UUID(next_node_id)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=400, detail={"code": "INVALID_NEXT_NODE_ID"}) from exc
            sess.updated_at = datetime.utcnow()

            log = ActionLog(
                session_id=sess.id,
                node_id=None,
                story_node_id=current_node_id,
                story_choice_id=str(selected_choice.get("choice_id")),
                player_input=(input_text or player_input or ""),
                user_raw_input=(compiled_action.user_raw_input if compiled_action else None),
                proposed_action=(compiled_action.proposed_action if compiled_action else {}),
                final_action=((selected_choice.get("action") or {}) if compiled_action is None else compiled_action.final_action),
                fallback_used=(compiled_action.fallback_used if compiled_action else False),
                fallback_reasons=(compiled_action.reasons if compiled_action else []),
                action_confidence=(compiled_action.confidence if compiled_action else 1.0),
                key_decision=bool(selected_choice.get("is_key_decision", False)),
                classification={},
                matched_rules=[],
                affection_delta=[],
                branch_evaluation=[],
            )
            db.add(log)

            return {
                "node_id": uuid.uuid4(),
                "narrative_text": narrative_text,
                "choices": response_choices,
                "affection_delta": [],
                "cost": {"tokens_in": 0, "tokens_out": 0, "provider": "none"},
            }

        conservative_cost = 20 + (len((input_text if input_text is not None else player_input) or "") // 4)
        reserve_budget = _preflight_required_budget(input_text if input_text is not None else player_input)
        reserve_update = db.execute(
            update(StorySession)
            .where(StorySession.id == sess.id, StorySession.token_budget_remaining >= reserve_budget)
            .values(
                token_budget_used=StorySession.token_budget_used + reserve_budget,
                token_budget_remaining=StorySession.token_budget_remaining - reserve_budget,
                updated_at=datetime.utcnow(),
            )
        )
        if reserve_update.rowcount != 1:
            raise HTTPException(status_code=409, detail={"code": "TOKEN_BUDGET_EXCEEDED"})
        db.refresh(sess)

        compiled_action = None
        if player_input is not None:
            char_rows = db.execute(
                select(SessionCharacterState, Character)
                .join(Character, Character.id == SessionCharacterState.character_id)
                .where(SessionCharacterState.session_id == sess.id)
                .order_by(Character.name.asc(), SessionCharacterState.character_id.asc())
            ).all()
            character_lookup = {str(character.name).lower(): str(cs.character_id) for cs, character in char_rows}
            compiled_action = action_compiler.compile(
                player_input,
                {
                    "active_characters": sess.active_characters or [],
                    "character_lookup": character_lookup,
                    "route_flags": sess.route_flags or {},
                },
            )

        resolved_input_text = input_text if input_text is not None else player_input

        step_id = uuid.uuid4()
        llm_runtime = get_llm_runtime()

        active_state, active_character = _resolve_active_character_state(db, sess, choice_id)
        story_id = _story_id_for_session(sess)
        if active_state and active_character:
            emotion_state = build_emotion_state(
                session_id=sess.id,
                character={
                    "id": active_state.character_id,
                    "name": active_character.name,
                    "baseline": active_state.score_visible,
                },
                story_id=story_id,
                window=DEFAULT_EMOTION_WINDOW,
                db_session=db,
            )
        else:
            emotion_state = {
                "character": "none",
                "score": 0,
                "band": "neutral",
                "window": DEFAULT_EMOTION_WINDOW,
                "story_id": story_id,
            }

        behavior_policy = select_behavior_policy(story_id, emotion_state["band"]).model_dump(mode="json")

        llm_classification, classify_ok = llm_runtime.classify_with_fallback(db, text=resolved_input_text or "", session_id=sess.id, step_id=step_id)
        if classify_ok:
            cls = llm_classification.model_dump()
        else:
            cls = classify_input_stub(resolved_input_text, choice_id)

        char_states = db.execute(
            select(SessionCharacterState)
            .where(SessionCharacterState.session_id == sess.id)
            .order_by(SessionCharacterState.character_id.asc())
        ).scalars().all()

        affection_delta = []
        rule_hits_all = []
        for cs in char_states:
            result = apply_affection(
                current_score_visible=cs.score_visible,
                relation_vector=cs.relation_vector or {},
                drift=cs.personality_drift or {},
                behavior_tags=cls["behavior_tags"],
            )
            cs.score_visible = result["new_score_visible"]
            cs.relation_vector = result["new_relation_vector"]
            cs.personality_drift = result["new_drift"]
            cs.updated_at = datetime.utcnow()

            affection_delta.append(
                {
                    "char_id": str(cs.character_id),
                    "score_delta": result["score_delta"],
                    "vector_delta": result["vector_delta"],
                }
            )
            for hit in result["rule_hits"]:
                hit_copy = dict(hit)
                hit_copy["character_id"] = str(cs.character_id)
                rule_hits_all.append(hit_copy)

        ctx = build_branch_context(sess, char_states)
        branches = []
        if sess.current_node_id is not None:
            branches = db.execute(
                select(Branch).where(Branch.from_node_id == sess.current_node_id)
            ).scalars().all()
        chosen_branch, branch_evaluation = resolve_branch(branches, ctx)

        character_compact = [
            {
                "character_id": str(cs.character_id),
                "score_visible": cs.score_visible,
                "relation_vector": cs.relation_vector or {},
            }
            for cs in char_states
        ]

        branch_result = {
            "chosen_branch_id": str(chosen_branch.id) if chosen_branch else None,
            "route_type": chosen_branch.route_type if chosen_branch else None,
        }

        narrative_prompt = build_step_prompt(
            memory_summary=sess.memory_summary or "",
            branch_result=branch_result,
            character_compact=character_compact,
            player_input=resolved_input_text or "",
            classification={
                "intent": cls.get("intent"),
                "tone": cls.get("tone"),
                "behavior_tags": cls.get("behavior_tags", []),
            },
            behavior_policy=behavior_policy,
            emotion_state=emotion_state,
        )

        llm_narrative, _ = llm_runtime.narrative_with_fallback(db, prompt=narrative_prompt, session_id=sess.id, step_id=step_id)
        narrative_text = llm_narrative.narrative_text
        choices = [c.model_dump() for c in llm_narrative.choices]

        db.refresh(sess, attribute_names=["token_budget_used", "token_budget_remaining"])
        db.flush()
        tokens_in, tokens_out = _sum_step_tokens(db, sess.id, step_id)
        actual_total = tokens_in + tokens_out
        deterministic_cost = actual_total if actual_total > 0 else conservative_cost

        budget_delta = reserve_budget - deterministic_cost
        if budget_delta >= 0:
            budget_update = db.execute(
                update(StorySession)
                .where(StorySession.id == sess.id)
                .values(
                    token_budget_used=StorySession.token_budget_used - budget_delta,
                    token_budget_remaining=StorySession.token_budget_remaining + budget_delta,
                    updated_at=datetime.utcnow(),
                )
            )
        else:
            additional_charge = -budget_delta
            budget_update = db.execute(
                update(StorySession)
                .where(StorySession.id == sess.id, StorySession.token_budget_remaining >= additional_charge)
                .values(
                    token_budget_used=StorySession.token_budget_used + additional_charge,
                    token_budget_remaining=StorySession.token_budget_remaining - additional_charge,
                    updated_at=datetime.utcnow(),
                )
            )
        if budget_update.rowcount != 1:
            raise HTTPException(status_code=409, detail={"code": "TOKEN_BUDGET_EXCEEDED"})
        db.refresh(sess)

        next_remaining = sess.token_budget_remaining
        branch_result["token_budget_remaining"] = next_remaining

        node = DialogueNode(
            session_id=sess.id,
            parent_node_id=sess.current_node_id,
            node_type="player",
            player_input=resolved_input_text,
            narrative_text=narrative_text,
            choices=choices,
            branch_decision=branch_result,
        )
        db.add(node)
        db.flush()

        log = ActionLog(
            session_id=sess.id,
            node_id=node.id,
            player_input=resolved_input_text or "",
            user_raw_input=(compiled_action.user_raw_input if compiled_action else None),
            proposed_action=(compiled_action.proposed_action if compiled_action else {}),
            final_action=(compiled_action.final_action if compiled_action else {}),
            fallback_used=(compiled_action.fallback_used if compiled_action else False),
            fallback_reasons=(compiled_action.reasons if compiled_action else []),
            action_confidence=(compiled_action.confidence if compiled_action else None),
            key_decision=(compiled_action.key_decision if compiled_action else False),
            classification=cls,
            matched_rules=rule_hits_all,
            affection_delta=affection_delta,
            branch_evaluation=branch_evaluation,
        )
        db.add(log)

        sess.current_node_id = node.id
        sess.updated_at = datetime.utcnow()

        latest_usage = db.execute(
            select(LLMUsageLog)
            .where(
                LLMUsageLog.session_id == sess.id,
                LLMUsageLog.step_id == step_id,
                LLMUsageLog.operation == "generate",
                LLMUsageLog.status == "success",
            )
            .order_by(LLMUsageLog.created_at.desc())
        ).scalars().first()
        provider_name = latest_usage.provider if latest_usage else "none"

    return {
        "node_id": node.id,
        "narrative_text": narrative_text,
        "choices": choices,
        "affection_delta": affection_delta,
        "cost": {"tokens_in": tokens_in, "tokens_out": tokens_out, "provider": provider_name},
    }


def create_snapshot(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> SessionSnapshot:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        cutoff = datetime.utcnow()
        char_states = db.execute(
            select(SessionCharacterState).where(SessionCharacterState.session_id == sess.id)
        ).scalars().all()

        node_ids = [str(v) for v in db.execute(select(DialogueNode.id).where(DialogueNode.session_id == sess.id)).scalars().all()]
        action_log_ids = [str(v) for v in db.execute(select(ActionLog.id).where(ActionLog.session_id == sess.id)).scalars().all()]

        payload = {
            "session": {
                "id": str(sess.id),
                "status": sess.status,
                "current_node_id": str(sess.current_node_id) if sess.current_node_id else None,
                "global_flags": sess.global_flags,
                "route_flags": sess.route_flags,
                "active_characters": sess.active_characters,
                "memory_summary": sess.memory_summary,
                "token_budget_used": sess.token_budget_used,
                "token_budget_remaining": sess.token_budget_remaining,
            },
            "character_states": [
                {
                    "id": str(cs.id),
                    "character_id": str(cs.character_id),
                    "score_visible": cs.score_visible,
                    "relation_vector": cs.relation_vector,
                    "personality_drift": cs.personality_drift,
                    "updated_at": cs.updated_at.isoformat(),
                }
                for cs in char_states
            ],
            "cutoff_ts": cutoff.isoformat(),
            "dialogue_node_ids": node_ids,
            "action_log_ids": action_log_ids,
        }

        snapshot = SessionSnapshot(session_id=sess.id, snapshot_name="manual", state_blob=payload, created_at=cutoff)
        db.add(snapshot)
        db.flush()
    db.refresh(snapshot)
    return snapshot


def rollback_to_snapshot(db: Session, session_id: uuid.UUID, user_id: uuid.UUID, snapshot_id: uuid.UUID) -> StorySession:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        snapshot = db.get(SessionSnapshot, snapshot_id)
        if not snapshot or snapshot.session_id != sess.id:
            raise HTTPException(status_code=404, detail="snapshot not found")

        payload = snapshot.state_blob
        s = payload["session"]
        sess.status = s["status"]
        sess.current_node_id = uuid.UUID(s["current_node_id"]) if s["current_node_id"] else None
        sess.global_flags = s["global_flags"]
        sess.route_flags = s["route_flags"]
        sess.active_characters = s["active_characters"]
        sess.memory_summary = s["memory_summary"]
        sess.token_budget_used = s["token_budget_used"]
        sess.token_budget_remaining = s["token_budget_remaining"]
        sess.updated_at = datetime.utcnow()

        db.execute(delete(SessionCharacterState).where(SessionCharacterState.session_id == sess.id))
        for cs in payload["character_states"]:
            db.add(
                SessionCharacterState(
                    id=uuid.UUID(cs["id"]),
                    session_id=sess.id,
                    character_id=uuid.UUID(cs["character_id"]),
                    score_visible=cs["score_visible"],
                    relation_vector=cs["relation_vector"],
                    personality_drift=cs["personality_drift"],
                    updated_at=datetime.fromisoformat(cs["updated_at"]),
                )
            )

        keep_node_ids = [uuid.UUID(v) for v in payload.get("dialogue_node_ids", [])]
        keep_action_log_ids = [uuid.UUID(v) for v in payload.get("action_log_ids", [])]

        action_delete = delete(ActionLog).where(ActionLog.session_id == sess.id)
        if keep_action_log_ids:
            action_delete = action_delete.where(ActionLog.id.not_in(keep_action_log_ids))
        db.execute(action_delete)

        node_delete = delete(DialogueNode).where(DialogueNode.session_id == sess.id)
        if keep_node_ids:
            node_delete = node_delete.where(DialogueNode.id.not_in(keep_node_ids))
        db.execute(node_delete)

    return sess


def end_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    with db.begin():
        sess = _require_session(db, session_id, user_id)
        sess.status = "ended"
        sess.updated_at = datetime.utcnow()

        report = replay_engine.build_report(session_id=sess.id, db=db)
        replay_row = upsert_replay_report(db, session_id=sess.id, report=report)
        db.flush()

    return {
        "ended": True,
        "replay_report_id": str(replay_row.id),
        "route_type": report.get("route_type", "default"),
    }


def get_replay(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    _require_session(db, session_id, user_id)
    from app.db.models import ReplayReport

    row = db.execute(select(ReplayReport).where(ReplayReport.session_id == session_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail={"code": "REPLAY_NOT_READY"})
    return row.report_json
