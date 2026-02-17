import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActionLog, SessionCharacterState
from app.modules.narrative.behavior_policy import BehaviorPolicy

DEFAULT_EMOTION_WINDOW = 6
BANDS = ["v_hostile", "hostile", "cool", "neutral", "warm", "friendly", "ally"]


@dataclass(frozen=True)
class StoryEmotionConfig:
    breakpoints: tuple[int, int, int, int, int, int, int, int]
    policy_by_band: dict[str, BehaviorPolicy]


STORY_CONFIG: dict[str, StoryEmotionConfig] = {
    "default": StoryEmotionConfig(
        breakpoints=(-100, -70, -40, -10, 10, 35, 65, 100),
        policy_by_band={
            "v_hostile": BehaviorPolicy(disclosure_level="closed", helpfulness=5, aggression=90),
            "hostile": BehaviorPolicy(disclosure_level="closed", helpfulness=10, aggression=75),
            "cool": BehaviorPolicy(disclosure_level="guarded", helpfulness=25, aggression=55),
            "neutral": BehaviorPolicy(disclosure_level="balanced", helpfulness=50, aggression=35),
            "warm": BehaviorPolicy(disclosure_level="balanced", helpfulness=65, aggression=20),
            "friendly": BehaviorPolicy(disclosure_level="open", helpfulness=80, aggression=10),
            "ally": BehaviorPolicy(disclosure_level="transparent", helpfulness=95, aggression=5),
        },
    ),
    "noir": StoryEmotionConfig(
        breakpoints=(-100, -75, -45, 0, 30, 55, 80, 100),
        policy_by_band={
            "v_hostile": BehaviorPolicy(disclosure_level="closed", helpfulness=0, aggression=95),
            "hostile": BehaviorPolicy(disclosure_level="closed", helpfulness=10, aggression=80),
            "cool": BehaviorPolicy(disclosure_level="guarded", helpfulness=20, aggression=60),
            "neutral": BehaviorPolicy(disclosure_level="guarded", helpfulness=45, aggression=45),
            "warm": BehaviorPolicy(disclosure_level="balanced", helpfulness=60, aggression=25),
            "friendly": BehaviorPolicy(disclosure_level="open", helpfulness=75, aggression=15),
            "ally": BehaviorPolicy(disclosure_level="transparent", helpfulness=92, aggression=5),
        },
    ),
}


def _clamp_score(score: int) -> int:
    return max(-100, min(100, int(score)))


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _aggregate_row_delta_for_character(affection_delta: list, character_id: uuid.UUID | str) -> int:
    char_key = str(character_id)
    items = [row for row in (affection_delta or []) if str((row or {}).get("char_id")) == char_key]
    if not items:
        return 0

    emotion_sum = 0.0
    has_emotion_dim = False
    for item in items:
        if item.get("dim") == "emotion":
            has_emotion_dim = True
            emotion_sum += _to_float(item.get("delta", 0))

    if has_emotion_dim:
        return int(round(emotion_sum))

    total = 0.0
    for item in items:
        if "delta" in item:
            total += _to_float(item.get("delta"))
        total += _to_float(item.get("score_delta"))
        vec = item.get("vector_delta") or {}
        if isinstance(vec, dict):
            for val in vec.values():
                total += _to_float(val)
    return int(round(total))


def compute_emotion_score(
    session_id: uuid.UUID,
    character_id: uuid.UUID,
    *,
    window: int = DEFAULT_EMOTION_WINDOW,
    db_session: Session,
) -> int:
    baseline_current = db_session.execute(
        select(SessionCharacterState.score_visible).where(
            SessionCharacterState.session_id == session_id,
            SessionCharacterState.character_id == character_id,
        )
    ).scalar_one_or_none()
    current_score = int(baseline_current) if baseline_current is not None else 0

    rows = db_session.execute(
        select(ActionLog.id, ActionLog.affection_delta)
        .where(ActionLog.session_id == session_id)
        .order_by(ActionLog.id.asc())
    ).all()

    step_deltas = [_aggregate_row_delta_for_character(row.affection_delta or [], character_id) for row in rows]
    persisted_total = sum(step_deltas)
    baseline = current_score - persisted_total

    total_delta = sum(step_deltas[-max(1, int(window)):])
    return _clamp_score(int(round(baseline + total_delta)))


def score_to_band(story_id: str, score: int) -> str:
    cfg = STORY_CONFIG.get(story_id) or STORY_CONFIG["default"]
    score = _clamp_score(score)
    points = cfg.breakpoints
    for idx, band in enumerate(BANDS):
        if idx == len(BANDS) - 1:
            return band
        if score < points[idx + 1]:
            return band
    return BANDS[-1]


def select_behavior_policy(story_id: str, band: str) -> BehaviorPolicy:
    cfg = STORY_CONFIG.get(story_id) or STORY_CONFIG["default"]
    return cfg.policy_by_band[band]


def build_emotion_state(
    *,
    session_id: uuid.UUID,
    character: dict,
    story_id: str,
    window: int = DEFAULT_EMOTION_WINDOW,
    db_session: Session | None = None,
    action_rows: list[dict] | None = None,
) -> dict:
    character_id = uuid.UUID(str(character.get("id")))
    baseline = int(character.get("baseline", 0) or 0)

    if action_rows is None:
        if db_session is None:
            raise ValueError("db_session is required when action_rows is not provided")
        rows = db_session.execute(
            select(ActionLog.id, ActionLog.affection_delta)
            .where(ActionLog.session_id == session_id)
            .order_by(ActionLog.id.asc())
        ).all()
        normalized_rows = [{"id": str(row.id), "affection_delta": row.affection_delta or []} for row in rows]
    else:
        normalized_rows = sorted(action_rows, key=lambda row: str(row.get("id", "")))

    step_deltas = [_aggregate_row_delta_for_character(row.get("affection_delta") or [], character_id) for row in normalized_rows]
    if db_session is not None and action_rows is None:
        baseline = baseline - sum(step_deltas)

    total_delta = sum(step_deltas[-max(1, int(window)):])
    score = _clamp_score(int(round(baseline + total_delta)))
    band = score_to_band(story_id, score)

    return {
        "character": character.get("name") or str(character_id),
        "score": score,
        "band": band,
        "window": int(window),
        "story_id": story_id,
    }
