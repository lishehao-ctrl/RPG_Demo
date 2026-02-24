import json
import re
import time

from app.modules.llm.base import LLMProvider

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_KEYWORD_GROUPS: tuple[set[str], ...] = (
    {"study", "class", "learn", "library", "notes", "review"},
    {"work", "job", "money", "paid", "shift", "cash", "earn"},
    {"rest", "sleep", "recover", "break", "pause"},
    {"date", "social", "meet", "talk", "alice", "hang", "walk"},
    {"gift", "present", "snack"},
)


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self):
        self.generate_calls = 0
        self.fail_generate = False
        self.invalid_generate_once = False

    @staticmethod
    def _normalize_text(value: object) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @classmethod
    def _tokens(cls, value: object) -> set[str]:
        return set(_TOKEN_RE.findall(cls._normalize_text(value)))

    @staticmethod
    def _extract_selection_context(prompt: str) -> dict:
        marker = "Context:"
        if marker not in prompt:
            return {}
        raw = prompt.split(marker, 1)[1].strip()
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _extract_author_task(prompt: str, *, fallback: str = "seed_expand") -> str:
        marker = '"task":"'
        start = prompt.find(marker)
        if start < 0:
            return fallback
        start += len(marker)
        end = prompt.find('"', start)
        if end < 0:
            return fallback
        task = prompt[start:end].strip().lower()
        return task or fallback

    @classmethod
    def _fake_author_idea_blueprint(cls, task: str) -> dict:
        return {
            "core_conflict": {
                "protagonist": "student",
                "opposition_actor": "roommate",
                "scarce_resource": "scholarship",
                "deadline": "one week",
                "irreversible_risk": "lose critical funding",
            },
            "tension_loop_plan": {
                "pressure_open": {
                    "objective": f"open conflict for {task}",
                    "stakes": "time pressure begins immediately",
                    "required_entities": ["student", "roommate", "scholarship"],
                    "risk_level": 3,
                },
                "pressure_escalation": {
                    "objective": "raise cost of indecision",
                    "stakes": "social trust and performance degrade",
                    "required_entities": ["roommate", "advisor"],
                    "risk_level": 4,
                },
                "recovery_window": {
                    "objective": "offer stabilization choice",
                    "stakes": "tempo vs resilience tradeoff",
                    "required_entities": ["student"],
                    "risk_level": 2,
                },
                "decision_gate": {
                    "objective": "commit to irreversible direction",
                    "stakes": "future trajectory is locked",
                    "required_entities": ["scholarship", "project"],
                    "risk_level": 5,
                },
            },
            "branch_design": {
                "high_risk_push": {
                    "short_term_gain": "fast progress",
                    "long_term_cost": "relationship damage",
                    "signature_action_type": "study",
                },
                "recovery_stabilize": {
                    "short_term_gain": "energy recovery",
                    "long_term_cost": "less immediate output",
                    "signature_action_type": "rest",
                },
            },
            "lexical_anchors": {
                "must_include_terms": ["roommate", "scholarship", "deadline"],
                "avoid_generic_labels": ["Option A", "Option B", "Take action"],
            },
        }

    @classmethod
    def _fake_author_cast_blueprint(cls, task: str) -> dict:
        _ = task
        return {
            "target_npc_count": 4,
            "npc_roster": [
                {
                    "name": "Alice",
                    "role": "support friend",
                    "motivation": "Keep the team together before the deadline.",
                    "tension_hook": "Worries that rushing will cause irreversible mistakes.",
                    "relationship_to_protagonist": "Trusted classmate who shares workload pressure.",
                },
                {
                    "name": "Reed",
                    "role": "rival competitor",
                    "motivation": "Win recognition by exposing weak spots in the project.",
                    "tension_hook": "Pushes the protagonist into high-risk shortcuts.",
                    "relationship_to_protagonist": "Academic rival with overlapping goals.",
                },
                {
                    "name": "Professor Lin",
                    "role": "gatekeeper advisor",
                    "motivation": "Protect evaluation fairness and long-term growth.",
                    "tension_hook": "Will block progress if evidence quality is weak.",
                    "relationship_to_protagonist": "Advisor who controls recommendation outcomes.",
                },
            ],
            "beat_presence": {
                "pressure_open": ["Alice", "Reed"],
                "pressure_escalation": ["Reed", "Professor Lin"],
                "recovery_window": ["Alice", "Professor Lin"],
                "decision_gate": ["Alice", "Reed", "Professor Lin"],
            },
        }

    @classmethod
    def _fake_author_assist_payload(cls, task: str) -> dict:
        return {
            "suggestions": {
                "meta": {"title": "Fake Author Assist"},
                "characters": {
                    "npcs": [
                        {"name": "Alice", "role": "support friend", "traits": ["warm", "observant"]},
                        {"name": "Reed", "role": "rival competitor", "traits": ["ambitious", "sharp"]},
                        {"name": "Professor Lin", "role": "gatekeeper advisor", "traits": ["strict", "fair"]},
                    ]
                },
                "flow": {
                    "start_scene_key": "pressure_open",
                    "scenes": [
                        {
                            "scene_key": "pressure_open",
                            "title": "Pressure Open",
                            "setup": "Conflict opens under deadline pressure.",
                            "options": [
                                {"option_key": "push", "label": "Push hard on evidence", "action_type": "study"},
                                {"option_key": "recover", "label": "Recover before escalation", "action_type": "rest"},
                            ],
                        },
                        {
                            "scene_key": "pressure_escalation",
                            "title": "Pressure Escalation",
                            "setup": "Costs rise quickly.",
                            "options": [
                                {"option_key": "public", "label": "Escalate publicly", "action_type": "study"},
                                {"option_key": "private", "label": "Probe quietly", "action_type": "work"},
                            ],
                        },
                        {
                            "scene_key": "recovery_window",
                            "title": "Recovery Window",
                            "setup": "A brief chance to stabilize.",
                            "options": [
                                {"option_key": "reset", "label": "Reset and plan", "action_type": "rest"},
                                {"option_key": "push", "label": "Skip reset and push", "action_type": "study"},
                            ],
                        },
                        {
                            "scene_key": "decision_gate",
                            "title": "Decision Gate",
                            "setup": "Choose a final stance.",
                            "is_end": True,
                            "options": [
                                {"option_key": "commit", "label": "Commit to evidence path", "action_type": "study"},
                                {"option_key": "repair", "label": "Repair relationship and split cost", "action_type": "date"},
                            ],
                        },
                    ],
                },
            },
            "patch_preview": [
                {
                    "id": f"fake_{task}_meta_title",
                    "path": "meta.title",
                    "label": "Refresh title from fake assist",
                    "value": "Fake Author Assist",
                }
            ],
            "warnings": [],
        }

    @classmethod
    def _select_choice_from_context(cls, context: dict) -> tuple[str, float] | None:
        player_input = cls._normalize_text(context.get("player_input"))
        input_tokens = cls._tokens(player_input)
        if not player_input or not input_tokens:
            return None

        valid_choice_ids = [
            str(choice_id).strip()
            for choice_id in (context.get("valid_choice_ids") or [])
            if str(choice_id).strip()
        ]
        valid_choice_set = set(valid_choice_ids)
        if not valid_choice_set:
            return None

        visible_choices: list[tuple[int, str, str, set[str]]] = []
        for index, raw_choice in enumerate(context.get("visible_choices") or []):
            if not isinstance(raw_choice, dict):
                continue
            choice_id = str(raw_choice.get("choice_id") or "").strip()
            if not choice_id or choice_id not in valid_choice_set:
                continue
            display_text = cls._normalize_text(raw_choice.get("display_text"))
            choice_tokens = cls._tokens(display_text)
            visible_choices.append((index, choice_id, display_text, choice_tokens))
        if not visible_choices:
            return None

        scored: list[tuple[float, int, str]] = []
        for index, choice_id, display_text, choice_tokens in visible_choices:
            score = 0.0
            if player_input == display_text:
                score += 100.0

            overlap = input_tokens & choice_tokens
            score += float(len(overlap)) * 10.0

            for group in _KEYWORD_GROUPS:
                if input_tokens & group and choice_tokens & group:
                    score += 4.0

            for token in input_tokens:
                if token and token in display_text:
                    score += 1.0

            if score > 0:
                scored.append((score, index, choice_id))
        if not scored:
            return None

        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        top_score, _top_index, top_choice_id = scored[0]
        confidence = max(0.0, min(0.95, 0.55 + min(top_score, 20.0) / 40.0))
        return top_choice_id, round(confidence, 2)

    async def generate(
        self,
        prompt: str,
        *,
        request_id: str,
        timeout_s: float | None,
        model: str,
        connect_timeout_s: float | None = None,
        read_timeout_s: float | None = None,
        write_timeout_s: float | None = None,
        pool_timeout_s: float | None = None,
        max_tokens_override: int | None = None,
        temperature_override: float | None = None,
        messages_override: list[dict] | None = None,
    ):
        started = time.perf_counter()
        self.generate_calls += 1
        if self.fail_generate:
            raise RuntimeError("fake generate failure")
        effective_prompt = str(prompt or "")
        if isinstance(messages_override, list) and messages_override:
            fragments: list[str] = []
            for item in messages_override:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                fragments.append(f"[{role}] {content}")
            if fragments:
                effective_prompt = "\n".join(fragments)
        prompt_lower = effective_prompt.lower()
        if self.invalid_generate_once:
            self.invalid_generate_once = False
            payload = {"narrative": "bad schema"}
        elif "author idea expansion task" in prompt_lower or "author idea repair task" in prompt_lower:
            task = self._extract_author_task(effective_prompt)
            payload = self._fake_author_idea_blueprint(task)
        elif "author cast expansion task" in prompt_lower:
            task = self._extract_author_task(effective_prompt)
            payload = self._fake_author_cast_blueprint(task)
        elif (
            "author story build task" in prompt_lower
            or "author-assist task" in prompt_lower
            or "author-assist repair task" in prompt_lower
        ):
            task = self._extract_author_task(effective_prompt)
            payload = self._fake_author_assist_payload(task)
        elif "story selection task" in prompt_lower:
            context = self._extract_selection_context(effective_prompt)
            selected = self._select_choice_from_context(context)
            if selected:
                selected_choice_id, confidence = selected
                payload = {
                    "choice_id": selected_choice_id,
                    "use_fallback": False,
                    "confidence": confidence,
                    "intent_id": None,
                    "notes": "fake_selector_context_match",
                }
            else:
                payload = {
                    "choice_id": None,
                    "use_fallback": True,
                    "confidence": 0.0,
                    "intent_id": None,
                    "notes": "fake_selector_fallback",
                }
        else:
            payload = {
                "narrative_text": "[llm] The evening breeze passes and she waits for your response.",
                "choices": [
                    {"id": "c1", "text": "Reply softly", "type": "dialog"},
                    {"id": "c2", "text": "Stay silent", "type": "action"},
                ],
            }
        usage = {
            "model": model,
            "prompt_tokens": max(1, len(effective_prompt) // 4),
            "completion_tokens": 64,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "success",
            "error_message": None,
        }
        return payload, usage
