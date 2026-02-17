from dataclasses import dataclass

ALLOWED_ACTIONS = {"study", "work", "rest", "date", "gift"}


@dataclass(frozen=True)
class CompiledAction:
    user_raw_input: str
    proposed_action: dict | None
    final_action: dict
    fallback_used: bool
    reasons: list[str]
    confidence: float
    key_decision: bool


class ActionCompiler:
    def __init__(self, confidence_threshold: float = 0.7) -> None:
        self.confidence_threshold = float(confidence_threshold)

    def compile(self, user_raw_input: str, session_state: dict) -> CompiledAction:
        raw = (user_raw_input or "").strip()
        proposed, confidence, reasons = self._propose(raw, session_state)

        if proposed is None:
            return CompiledAction(
                user_raw_input=raw,
                proposed_action=None,
                final_action={"action_id": "clarify", "params": {}},
                fallback_used=True,
                reasons=reasons or ["UNMAPPED_INPUT"],
                confidence=confidence,
                key_decision=False,
            )

        valid, validate_reasons = self._validate(proposed, session_state)
        if confidence < self.confidence_threshold:
            return CompiledAction(
                user_raw_input=raw,
                proposed_action=proposed,
                final_action={"action_id": "clarify", "params": {}},
                fallback_used=True,
                reasons=["LOW_CONFIDENCE"],
                confidence=confidence,
                key_decision=False,
            )

        if not valid:
            return CompiledAction(
                user_raw_input=raw,
                proposed_action=proposed,
                final_action={"action_id": "rest", "params": {}},
                fallback_used=True,
                reasons=validate_reasons,
                confidence=confidence,
                key_decision=False,
            )

        action_id = proposed["action_id"]
        return CompiledAction(
            user_raw_input=raw,
            proposed_action=proposed,
            final_action=proposed,
            fallback_used=False,
            reasons=[],
            confidence=confidence,
            key_decision=action_id in {"date", "gift"},
        )

    def _propose(self, raw: str, session_state: dict) -> tuple[dict | None, float, list[str]]:
        text = raw.lower().strip()
        if not text:
            return None, 0.0, ["UNMAPPED_INPUT"]

        if text in {"study", "learn", "read"}:
            return {"action_id": "study", "params": {}}, 0.95, []
        if text in {"work", "job", "earn"}:
            return {"action_id": "work", "params": {}}, 0.95, []
        if text in {"rest", "sleep", "wait"}:
            return {"action_id": "rest", "params": {}}, 0.95, []

        if text.startswith("date "):
            target_raw = text.split(" ", 1)[1].strip()
            target = self._resolve_target(target_raw, session_state)
            if target:
                return {"action_id": "date", "params": {"target": target}}, 0.9, []
            return {"action_id": "date", "params": {"target": target_raw}}, 0.75, []

        if text.startswith("gift "):
            chunks = text.split()
            if len(chunks) >= 3:
                target = self._resolve_target(chunks[1], session_state) or chunks[1]
                gift_type = chunks[2]
                return {"action_id": "gift", "params": {"target": target, "gift_type": gift_type}}, 0.9, []
            return {"action_id": "gift", "params": {}}, 0.6, ["INVALID_GIFT_FORMAT"]

        return None, 0.0, ["UNMAPPED_INPUT"]

    @staticmethod
    def _resolve_target(target_raw: str, session_state: dict) -> str | None:
        lookup = session_state.get("character_lookup") or {}
        key = str(target_raw).strip().lower()
        if key in lookup:
            return str(lookup[key])
        return None

    @staticmethod
    def _validate(action: dict, session_state: dict) -> tuple[bool, list[str]]:
        action_id = action.get("action_id")
        if action_id not in ALLOWED_ACTIONS:
            return False, ["UNKNOWN_ACTION"]

        params = action.get("params") or {}
        active = {str(v) for v in (session_state.get("active_characters") or [])}

        if action_id == "date":
            target = str(params.get("target") or "")
            if not target:
                return False, ["MISSING_TARGET"]
            if target not in active:
                return False, ["TARGET_LOCKED"]

        if action_id == "gift":
            target = str(params.get("target") or "")
            gift_type = str(params.get("gift_type") or "")
            if not target:
                return False, ["MISSING_TARGET"]
            if target not in active:
                return False, ["TARGET_LOCKED"]
            if not gift_type:
                return False, ["MISSING_GIFT_TYPE"]

        return True, []
