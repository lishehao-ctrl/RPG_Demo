from __future__ import annotations

from copy import deepcopy

from .deterministic_tasks import (
    _CJK_SEGMENT_RE,
    _WORD_RE,
    _clean_text,
    _dedupe_text_items,
    _default_playability_policy,
    _is_generic_option_label,
    _writer_turn,
)
from .errors import AuthorAssistInvalidOutputError
from .types import ASSIST_ACTION_TYPES, ASSIST_MAX_SCENES, ASSIST_MIN_SCENES

_ASSIST_ACTION_TYPES = ASSIST_ACTION_TYPES
_ASSIST_MAX_SCENES = ASSIST_MAX_SCENES
_ASSIST_MIN_SCENES = ASSIST_MIN_SCENES
def _extract_seed_entities(seed_text: str, *, limit: int = 4) -> list[str]:
    text = _clean_text(seed_text)
    lowered = text.lower()
    out: list[str] = []

    def _push(candidate: str) -> None:
        item = _clean_text(candidate)
        if not item:
            return
        normalized = item.lower()
        if any(existing.lower() == normalized for existing in out):
            return
        out.append(item)

    zh_priority = (
        "室友",
        "奖学金",
        "导师",
        "项目",
        "论文",
        "抄袭",
        "证据",
        "毕业",
        "家人",
        "朋友",
    )
    en_priority = (
        "roommate",
        "scholarship",
        "advisor",
        "project",
        "plagiarism",
        "evidence",
        "deadline",
        "family",
        "friend",
    )
    for token in zh_priority:
        if token in text:
            _push(token)
    for token in en_priority:
        if token in lowered:
            _push(token)

    zh_stop = {"一个", "你是", "我们", "他们", "这个", "那个", "最后", "决定", "未来"}
    for seg in _CJK_SEGMENT_RE.findall(text):
        if seg in zh_stop:
            continue
        _push(seg)
        if len(out) >= limit:
            return out[:limit]

    en_stop = {
        "about",
        "after",
        "before",
        "there",
        "their",
        "would",
        "could",
        "should",
        "story",
        "write",
        "with",
        "from",
        "into",
        "that",
        "this",
        "have",
        "your",
        "week",
    }
    for token in _WORD_RE.findall(lowered):
        if len(token) < 4 or token in en_stop:
            continue
        _push(token)
        if len(out) >= limit:
            break

    return out[:limit]


def _seed_deadline_phrase(seed_text: str, *, locale: str) -> str:
    text = _clean_text(seed_text)
    lowered = text.lower()
    is_zh = locale.lower().startswith("zh")
    if "今晚" in text or "today" in lowered or "tonight" in lowered:
        return "今晚前" if is_zh else "before tonight"
    if "明天" in text or "tomorrow" in lowered:
        return "明天前" if is_zh else "before tomorrow"
    if "一周" in text or "七天" in text or "7天" in text or "week" in lowered:
        return "一周内" if is_zh else "within one week"
    return "短时间内" if is_zh else "within a short window"


def _contains_entity(text: object, entities: list[str]) -> bool:
    candidate = _clean_text(text).lower()
    if not candidate:
        return False
    for entity in entities:
        if _clean_text(entity).lower() in candidate:
            return True
    return False


def _seed_option(
    *,
    option_key: str,
    label: str,
    action_type: str,
    go_to: str | None,
    aliases: list[str],
    effects: dict | None = None,
    requirements: dict | None = None,
    is_key_decision: bool = False,
) -> dict:
    payload = {
        "option_key": option_key,
        "label": label,
        "intent_aliases": aliases,
        "action_type": action_type if action_type in _ASSIST_ACTION_TYPES else "rest",
        "go_to": go_to,
        "is_key_decision": bool(is_key_decision),
    }
    if isinstance(effects, dict) and effects:
        payload["effects"] = effects
    if isinstance(requirements, dict):
        payload["requirements"] = requirements
    return payload


def _build_seed_tension_loop_scenes(*, locale: str, seed_text: str) -> list[dict]:
    entities = _extract_seed_entities(seed_text)
    is_zh = locale.lower().startswith("zh")
    rival = entities[0] if entities else ("室友" if is_zh else "your counterpart")
    resource = entities[1] if len(entities) > 1 else ("奖学金" if is_zh else "scholarship")
    support = entities[2] if len(entities) > 2 else ("导师" if is_zh else "advisor")
    deadline = _seed_deadline_phrase(seed_text, locale=locale)
    hint_entities = [item for item in [rival, resource, support] if item]

    if is_zh:
        return [
            {
                "scene_key": "pressure_open",
                "title": f"开局压力：{deadline}",
                "setup": f"{rival}相关的异常让你的{resource}风险升高，你必须在{deadline}前做第一步。",
                "dramatic_question": f"你现在先保住{resource}，还是先处理与{rival}的信任裂痕？",
                "free_input_hints": ["对质", "证据", "奖学金", "恢复", rival, resource],
                "options": [
                    _seed_option(
                        option_key="open_confront",
                        label=f"立刻和{rival}对质，逼出真相",
                        action_type="date",
                        go_to="pressure_escalation",
                        aliases=["对质", "谈判", "摊牌", rival],
                        effects={"energy": -8, "affection": -4, "knowledge": 1},
                        is_key_decision=True,
                    ),
                    _seed_option(
                        option_key="open_secure_proof",
                        label=f"先整理{resource}与项目证据，再决定公开策略",
                        action_type="study",
                        go_to="pressure_escalation",
                        aliases=["证据", "整理", "项目", resource],
                        effects={"energy": -12, "knowledge": 3},
                        is_key_decision=True,
                    ),
                    _seed_option(
                        option_key="open_recover",
                        label=f"短暂恢复体力，避免在{rival}问题上失控",
                        action_type="rest",
                        go_to="pressure_escalation",
                        aliases=["恢复", "休息", "稳定", rival],
                        effects={"energy": 14},
                    ),
                ],
                "is_end": False,
                "intent_module": {
                    "author_input": seed_text,
                    "intent_tags": ["pressure_open", "deadline", "tradeoff"],
                    "parse_notes": "首节点明确冲突主体、稀缺资源和倒计时。",
                    "aliases": hint_entities,
                },
            },
            {
                "scene_key": "pressure_escalation",
                "title": "冲突升级",
                "setup": f"证据与关系开始反噬。你可以快速止损{resource}，但代价会在后续爆发。",
                "dramatic_question": "你要用高风险捷径换短期收益，还是保留转圜空间？",
                "free_input_hints": ["公开", "导师", "止损", "高风险", support],
                "options": [
                    _seed_option(
                        option_key="escalate_public_callout",
                        label=f"公开指控{rival}，立刻保护{resource}",
                        action_type="study",
                        go_to="recovery_window",
                        aliases=["公开", "指控", rival, resource],
                        effects={"energy": -15, "knowledge": 4, "affection": -8},
                        is_key_decision=True,
                    ),
                    _seed_option(
                        option_key="escalate_private_probe",
                        label=f"私下找{support}核验线索，延后摊牌",
                        action_type="study",
                        go_to="recovery_window",
                        aliases=["核验", "导师", support, "线索"],
                        effects={"energy": -10, "knowledge": 2, "money": -4},
                        is_key_decision=False,
                    ),
                    _seed_option(
                        option_key="escalate_shift",
                        label=f"先做一段短工缓冲{resource}风险",
                        action_type="work",
                        go_to="recovery_window",
                        aliases=["短工", "打工", "缓冲", resource],
                        effects={"energy": -10, "money": 18},
                        is_key_decision=False,
                    ),
                ],
                "is_end": False,
                "intent_module": {
                    "author_input": seed_text,
                    "intent_tags": ["pressure_escalation", "risk_tradeoff"],
                    "parse_notes": "第二节点提供短期收益高但长期风险高的选择。",
                    "aliases": hint_entities,
                },
            },
            {
                "scene_key": "recovery_window",
                "title": "恢复窗口",
                "setup": f"局势暂时放缓。你可以修复状态，也可以提前压上最后一次行动。",
                "dramatic_question": "现在回血会不会错过翻盘时机？",
                "free_input_hints": ["恢复", "复盘", "推进", "稳住"],
                "options": [
                    _seed_option(
                        option_key="recover_reset",
                        label=f"暂缓行动，修复与{rival}相关的压力损耗",
                        action_type="rest",
                        go_to="decision_gate",
                        aliases=["恢复", "休息", "修复", rival],
                        effects={"energy": 16, "affection": 1},
                        is_key_decision=False,
                    ),
                    _seed_option(
                        option_key="recover_plan",
                        label=f"和{support}快速对表，准备终局方案",
                        action_type="date",
                        go_to="decision_gate",
                        aliases=["对表", "计划", support],
                        effects={"energy": -5, "knowledge": 2, "affection": 2},
                        is_key_decision=False,
                    ),
                    _seed_option(
                        option_key="recover_push",
                        label=f"不休息，直接推进{resource}最终争夺",
                        action_type="study",
                        go_to="decision_gate",
                        aliases=["推进", "冲刺", resource],
                        effects={"energy": -14, "knowledge": 4},
                        is_key_decision=True,
                    ),
                ],
                "is_end": False,
                "intent_module": {
                    "author_input": seed_text,
                    "intent_tags": ["recovery_window", "tempo_shift"],
                    "parse_notes": "第三节点保证可恢复窗并保留进攻路线。",
                    "aliases": hint_entities,
                },
            },
            {
                "scene_key": "decision_gate",
                "title": "关键决断",
                "setup": f"最后节点要决定你如何处理{rival}与{resource}，并承受这一周的后果。",
                "dramatic_question": "你愿意为哪种未来付代价？",
                "free_input_hints": ["保全", "和解", "证据", "承担后果"],
                "options": [
                    _seed_option(
                        option_key="decide_self_preserve",
                        label=f"优先保住{resource}，接受与{rival}关系受损",
                        action_type="study",
                        go_to=None,
                        aliases=["保住", resource, "自保"],
                        effects={"knowledge": 3, "affection": -6},
                        is_key_decision=True,
                    ),
                    _seed_option(
                        option_key="decide_shared_future",
                        label=f"给{rival}一次修复机会，共同承担项目后果",
                        action_type="date",
                        go_to=None,
                        aliases=["修复", "和解", rival],
                        effects={"affection": 5, "knowledge": -1},
                        is_key_decision=True,
                    ),
                ],
                "is_end": True,
                "intent_module": {
                    "author_input": seed_text,
                    "intent_tags": ["decision_gate", "ending_pressure"],
                    "parse_notes": "终局节点聚焦不可逆代价与立场选择。",
                    "aliases": hint_entities,
                },
            },
        ]

    return [
        {
            "scene_key": "pressure_open",
            "title": f"Pressure Open ({deadline})",
            "setup": f"Signals around {rival} put your {resource} at risk. You need your first move {deadline}.",
            "dramatic_question": f"Do you secure {resource} first or address the fracture with {rival} now?",
            "free_input_hints": ["confront", "evidence", "recover", rival, resource],
            "options": [
                _seed_option(
                    option_key="open_confront",
                    label=f"Confront {rival} now and force clarity",
                    action_type="date",
                    go_to="pressure_escalation",
                    aliases=["confront", "talk", "clarify", rival],
                    effects={"energy": -8, "affection": -4, "knowledge": 1},
                    is_key_decision=True,
                ),
                _seed_option(
                    option_key="open_secure_proof",
                    label=f"Secure {resource} and project evidence before escalation",
                    action_type="study",
                    go_to="pressure_escalation",
                    aliases=["evidence", "project", resource, "secure"],
                    effects={"energy": -12, "knowledge": 3},
                    is_key_decision=True,
                ),
                _seed_option(
                    option_key="open_recover",
                    label=f"Take a recovery beat before the {rival} conflict explodes",
                    action_type="rest",
                    go_to="pressure_escalation",
                    aliases=["recover", "rest", "stabilize", rival],
                    effects={"energy": 14},
                ),
            ],
            "is_end": False,
            "intent_module": {
                "author_input": seed_text,
                "intent_tags": ["pressure_open", "deadline", "tradeoff"],
                "parse_notes": "Opening node makes conflict actors, scarce resource, and deadline explicit.",
                "aliases": hint_entities,
            },
        },
        {
            "scene_key": "pressure_escalation",
            "title": "Pressure Escalation",
            "setup": f"You can protect {resource} quickly, but your social and future costs spike.",
            "dramatic_question": "Do you take the high-risk shortcut or preserve optionality?",
            "free_input_hints": ["public", "advisor", "shortcut", "risk", support],
            "options": [
                _seed_option(
                    option_key="escalate_public_callout",
                    label=f"Call out {rival} in public to protect {resource} immediately",
                    action_type="study",
                    go_to="recovery_window",
                    aliases=["public", "callout", rival, resource],
                    effects={"energy": -15, "knowledge": 4, "affection": -8},
                    is_key_decision=True,
                ),
                _seed_option(
                    option_key="escalate_private_probe",
                    label=f"Quietly verify evidence with {support} before you strike",
                    action_type="study",
                    go_to="recovery_window",
                    aliases=["verify", "advisor", support, "evidence"],
                    effects={"energy": -10, "knowledge": 2, "money": -4},
                ),
                _seed_option(
                    option_key="escalate_shift",
                    label=f"Take a short shift to buffer {resource} risk",
                    action_type="work",
                    go_to="recovery_window",
                    aliases=["shift", "money", resource],
                    effects={"energy": -10, "money": 18},
                ),
            ],
            "is_end": False,
            "intent_module": {
                "author_input": seed_text,
                "intent_tags": ["pressure_escalation", "risk_tradeoff"],
                "parse_notes": "Escalation includes short-term gain with delayed costs.",
                "aliases": hint_entities,
            },
        },
        {
            "scene_key": "recovery_window",
            "title": "Recovery Window",
            "setup": "The pace briefly loosens. You can recover, stabilize, or overcommit for tempo.",
            "dramatic_question": "Will recovery cost you momentum, or save your final decision quality?",
            "free_input_hints": ["recover", "reset", "plan", "push"],
            "options": [
                _seed_option(
                    option_key="recover_reset",
                    label=f"Reset before the final choice around {rival}",
                    action_type="rest",
                    go_to="decision_gate",
                    aliases=["recover", "reset", rival],
                    effects={"energy": 16, "affection": 1},
                ),
                _seed_option(
                    option_key="recover_plan",
                    label=f"Align a final plan with {support}",
                    action_type="date",
                    go_to="decision_gate",
                    aliases=["align", "plan", support],
                    effects={"energy": -5, "knowledge": 2, "affection": 2},
                ),
                _seed_option(
                    option_key="recover_push",
                    label=f"Skip recovery and push for {resource} control now",
                    action_type="study",
                    go_to="decision_gate",
                    aliases=["push", resource, "commit"],
                    effects={"energy": -14, "knowledge": 4},
                    is_key_decision=True,
                ),
            ],
            "is_end": False,
            "intent_module": {
                "author_input": seed_text,
                "intent_tags": ["recovery_window", "tempo_shift"],
                "parse_notes": "Recovery window guarantees at least one stabilizing route.",
                "aliases": hint_entities,
            },
        },
        {
            "scene_key": "decision_gate",
            "title": "Decision Gate",
            "setup": f"Your last move resolves the conflict between {rival} and {resource}.",
            "dramatic_question": "Which future are you willing to pay for right now?",
            "free_input_hints": ["protect", "repair", "future", "cost"],
            "options": [
                _seed_option(
                    option_key="decide_self_preserve",
                    label=f"Protect {resource} and accept fallout with {rival}",
                    action_type="study",
                    go_to=None,
                    aliases=["protect", resource, "self-preserve"],
                    effects={"knowledge": 3, "affection": -6},
                    is_key_decision=True,
                ),
                _seed_option(
                    option_key="decide_shared_future",
                    label=f"Give {rival} one repair chance and share the cost",
                    action_type="date",
                    go_to=None,
                    aliases=["repair", "trust", rival],
                    effects={"affection": 5, "knowledge": -1},
                    is_key_decision=True,
                ),
            ],
            "is_end": True,
            "intent_module": {
                "author_input": seed_text,
                "intent_tags": ["decision_gate", "ending_pressure"],
                "parse_notes": "Final gate is stance-driven and irreversible.",
                "aliases": hint_entities,
            },
        },
    ]


def _coerce_scene_option(raw: object, *, fallback: dict, go_to: str | None) -> dict:
    if not isinstance(raw, dict):
        option = deepcopy(fallback)
    else:
        option = deepcopy(raw)
    option_key = _clean_text(option.get("option_key"), fallback=fallback.get("option_key") or "option")
    label = _clean_text(option.get("label"), fallback=fallback.get("label") or "Take action")
    if _is_generic_option_label(label):
        label = _clean_text(fallback.get("label"), fallback=label)
    action_type = _clean_text(option.get("action_type"), fallback=str(fallback.get("action_type") or "rest")).lower()
    if action_type not in _ASSIST_ACTION_TYPES:
        action_type = str(fallback.get("action_type") or "rest")
    aliases = option.get("intent_aliases")
    if not isinstance(aliases, list) or not aliases:
        aliases = list(fallback.get("intent_aliases") or [])
    aliases = _dedupe_text_items(list(aliases), limit=8)
    if not aliases:
        aliases = _dedupe_text_items([label, action_type], limit=4)
    effects = option.get("effects") if isinstance(option.get("effects"), dict) else fallback.get("effects")
    requirements = option.get("requirements") if isinstance(option.get("requirements"), dict) else {}
    return {
        "option_key": option_key,
        "label": label,
        "intent_aliases": aliases,
        "action_type": action_type,
        "go_to": go_to,
        "effects": effects if isinstance(effects, dict) else {},
        "requirements": requirements if isinstance(requirements, dict) else {},
        "is_key_decision": bool(option.get("is_key_decision", fallback.get("is_key_decision", False))),
    }


def _ensure_scene_option_quality(*, scene_key: str, options: list[dict], warnings: list[str]) -> list[dict]:
    out = [deepcopy(item) for item in options if isinstance(item, dict)]
    if not out:
        return out
    def _to_int(value: object, default: int) -> int:
        try:
            return int(value)
        except Exception:  # noqa: BLE001
            return default
    seen_labels: set[str] = set()
    seen_signatures: set[tuple[str, str]] = set()
    contrast_boosted = False
    for idx, option in enumerate(out):
        label = _clean_text(option.get("label"), fallback=f"Option {idx + 1}")
        key = label.lower()
        if key in seen_labels:
            label = f"{label} ({_clean_text(option.get('action_type'), fallback='alt')})"
            key = label.lower()
        seen_labels.add(key)
        option["label"] = label
        option["intent_aliases"] = _dedupe_text_items(
            list(option.get("intent_aliases") or []),
            limit=8,
        )
        signature = (
            _clean_text(option.get("action_type"), fallback="rest").lower(),
            _clean_text(option.get("go_to"), fallback=""),
        )
        if signature in seen_signatures and not contrast_boosted:
            option["action_type"] = "rest" if signature[0] != "rest" else "study"
            effects = option.get("effects") if isinstance(option.get("effects"), dict) else {}
            effects = dict(effects)
            if option["action_type"] == "rest":
                effects["energy"] = max(10, _to_int(effects.get("energy", 0) or 0, 0))
                option["label"] = f"{label} (Recover)"
            else:
                effects["knowledge"] = max(2, _to_int(effects.get("knowledge", 0) or 0, 0))
                effects["energy"] = min(-6, _to_int(effects.get("energy", -8) or -8, -8))
                option["label"] = f"{label} (Push)"
            option["effects"] = effects
            contrast_boosted = True
            warnings.append(f"Adjusted scene '{scene_key}' to increase branch contrast between options.")
            signature = (
                _clean_text(option.get("action_type"), fallback="rest").lower(),
                _clean_text(option.get("go_to"), fallback=""),
            )
        seen_signatures.add(signature)
    return out


def _normalize_seed_expand_suggestions(*, locale: str, context: dict, suggestions: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    normalized = deepcopy(suggestions if isinstance(suggestions, dict) else {})
    seed_text = _clean_text(
        context.get("seed_text") or context.get("global_brief") or context.get("brief"),
        fallback="",
    )
    entities = _extract_seed_entities(seed_text)
    defaults = _build_seed_tension_loop_scenes(locale=locale, seed_text=seed_text)
    flow = normalized.get("flow") if isinstance(normalized.get("flow"), dict) else {}
    raw_scenes = flow.get("scenes") if isinstance(flow.get("scenes"), list) else []

    if not raw_scenes:
        warnings.append("seed_expand returned no scenes; generated a 4-node tension loop scaffold.")
        raw_scenes = deepcopy(defaults)

    if len(raw_scenes) < _ASSIST_MIN_SCENES:
        warnings.append("seed_expand scene count was too small; appended missing tension-loop scenes.")
    if len(raw_scenes) > _ASSIST_MAX_SCENES:
        warnings.append("seed_expand scene count exceeded 4; trimmed to the first four scenes.")

    scenes: list[dict] = []
    for idx in range(_ASSIST_MAX_SCENES):
        fallback_scene = deepcopy(defaults[idx])
        raw_scene = raw_scenes[idx] if idx < len(raw_scenes) and isinstance(raw_scenes[idx], dict) else {}
        merged = deepcopy(fallback_scene)
        for field in ("title", "setup", "dramatic_question", "free_input_hints", "intent_module"):
            if field in raw_scene and raw_scene[field]:
                merged[field] = deepcopy(raw_scene[field])

        merged["scene_key"] = fallback_scene["scene_key"]
        merged["is_end"] = idx == _ASSIST_MAX_SCENES - 1
        go_to = defaults[idx + 1]["scene_key"] if idx < _ASSIST_MAX_SCENES - 1 else None
        raw_options = raw_scene.get("options") if isinstance(raw_scene.get("options"), list) else []
        fallback_options = fallback_scene.get("options") if isinstance(fallback_scene.get("options"), list) else []

        options: list[dict] = []
        for option_idx, fallback_option in enumerate(fallback_options):
            candidate = raw_options[option_idx] if option_idx < len(raw_options) else fallback_option
            option = _coerce_scene_option(candidate, fallback=fallback_option, go_to=go_to)
            options.append(option)

        if len(raw_options) > len(fallback_options):
            for extra in raw_options[len(fallback_options) :]:
                if len(options) >= 4:
                    break
                fallback_option = fallback_options[-1]
                option = _coerce_scene_option(extra, fallback=fallback_option, go_to=go_to)
                options.append(option)

        if not merged["is_end"]:
            options = options[:4]
            while len(options) < 2:
                filler = _coerce_scene_option(
                    {},
                    fallback=fallback_options[min(len(options), len(fallback_options) - 1)],
                    go_to=go_to,
                )
                options.append(filler)
            if not any(opt.get("action_type") == "rest" or int((opt.get("effects") or {}).get("energy", 0)) > 0 for opt in options):
                recovery = _coerce_scene_option(
                    {
                        "option_key": f"{merged['scene_key']}_recover",
                        "label": fallback_options[-1]["label"],
                        "action_type": "rest",
                        "intent_aliases": ["recover", "rest", "reset"],
                        "effects": {"energy": 12},
                    },
                    fallback=fallback_options[-1],
                    go_to=go_to,
                )
                if len(options) >= 4:
                    options[-1] = recovery
                else:
                    options.append(recovery)
                warnings.append(f"Added recovery option in scene '{merged['scene_key']}' to keep tension loop playable.")
        else:
            options = options[:4]
            for option in options:
                option["go_to"] = None
        if not options:
            raise AuthorAssistInvalidOutputError(
                hint="Model response missed required scene options.",
                detail=f"scene '{merged['scene_key']}' has no options",
            )

        if entities and not any(_contains_entity(item.get("label"), entities) for item in options):
            options[0]["label"] = f"{options[0]['label']} ({entities[0]})"
            warnings.append(f"Injected seed entity into scene '{merged['scene_key']}' option labels for specificity.")

        merged["options"] = _ensure_scene_option_quality(
            scene_key=merged["scene_key"],
            options=options,
            warnings=warnings,
        )
        scenes.append(merged)

    flow = deepcopy(flow)
    flow["start_scene_key"] = scenes[0]["scene_key"]
    flow["scenes"] = scenes
    normalized["flow"] = flow
    normalized["format_version"] = 4
    normalized["entry_mode"] = "spark"
    normalized["source_text"] = None

    plot = normalized.get("plot") if isinstance(normalized.get("plot"), dict) else {}
    acts = plot.get("mainline_acts") if isinstance(plot.get("mainline_acts"), list) else []
    if len(acts) < 2:
        acts = [
            {
                "act_key": "act_pressure",
                "title": "Act I - Pressure",
                "objective": "Open and escalate the conflict.",
                "scene_keys": ["pressure_open", "pressure_escalation"],
            },
            {
                "act_key": "act_resolution",
                "title": "Act II - Recovery and Decision",
                "objective": "Recover, then commit to an irreversible stance.",
                "scene_keys": ["recovery_window", "decision_gate"],
            },
        ]
        warnings.append("Rebuilt plot acts to align with the 4-node tension loop.")
    else:
        normalized_keys = [scene["scene_key"] for scene in scenes]
        for idx, act in enumerate(acts):
            if not isinstance(act, dict):
                continue
            if idx == 0:
                act["scene_keys"] = normalized_keys[:2]
            else:
                act["scene_keys"] = normalized_keys[2:]
    plot["mainline_acts"] = acts
    normalized["plot"] = plot

    journal = normalized.get("writer_journal") if isinstance(normalized.get("writer_journal"), list) else []
    if not journal:
        journal = [
            _writer_turn(
                phase="expand",
                author_text=seed_text or "Spark seed.",
                assistant_text="Built a 4-node tension loop: pressure open, escalation, recovery window, and decision gate.",
            )
        ]
        warnings.append("writer_journal was missing; seeded one explainable author turn.")
    normalized["writer_journal"] = journal
    if "playability_policy" not in normalized:
        normalized["playability_policy"] = _default_playability_policy()
    return normalized, warnings


