from __future__ import annotations

import json
import re

import httpx
from pydantic import ValidationError

from app.modules.llm.runtime.errors import (
    ASSIST_ERROR_HTTP_STATUS,
    ASSIST_ERROR_JSON_PARSE,
    ASSIST_ERROR_NETWORK,
    ASSIST_ERROR_SCHEMA_VALIDATE,
    ASSIST_ERROR_TIMEOUT,
    NARRATIVE_ERROR_HTTP_STATUS,
    NARRATIVE_ERROR_JSON_PARSE,
    NARRATIVE_ERROR_NETWORK,
    NARRATIVE_ERROR_SCHEMA_VALIDATE,
    NARRATIVE_ERROR_TIMEOUT,
    AuthorAssistParseError,
    NarrativeParseError,
)
from app.modules.llm.schemas import NarrativeOutput

_TOKEN_REDACTION_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", re.IGNORECASE)


def sanitize_raw_snippet(raw: object, max_len: int = 200) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        try:
            text = json.dumps(raw, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            text = str(raw)
    else:
        text = str(raw)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = _TOKEN_REDACTION_RE.sub("[REDACTED_KEY]", text)
    text = " ".join(text.split())
    text = text.replace("|", "/")
    if not text:
        return None
    return text[:max_len]


def extract_json_fragment(raw_text: str) -> str | None:
    if not raw_text:
        return None
    fenced = _FENCED_JSON_RE.search(raw_text)
    if fenced:
        return fenced.group(1).strip()
    left = raw_text.find("{")
    right = raw_text.rfind("}")
    if left == -1 or right == -1 or right <= left:
        return None
    return raw_text[left : right + 1].strip()


def narrative_error_kind(exc: Exception) -> str:
    if isinstance(exc, NarrativeParseError):
        return exc.error_kind
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return NARRATIVE_ERROR_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return NARRATIVE_ERROR_HTTP_STATUS
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ),
    ):
        return NARRATIVE_ERROR_NETWORK
    return NARRATIVE_ERROR_NETWORK


def narrative_raw_snippet(exc: Exception, raw: object | None) -> str | None:
    if isinstance(exc, NarrativeParseError) and exc.raw_snippet:
        return exc.raw_snippet
    return sanitize_raw_snippet(raw)


def assist_error_kind(exc: Exception) -> str:
    if isinstance(exc, AuthorAssistParseError):
        return exc.error_kind
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return ASSIST_ERROR_TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return ASSIST_ERROR_HTTP_STATUS
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ),
    ):
        return ASSIST_ERROR_NETWORK
    return ASSIST_ERROR_NETWORK


def assist_raw_snippet(exc: Exception, raw: object | None) -> str | None:
    if isinstance(exc, AuthorAssistParseError) and exc.raw_snippet:
        return exc.raw_snippet
    return sanitize_raw_snippet(raw)


def format_narrative_chain_error(
    last_error: Exception | None,
    *,
    error_kind: str | None,
    raw_snippet: str | None,
) -> str:
    detail = f": {last_error}" if last_error else ""
    message = f"narrative provider chain exhausted{detail}"
    if error_kind:
        message = f"{message} | kind={error_kind}"
    if raw_snippet:
        message = f"{message} | raw={raw_snippet}"
    return message


def format_assist_chain_error(
    last_error: Exception | None,
    *,
    error_kind: str | None,
    raw_snippet: str | None,
) -> str:
    detail = f": {last_error}" if last_error else ""
    message = f"author assist provider chain exhausted{detail}"
    if error_kind:
        message = f"{message} | kind={error_kind}"
    if raw_snippet:
        message = f"{message} | raw={raw_snippet}"
    return message


def parse_narrative(raw: object) -> NarrativeOutput:
    parsed_payload: object = raw
    original_raw_snippet = sanitize_raw_snippet(raw)

    if isinstance(parsed_payload, str):
        raw_text = parsed_payload.strip()
        if not raw_text:
            raise NarrativeParseError(
                "narrative json parse error: empty response",
                error_kind=NARRATIVE_ERROR_JSON_PARSE,
                raw_snippet=original_raw_snippet,
            )
        try:
            parsed_payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            fragment = extract_json_fragment(raw_text)
            if fragment:
                try:
                    parsed_payload = json.loads(fragment)
                except json.JSONDecodeError as fragment_exc:
                    raise NarrativeParseError(
                        f"narrative json parse error: {fragment_exc}",
                        error_kind=NARRATIVE_ERROR_JSON_PARSE,
                        raw_snippet=original_raw_snippet,
                    ) from exc
            else:
                raise NarrativeParseError(
                    f"narrative json parse error: {exc}",
                    error_kind=NARRATIVE_ERROR_JSON_PARSE,
                    raw_snippet=original_raw_snippet,
                ) from exc

    try:
        return NarrativeOutput.model_validate(parsed_payload)
    except ValidationError as exc:
        raise NarrativeParseError(
            f"narrative schema validate error: {exc}",
            error_kind=NARRATIVE_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        ) from exc


def parse_author_assist(raw: object) -> dict:
    parsed_payload: object = raw
    original_raw_snippet = sanitize_raw_snippet(raw)

    if isinstance(parsed_payload, str):
        raw_text = parsed_payload.strip()
        if not raw_text:
            raise AuthorAssistParseError(
                "author-assist json parse error: empty response",
                error_kind=ASSIST_ERROR_JSON_PARSE,
                raw_snippet=original_raw_snippet,
            )
        try:
            parsed_payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            fragment = extract_json_fragment(raw_text)
            if fragment:
                try:
                    parsed_payload = json.loads(fragment)
                except json.JSONDecodeError as fragment_exc:
                    raise AuthorAssistParseError(
                        f"author-assist json parse error: {fragment_exc}",
                        error_kind=ASSIST_ERROR_JSON_PARSE,
                        raw_snippet=original_raw_snippet,
                    ) from exc
            else:
                raise AuthorAssistParseError(
                    f"author-assist json parse error: {exc}",
                    error_kind=ASSIST_ERROR_JSON_PARSE,
                    raw_snippet=original_raw_snippet,
                ) from exc

    if not isinstance(parsed_payload, dict):
        raise AuthorAssistParseError(
            "author-assist schema validate error: top-level payload must be a JSON object",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    suggestions = parsed_payload.get("suggestions")
    patch_preview = parsed_payload.get("patch_preview")
    warnings = parsed_payload.get("warnings")

    if not isinstance(suggestions, dict) or not isinstance(patch_preview, list):
        raise AuthorAssistParseError(
            "author-assist schema validate error: missing suggestions/patch_preview",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )
    if warnings is None:
        warnings = []
    if not isinstance(warnings, list):
        raise AuthorAssistParseError(
            "author-assist schema validate error: warnings must be a list",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    normalized_patch_preview: list[dict] = [item for item in patch_preview if isinstance(item, dict)]
    normalized_warnings = [str(item) for item in warnings]
    return {
        "suggestions": suggestions,
        "patch_preview": normalized_patch_preview,
        "warnings": normalized_warnings,
    }


def parse_author_idea_blueprint(raw: object) -> dict:
    parsed_payload: object = raw
    original_raw_snippet = sanitize_raw_snippet(raw)

    if isinstance(parsed_payload, str):
        raw_text = parsed_payload.strip()
        if not raw_text:
            raise AuthorAssistParseError(
                "author-idea json parse error: empty response",
                error_kind=ASSIST_ERROR_JSON_PARSE,
                raw_snippet=original_raw_snippet,
            )
        try:
            parsed_payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            fragment = extract_json_fragment(raw_text)
            if fragment:
                try:
                    parsed_payload = json.loads(fragment)
                except json.JSONDecodeError as fragment_exc:
                    raise AuthorAssistParseError(
                        f"author-idea json parse error: {fragment_exc}",
                        error_kind=ASSIST_ERROR_JSON_PARSE,
                        raw_snippet=original_raw_snippet,
                    ) from exc
            else:
                raise AuthorAssistParseError(
                    f"author-idea json parse error: {exc}",
                    error_kind=ASSIST_ERROR_JSON_PARSE,
                    raw_snippet=original_raw_snippet,
                ) from exc

    if not isinstance(parsed_payload, dict):
        raise AuthorAssistParseError(
            "author-idea schema validate error: top-level payload must be a JSON object",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    def _clean_text(value: object) -> str:
        return " ".join(str(value or "").split())

    core_conflict_raw = parsed_payload.get("core_conflict")
    if not isinstance(core_conflict_raw, dict):
        raise AuthorAssistParseError(
            "author-idea schema validate error: missing core_conflict",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )
    core_conflict = {
        "protagonist": _clean_text(core_conflict_raw.get("protagonist")),
        "opposition_actor": _clean_text(core_conflict_raw.get("opposition_actor")),
        "scarce_resource": _clean_text(core_conflict_raw.get("scarce_resource")),
        "deadline": _clean_text(core_conflict_raw.get("deadline")),
        "irreversible_risk": _clean_text(core_conflict_raw.get("irreversible_risk")),
    }
    if not all(core_conflict.values()):
        raise AuthorAssistParseError(
            "author-idea schema validate error: core_conflict fields are required",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(core_conflict_raw),
        )

    plan_raw = parsed_payload.get("tension_loop_plan")
    if not isinstance(plan_raw, dict):
        raise AuthorAssistParseError(
            "author-idea schema validate error: missing tension_loop_plan",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )
    tension_loop_plan: dict[str, dict] = {}
    for beat in ("pressure_open", "pressure_escalation", "recovery_window", "decision_gate"):
        node = plan_raw.get(beat)
        if not isinstance(node, dict):
            raise AuthorAssistParseError(
                f"author-idea schema validate error: missing tension_loop_plan.{beat}",
                error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
                raw_snippet=sanitize_raw_snippet(plan_raw),
            )
        required_entities_raw = node.get("required_entities")
        required_entities = []
        if isinstance(required_entities_raw, list):
            for item in required_entities_raw:
                text = _clean_text(item)
                if text:
                    required_entities.append(text)
        if not required_entities:
            required_entities = [core_conflict["protagonist"], core_conflict["opposition_actor"]]
        risk_level = node.get("risk_level")
        try:
            risk_level = int(risk_level)
        except Exception:  # noqa: BLE001
            risk_level = 3
        risk_level = max(1, min(5, risk_level))
        objective = _clean_text(node.get("objective"))
        stakes = _clean_text(node.get("stakes"))
        if not objective or not stakes:
            raise AuthorAssistParseError(
                f"author-idea schema validate error: missing objective/stakes in {beat}",
                error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
                raw_snippet=sanitize_raw_snippet(node),
            )
        tension_loop_plan[beat] = {
            "objective": objective,
            "stakes": stakes,
            "required_entities": required_entities[:6],
            "risk_level": risk_level,
        }

    branch_raw = parsed_payload.get("branch_design")
    if not isinstance(branch_raw, dict):
        raise AuthorAssistParseError(
            "author-idea schema validate error: missing branch_design",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )
    branch_design: dict[str, dict[str, str]] = {}
    for key in ("high_risk_push", "recovery_stabilize"):
        branch = branch_raw.get(key)
        if not isinstance(branch, dict):
            raise AuthorAssistParseError(
                f"author-idea schema validate error: missing branch_design.{key}",
                error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
                raw_snippet=sanitize_raw_snippet(branch_raw),
            )
        short_gain = _clean_text(branch.get("short_term_gain"))
        long_cost = _clean_text(branch.get("long_term_cost"))
        action_type = _clean_text(branch.get("signature_action_type")).lower()
        if not short_gain or not long_cost or not action_type:
            raise AuthorAssistParseError(
                f"author-idea schema validate error: missing branch_design fields in {key}",
                error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
                raw_snippet=sanitize_raw_snippet(branch),
            )
        branch_design[key] = {
            "short_term_gain": short_gain,
            "long_term_cost": long_cost,
            "signature_action_type": action_type,
        }

    anchors_raw = parsed_payload.get("lexical_anchors")
    if not isinstance(anchors_raw, dict):
        raise AuthorAssistParseError(
            "author-idea schema validate error: missing lexical_anchors",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    def _dedupe_text_list(values: object, *, fallback: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        candidates = values if isinstance(values, list) else []
        for item in candidates:
            text = _clean_text(item)
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        if out:
            return out[:12]
        return fallback

    must_include = _dedupe_text_list(
        anchors_raw.get("must_include_terms"),
        fallback=[
            core_conflict["protagonist"],
            core_conflict["opposition_actor"],
            core_conflict["scarce_resource"],
        ],
    )
    avoid_generic = _dedupe_text_list(
        anchors_raw.get("avoid_generic_labels"),
        fallback=["Option A", "Option B", "Take action"],
    )

    return {
        "core_conflict": core_conflict,
        "tension_loop_plan": tension_loop_plan,
        "branch_design": branch_design,
        "lexical_anchors": {
            "must_include_terms": must_include,
            "avoid_generic_labels": avoid_generic,
        },
    }


def parse_author_cast_blueprint(raw: object) -> dict:
    parsed_payload: object = raw
    original_raw_snippet = sanitize_raw_snippet(raw)

    if isinstance(parsed_payload, str):
        raw_text = parsed_payload.strip()
        if not raw_text:
            raise AuthorAssistParseError(
                "author-cast json parse error: empty response",
                error_kind=ASSIST_ERROR_JSON_PARSE,
                raw_snippet=original_raw_snippet,
            )
        try:
            parsed_payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            fragment = extract_json_fragment(raw_text)
            if fragment:
                try:
                    parsed_payload = json.loads(fragment)
                except json.JSONDecodeError as fragment_exc:
                    raise AuthorAssistParseError(
                        f"author-cast json parse error: {fragment_exc}",
                        error_kind=ASSIST_ERROR_JSON_PARSE,
                        raw_snippet=original_raw_snippet,
                    ) from exc
            else:
                raise AuthorAssistParseError(
                    f"author-cast json parse error: {exc}",
                    error_kind=ASSIST_ERROR_JSON_PARSE,
                    raw_snippet=original_raw_snippet,
                ) from exc

    if not isinstance(parsed_payload, dict):
        raise AuthorAssistParseError(
            "author-cast schema validate error: top-level payload must be a JSON object",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    def _clean_text(value: object) -> str:
        return " ".join(str(value or "").split())

    target_raw = parsed_payload.get("target_npc_count")
    if target_raw is None:
        raise AuthorAssistParseError(
            "author-cast schema validate error: missing target_npc_count",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )
    try:
        target_npc_count = int(target_raw)
    except Exception as exc:  # noqa: BLE001
        raise AuthorAssistParseError(
            "author-cast schema validate error: target_npc_count must be integer",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        ) from exc
    target_npc_count = max(3, min(6, target_npc_count))

    roster_raw = parsed_payload.get("npc_roster")
    if not isinstance(roster_raw, list):
        raise AuthorAssistParseError(
            "author-cast schema validate error: missing npc_roster",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    npc_roster: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for item in roster_raw:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        role = _clean_text(item.get("role"))
        motivation = _clean_text(item.get("motivation"))
        tension_hook = _clean_text(item.get("tension_hook"))
        relationship = _clean_text(item.get("relationship_to_protagonist"))
        if not all([name, role, motivation, tension_hook, relationship]):
            continue
        dedupe_key = name.lower()
        if dedupe_key in seen_names:
            continue
        seen_names.add(dedupe_key)
        npc_roster.append(
            {
                "name": name,
                "role": role,
                "motivation": motivation,
                "tension_hook": tension_hook,
                "relationship_to_protagonist": relationship,
            }
        )
        if len(npc_roster) >= 6:
            break

    if not npc_roster:
        raise AuthorAssistParseError(
            "author-cast schema validate error: npc_roster must include at least one valid npc",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    beat_presence_raw = parsed_payload.get("beat_presence")
    if not isinstance(beat_presence_raw, dict):
        raise AuthorAssistParseError(
            "author-cast schema validate error: missing beat_presence",
            error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
            raw_snippet=sanitize_raw_snippet(parsed_payload),
        )

    known_names = [npc["name"] for npc in npc_roster]
    beat_presence: dict[str, list[str]] = {}
    for beat in ("pressure_open", "pressure_escalation", "recovery_window", "decision_gate"):
        raw_names = beat_presence_raw.get(beat)
        if not isinstance(raw_names, list):
            raise AuthorAssistParseError(
                f"author-cast schema validate error: missing beat_presence.{beat}",
                error_kind=ASSIST_ERROR_SCHEMA_VALIDATE,
                raw_snippet=sanitize_raw_snippet(beat_presence_raw),
            )
        out_names: list[str] = []
        seen_beat: set[str] = set()
        for raw_name in raw_names:
            name = _clean_text(raw_name)
            if not name:
                continue
            key = name.lower()
            if key in seen_beat:
                continue
            seen_beat.add(key)
            out_names.append(name)
        if not out_names:
            out_names = known_names[:2] if len(known_names) > 1 else known_names[:1]
        beat_presence[beat] = out_names[:6]

    return {
        "target_npc_count": target_npc_count,
        "npc_roster": npc_roster,
        "beat_presence": beat_presence,
    }
