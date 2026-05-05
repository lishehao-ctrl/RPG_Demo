from __future__ import annotations

import copy
from dataclasses import replace
import inspect
import re
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError
from typing_extensions import TypedDict

from rpg_backend.author.contracts import StoryShellId
from rpg_backend.author.gateway import AuthorGatewayError
from rpg_backend.author.normalize import normalize_whitespace, slugify, trim_text
from rpg_backend.author_v2.contracts import (
    AcceptedBlueprint,
    BlueprintEdits,
    ExperienceBandId,
    PlayLengthPresetId,
    PreviewSynthesisDelta,
    SeedSignals,
    UrbanPreviewBlueprint,
    WorldlyDesireType,
)
from rpg_backend.author_v2.gateway import (
    AuthorV2LLMGateway,
    AuthorV2RunMode,
    get_author_v2_llm_gateway,
    resolve_author_v2_live_mode_chain,
)
from rpg_backend.author_v2.stage_utils import (
    MAX_STAGE_REGEN_ATTEMPTS,
    append_quality_trace,
    extend_llm_trace as extend_stage_llm_trace,
    fallback_reason,
    is_provider_failure,
    retry_exhausted_outcome,
)
from rpg_backend.author_v2.template_library import (
    build_seed_fingerprint,
    is_hero_template,
    match_story_template_with_trace,
    render_template_text,
)
from rpg_backend.config import get_settings

_MAINLINE_LIVE_MODES = {"live_priority", "mainline_live"}

PREVIEW_SYNTHESIS_SYSTEM_PROMPT = """
你在编译一个都市关系戏 preview blueprint。
目标不是完整世界观，而是可传播、可站队、可失控。
请只返回 JSON 对象，只能包含以下 delta 字段：
- 必填：hook、bomb_moment、cost_of_truth
- 选填：protagonist_public_identity、protagonist_hidden_need、social_arena、relationship_setup、taboo_secret、share_hook

规则：
- 强化 hook / route_promise / bomb_moment / cost_of_truth 的传播性与世俗感。
- hook 必须明确：主角是谁、今晚是什么局、至少两股拉扯她的关系力量、最危险的秘密是什么。
- route_promise 是锁定字段，不要输出 route_promise，也不要改写站队动词结构。
- bomb_moment 必须是公开场合里的失控瞬间，而且要有体面被撕开、秘密被甩到台前的感觉。
- cost_of_truth 必须是可感知的现实代价：体面、位置、名声、前途、退路、关系、婚约、资源里至少命中一类。
- 不要引入 civic / harbor / council / archive 语义。
- 不要输出 markdown，不要解释。
""".strip()

SHELL_KEYWORDS: dict[StoryShellId, tuple[str, ...]] = {
    "wealth_families": ("豪门", "联姻", "继承", "家宴", "私生", "遗嘱"),
    "entertainment_scandal": ("顶流", "热搜", "绯闻", "经纪", "娱乐圈", "直播"),
    "office_power": ("总裁", "上司", "董事会", "并购", "职场", "办公室"),
    "campus_romance": ("校园", "奖学金", "学生会", "导师", "校庆", "社团"),
    "urban_supernatural": ("灵媒", "夜巡", "异能", "怪谈", "契约", "都市奇谈"),
}

SOCIAL_ARENA_HINTS: tuple[tuple[str, str], ...] = (
    ("婚礼", "婚礼主场"),
    ("订婚", "订婚宴"),
    ("家宴", "家宴主桌"),
    ("董事会", "董事会现场"),
    ("发布会", "发布会主舞台"),
    ("直播", "直播镜头前"),
    ("酒会", "名流酒会"),
    ("答辩", "答辩会场"),
    ("校庆", "校庆晚会"),
    ("夜店", "夜店包厢"),
)

PUBLIC_BOMB_WORDS = ("当众", "公开", "直播", "婚礼", "家宴", "董事会", "发布会", "热搜", "镜头")

DESIRE_HINTS: tuple[tuple[WorldlyDesireType, tuple[str, ...]], ...] = (
    ("love", ("爱", "前任", "白月光", "婚", "暧昧", "告白")),
    ("status", ("继承", "上位", "体面", "名分", "权力", "地位")),
    ("money", ("钱", "资源", "债", "股份", "投资", "代言")),
    ("revenge", ("复仇", "报复", "旧账", "羞辱", "翻旧账")),
    ("freedom", ("逃离", "自由", "离开", "摆脱", "跑路")),
    ("control", ("控制", "掌控", "安排", "拿捏", "封口")),
    ("identity", ("身份", "替身", "私生", "认错", "真假", "身世")),
)

SHELL_DEFAULTS: dict[StoryShellId, dict[str, str]] = {
    "wealth_families": {
        "identity": "被卷进豪门联姻局的关键当事人",
        "need": "她真正想要的不是名分，而是有人肯在众目睽睽下站到她这一边。",
        "relationship": "主角被夹在掌权继承人、旧情回潮者和握着遗嘱秘密的人之间。",
        "secret": "足以改写继承顺位的旧案证据",
        "share_hook": "豪门联姻、旧爱回归、继承真相一起炸开。",
        "arena": "家宴主桌",
        "material_cost": "名分、婚约和家族体面",
    },
    "entertainment_scandal": {
        "identity": "被热搜裹挟的新人女主或经纪核心人物",
        "need": "她真正想要的不是红，而是不用再把真心当公关素材。",
        "relationship": "主角周旋在顶流、经纪人与掌握黑料的盟友之间。",
        "secret": "会让事业和亲密关系一起翻车的偷拍视频",
        "share_hook": "热搜、隐恋、背刺经纪，一句话就能把场面炸穿。",
        "arena": "直播镜头前",
        "material_cost": "名声、代言和事业退路",
    },
    "office_power": {
        "identity": "在权力边缘求生的项目负责人",
        "need": "她真正想要的是被当成同盟，而不是永远被当成可替代的棋子。",
        "relationship": "主角被强势上司、危险合作方和最懂她弱点的人同时拉扯。",
        "secret": "足以让董事会翻盘的并购黑账",
        "share_hook": "上位、站队、办公室暧昧和黑账一起爆。",
        "arena": "董事会现场",
        "material_cost": "位置、前途和最后那点体面",
    },
    "campus_romance": {
        "identity": "表面体面、内里背着竞逐压力的校园核心人物",
        "need": "她真正想要的是被看见真实欲望，而不是继续扮演那个完美样本。",
        "relationship": "主角夹在白切黑竞争者、旧日暧昧对象和掌握录音的人之间。",
        "secret": "会毁掉前途与名声的录音",
        "share_hook": "奖学金、旧爱、站队和校园名声同时失控。",
        "arena": "校庆晚会",
        "material_cost": "名声、前途和奖学金机会",
    },
    "urban_supernatural": {
        "identity": "白天维持正常体面、夜里被异能旧账追上的都市人",
        "need": "她真正想要的是摆脱被命运安排的关系债，自己决定要爱谁。",
        "relationship": "主角在危险知情者、夜色盟友与旧债缠身者之间越陷越深。",
        "secret": "一份会把前世债与当下情欲一起拖进现实的契约",
        "share_hook": "都市夜色、异能契约、情感站队一起上头。",
        "arena": "夜色会所外场",
        "material_cost": "命、自由和好不容易保住的正常生活",
    },
}

ROUTE_PROMISE_TEMPLATES: dict[StoryShellId, str] = {
    "wealth_families": "你要在{arena}失控前，选谁一起扛下继承风暴、护谁留住名分，再决定先拆掉谁的体面。",
    "entertainment_scandal": "你要在{arena}翻车前，选谁陪你扛热搜、护谁留在镜头里，再决定先把谁的伪装撕开。",
    "office_power": "你要在{arena}失控前，选谁一起扛雷、护谁留在牌桌上，再决定先逼谁当众表态。",
    "campus_romance": "你要在{arena}翻车前，选谁站到你这边、护谁不被舆论吃掉，再决定先逼谁承认旧账。",
    "urban_supernatural": "你要在{arena}失控前，选谁陪你扛下旧债、护谁别被夜色吞掉，再决定先逼谁说破契约。",
}

BOMB_MOMENT_TEMPLATES: dict[StoryShellId, str] = {
    "wealth_families": "在{arena}最安静的那一秒，有人把{secret}甩到台前，最体面的那个人被逼得当众失控。",
    "entertainment_scandal": "在{arena}灯最亮的时候，{secret}被突然推上台面，最会控场的人也只能当众翻车。",
    "office_power": "在{arena}最讲规矩的那一刻，{secret}被直接摔到桌上，最稳的人也被逼得当众失态。",
    "campus_romance": "在{arena}所有人都盯着的时候，{secret}被突然说破，最会装体面的人先当众崩掉。",
    "urban_supernatural": "在{arena}人群最密的时候，{secret}被硬生生拖进现实，最能装镇定的人也当众失控。",
}

COST_OF_TRUTH_TEMPLATES: dict[StoryShellId, str] = {
    "wealth_families": "真相一旦说破，主角会一起失去{material_cost}，再也回不到那张桌子的安全位置。",
    "entertainment_scandal": "真相一旦说破，主角会一起赔上{material_cost}，连最想保住的关系也会被拖进热搜。",
    "office_power": "真相一旦说破，主角会一起赔上{material_cost}，以后没人再把她当成还能回头的人。",
    "campus_romance": "真相一旦说破，主角会一起赔上{material_cost}，从此连最熟悉的人都得重新看她。",
    "urban_supernatural": "真相一旦说破，主角会一起赔上{material_cost}，连她最想保住的人间退路都会被烧穿。",
}


class PreviewState(TypedDict, total=False):
    prompt_seed: str
    preview_id: str
    seed_signals: SeedSignals
    seed_fingerprint: Any
    matched_template: Any
    template_decision_trace: dict[str, Any]
    preview_blueprint: UrbanPreviewBlueprint
    llm_call_trace: list[dict[str, Any]]
    quality_trace: list[dict[str, Any]]
    live_mode: AuthorV2RunMode
    live_gateway: AuthorV2LLMGateway | None
    target_gender_pref: Literal["male", "female"] | None


def _append_quality(
    state: PreviewState,
    *,
    stage: str,
    outcome: str,
    reasons: list[str] | None = None,
    source: str = "deterministic",
    metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return append_quality_trace(
        list(state.get("quality_trace", [])),
        stage=stage,
        outcome=outcome,
        reasons=reasons,
        source=source,
        metrics=metrics,
        strict_enabled=_strict_no_repair_fallback_enabled(),
    )


def _strict_no_repair_fallback_enabled() -> bool:
    return bool(get_settings().internal_test_strict_no_repair_fallback)


def _extend_llm_trace(
    state: PreviewState,
    gateway: AuthorV2LLMGateway,
    *,
    start_index: int,
    stage: str,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    return extend_stage_llm_trace(
        list(state.get("llm_call_trace", [])),
        gateway=gateway,
        start_index=start_index,
        stage=stage,
        duration_seconds=duration_seconds,
        retry_count=0,
    )


class _PreviewDeltaValidationError(RuntimeError):
    def __init__(self, *, code: str) -> None:
        super().__init__(code)
        self.code = code


_PREVIEW_DELTA_FIELDS: tuple[str, ...] = (
    "hook",
    "bomb_moment",
    "cost_of_truth",
    "protagonist_public_identity",
    "protagonist_hidden_need",
    "social_arena",
    "relationship_setup",
    "taboo_secret",
    "share_hook",
)
_PREVIEW_DELTA_REQUIRED_FIELDS: tuple[str, ...] = (
    "hook",
    "bomb_moment",
    "cost_of_truth",
)
_PREVIEW_LOCKED_FIELDS = {
    "preview_id",
    "prompt_seed",
    "story_shell_id",
    "worldly_desire_type",
    "fit_mode",
    "template_id",
    "seed_fingerprint",
    "target_gender_pref",
}


def _build_preview_synthesis_json_schema() -> dict[str, Any]:
    schema = copy.deepcopy(PreviewSynthesisDelta.model_json_schema())
    properties = schema.get("properties")
    if isinstance(properties, dict):
        # xcode chat-completions strict json_schema requires required[] to include all keys.
        schema["required"] = list(properties.keys())
        schema.setdefault("additionalProperties", False)
    return schema


_PREVIEW_SYNTHESIS_JSON_SCHEMA: dict[str, Any] = _build_preview_synthesis_json_schema()


def _compact_reason_keys(keys: list[str]) -> str:
    if not keys:
        return "none"
    return "+".join(sorted({str(item) for item in keys if str(item).strip()}))


def _coerce_preview_delta_payload(payload: dict[str, Any]) -> dict[str, Any]:
    nested_delta = payload.get("preview_blueprint_delta")
    if isinstance(nested_delta, dict):
        source_payload = nested_delta
    else:
        nested_blueprint = payload.get("preview_blueprint")
        if isinstance(nested_blueprint, dict):
            source_payload = nested_blueprint
        else:
            source_payload = payload
    return {
        key: source_payload[key]
        for key in _PREVIEW_DELTA_FIELDS
        if key in source_payload
    }


def _invoke_preview_synthesis(
    *,
    gateway: AuthorV2LLMGateway | Any,
    request_payload: dict[str, Any],
) -> Any:
    invoke = gateway.invoke_json
    supports_schema = False
    try:
        supports_schema = "response_format_schema" in inspect.signature(invoke).parameters
    except (TypeError, ValueError):
        supports_schema = False
    if supports_schema:
        return invoke(
            system_prompt=PREVIEW_SYNTHESIS_SYSTEM_PROMPT,
            user_payload=request_payload,
            max_output_tokens=gateway.max_output_tokens_preview,
            operation_name="author_v2.preview_synthesis",
            response_format_type="json_schema",
            response_format_schema=_PREVIEW_SYNTHESIS_JSON_SCHEMA,
            response_format_name="preview_synthesis_delta",
            response_format_strict=True,
        )
    return invoke(
        system_prompt=PREVIEW_SYNTHESIS_SYSTEM_PROMPT,
        user_payload=request_payload,
        max_output_tokens=gateway.max_output_tokens_preview,
        operation_name="author_v2.preview_synthesis",
        response_format_type="json_object",
    )


def _experience_band_for_preset(play_length_preset: PlayLengthPresetId) -> ExperienceBandId:
    if play_length_preset == "5_8":
        return "5_8"
    if play_length_preset in {"10_12", "12_15"}:
        return "8_15"
    return "15_25"


def _normalize_cast_count_for_preset(cast_count_target: int, play_length_preset: PlayLengthPresetId) -> int:
    cast_count_target = max(3, min(7, cast_count_target))
    if play_length_preset == "5_8":
        return min(cast_count_target, 4)
    if play_length_preset in {"10_12", "12_15"}:
        return min(max(cast_count_target, 4), 5)
    if play_length_preset == "15_20":
        return min(max(cast_count_target, 5), 6)
    if play_length_preset == "20_25":
        return max(cast_count_target, 6)
    return max(cast_count_target, 6)


def _to_json_comparable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            return value
    if isinstance(value, dict):
        return {key: _to_json_comparable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json_comparable(item) for item in value]
    return value


def _validate_preview_business_rules(
    candidate: UrbanPreviewBlueprint,
    *,
    deterministic_blueprint: UrbanPreviewBlueprint,
) -> None:
    expected_cast_count = _normalize_cast_count_for_preset(candidate.cast_count_target, candidate.play_length_preset)
    if candidate.cast_count_target != expected_cast_count:
        raise ValueError("cast_count_target_mismatch")

    expected_route_targets = _normalize_route_target_count(candidate.cast_count_target)
    if candidate.route_target_count != expected_route_targets:
        raise ValueError("route_target_count_mismatch")

    expected_experience_band = _experience_band_for_preset(candidate.play_length_preset)
    if candidate.experience_band != expected_experience_band:
        raise ValueError("experience_band_mismatch")

    if not any(word in candidate.bomb_moment for word in PUBLIC_BOMB_WORDS):
        raise ValueError("bomb_moment_needs_public_stage")

    deterministic_payload = deterministic_blueprint.model_dump(mode="json")
    candidate_payload = candidate.model_dump(mode="json")
    for field_name in _PREVIEW_LOCKED_FIELDS:
        if _to_json_comparable(candidate_payload.get(field_name)) != _to_json_comparable(deterministic_payload.get(field_name)):
            raise ValueError(f"{field_name}_locked")


def _validate_live_preview_blueprint(
    deterministic_blueprint: UrbanPreviewBlueprint,
    live_payload: dict[str, Any],
) -> UrbanPreviewBlueprint:
    try:
        delta = PreviewSynthesisDelta.model_validate(live_payload)
    except ValidationError as exc:
        errors = list(exc.errors() or [])
        first = errors[0] if errors else {}
        loc_tokens = [str(token) for token in list(first.get("loc") or []) if str(token)]
        loc = ".".join(loc_tokens) if loc_tokens else "root"
        err_type = str(first.get("type") or "invalid")
        returned_keys = [str(key) for key in live_payload.keys()]
        missing_required_keys = [field for field in _PREVIEW_DELTA_REQUIRED_FIELDS if field not in live_payload]
        code = (
            "schema_invalid:delta:"
            f"{loc}:{err_type}:"
            f"returned_keys={_compact_reason_keys(returned_keys)}:"
            f"missing_required_keys={_compact_reason_keys(missing_required_keys)}"
        )
        raise _PreviewDeltaValidationError(code=code) from exc
    merged_payload = deterministic_blueprint.model_dump(mode="json")
    merged_payload.update(delta.model_dump(mode="json", exclude_none=True))
    parsed = UrbanPreviewBlueprint.model_validate(merged_payload)
    _validate_preview_business_rules(parsed, deterministic_blueprint=deterministic_blueprint)
    return parsed


def _infer_shell(seed: str) -> StoryShellId:
    lowered = seed.casefold()
    scores: dict[StoryShellId, int] = {}
    for shell_id, keywords in SHELL_KEYWORDS.items():
        scores[shell_id] = sum(1 for keyword in keywords if keyword.casefold() in lowered)
    best_shell = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
    if scores[best_shell] > 0:
        return best_shell
    return "wealth_families"


def _infer_desire(seed: str, shell_id: StoryShellId) -> WorldlyDesireType:
    lowered = seed.casefold()
    for desire, keywords in DESIRE_HINTS:
        if any(keyword.casefold() in lowered for keyword in keywords):
            return desire
    return {
        "wealth_families": "status",
        "entertainment_scandal": "love",
        "office_power": "control",
        "campus_romance": "identity",
        "urban_supernatural": "freedom",
    }[shell_id]


def _infer_social_arena(seed: str, shell_id: StoryShellId) -> str:
    for needle, arena in SOCIAL_ARENA_HINTS:
        if needle in seed:
            return arena
    return SHELL_DEFAULTS[shell_id]["arena"]


def _infer_cast_count(seed: str, shell_id: StoryShellId) -> int:
    lowered = seed.casefold()
    if any(token in lowered for token in ("7人", "群像", "复杂", "旗舰", "长篇", "二十分钟", "25分钟")):
        return 6 if shell_id != "campus_romance" else 5
    if any(token in lowered for token in ("短", "快", "teaser", "5分钟", "8分钟")):
        return 4 if shell_id != "wealth_families" else 3
    return {
        "wealth_families": 6,
        "entertainment_scandal": 5,
        "office_power": 5,
        "campus_romance": 4,
        "urban_supernatural": 5,
    }[shell_id]


def _infer_public_identity(seed: str, shell_id: StoryShellId) -> str:
    defaults = SHELL_DEFAULTS[shell_id]["identity"]
    if "女律师" in seed:
        return "被豪门和旧情一起拖进局里的女律师"
    if "经纪人" in seed:
        return "被镜头和合同一起挟持的经纪核心人物"
    if "秘书" in seed:
        return "最懂上位者秘密、也最容易被牺牲的秘书"
    return defaults


def _infer_hidden_need(seed: str, shell_id: StoryShellId, desire: WorldlyDesireType) -> str:
    if "想翻身" in seed or desire == "status":
        return "她真正想要的不是被安排的体面，而是亲手赢下站队权。"
    if desire == "love":
        return "她真正想要的不是暧昧，而是有人敢在最难看的场面里站她。"
    if desire == "revenge":
        return "她真正想要的不只是报复，而是让当年伤她的人在同样的场合失控。"
    if desire == "money":
        return "她真正想要的不是账面资源，而是不用再用感情换筹码。"
    return SHELL_DEFAULTS[shell_id]["need"]


def _infer_share_hook(seed: str, shell_id: StoryShellId) -> str:
    if "谁先失控" in seed:
        return "最体面的那个人先失控，最危险的秘密被当众说破。"
    return SHELL_DEFAULTS[shell_id]["share_hook"]


def _infer_play_length_preset(seed: str) -> PlayLengthPresetId:
    lowered = seed.casefold()
    range_match = re.search(r"(\d+)\s*(?:到|-|至)\s*(\d+)\s*分钟", lowered)
    if range_match:
        high = int(range_match.group(2))
        if high <= 8:
            return "5_8"
        if high <= 12:
            return "10_12"
        if high <= 15:
            return "12_15"
        if high <= 20:
            return "15_20"
        if high <= 25:
            return "20_25"
        return "30_45"
    minute_match = re.search(r"(?<!\d)(\d+)\s*分钟", lowered)
    if minute_match:
        minute_value = int(minute_match.group(1))
        if minute_value <= 8:
            return "5_8"
        if minute_value <= 12:
            return "10_12"
        if minute_value <= 15:
            return "12_15"
        if minute_value <= 20:
            return "15_20"
        if minute_value <= 25:
            return "20_25"
        return "30_45"
    if any(token in lowered for token in ("30分钟", "35分钟", "40分钟", "45分钟", "超级旗舰", "超级长局", "长篇群像", "8 beat", "8beat")):
        return "30_45"
    if any(token in lowered for token in ("20分钟", "25分钟", "旗舰", "复杂", "长篇", "群像")):
        return "20_25"
    if any(token in lowered for token in ("15分钟", "18分钟", "中长", "长局")):
        return "15_20"
    if any(token in lowered for token in ("短", "快", "teaser", "短局")):
        return "5_8"
    return "12_15"


def _normalize_route_target_count(cast_count: int) -> int:
    if cast_count <= 4:
        return 2
    if cast_count <= 6:
        return 3
    return 4


def extract_seed_signals(state: PreviewState) -> PreviewState:
    seed = normalize_whitespace(state["prompt_seed"])
    play_length_preset = _infer_play_length_preset(seed)
    fingerprint = build_seed_fingerprint(seed, play_length_preset)
    if fingerprint.fit_mode == "out_of_scope":
        # Raised through the gateway-error path so the FastAPI exception handler
        # turns this into a 422 (not the bare 500 you get from a raw ValueError
        # bubbling up through LangGraph). Frontend reads `code` to localize.
        raise AuthorGatewayError(
            code="seed_out_of_scope",
            message=(
                "这句开头不在当前支持的题材范围内。"
                "试试更贴近现代都市职场、情感关系、悬疑博弈的设定 — "
                "比如：'公司年会前夜，我作为新晋总监被三个高管同时盯上' / "
                "'闺蜜结婚前一周突然把我前任拉进伴娘群'"
            ),
            status_code=422,
        )
    matched_template, decision_trace = match_story_template_with_trace(fingerprint)
    shell_id = fingerprint.public_shell_id
    desire = _infer_desire(seed, shell_id)
    signals = SeedSignals(
        raw_seed=seed,
        protagonist_public_identity=_infer_public_identity(seed, shell_id),
        protagonist_hidden_need=_infer_hidden_need(seed, shell_id, desire),
        social_arena=_infer_social_arena(seed, shell_id),
        relationship_setup=trim_text(matched_template.relationship_setup_template, 220),
        taboo_secret_type=trim_text(SHELL_DEFAULTS[shell_id]["secret"], 120),
        worldly_desire_type=desire,
        share_hook=trim_text(matched_template.share_hook_template, 180),
        story_shell_id=shell_id,
        desired_cast_count=_infer_cast_count(seed, shell_id),
    )
    return {
        "seed_signals": signals,
        "seed_fingerprint": fingerprint,
        "matched_template": matched_template,
        "template_decision_trace": decision_trace,
        "llm_call_trace": list(state.get("llm_call_trace", [])),
        "quality_trace": _append_quality(
            state,
            stage="extract_seed_signals",
            outcome="accepted",
            source="deterministic",
            metrics={
                "decision_source": str(decision_trace.get("decision_source") or "template_router_deterministic"),
                "decision_rule_hits": list(decision_trace.get("decision_rule_hits") or [])[:16],
                "decision_axis_hits": list(decision_trace.get("decision_axis_hits") or [])[:16],
                "decision_hint_hits": list(decision_trace.get("decision_hint_hits") or [])[:16],
            },
        ),
    }


def _build_deterministic_preview_blueprint(state: PreviewState) -> UrbanPreviewBlueprint:
    signals = state["seed_signals"]
    fingerprint = state["seed_fingerprint"]
    matched_template = state["matched_template"]
    cast_count_target = max(3, min(7, signals.desired_cast_count))
    play_length_preset = fingerprint.play_length_preset
    experience_band = _experience_band_for_preset(play_length_preset)
    cast_count_target = _normalize_cast_count_for_preset(cast_count_target, play_length_preset)
    route_target_count = _normalize_route_target_count(cast_count_target)
    template_text = render_template_text(matched_template, fingerprint)
    taboo_secret = trim_text(
        f"一份会在{template_text['arena']}上同时毁掉体面和关系的{template_text['secret']}",
        180,
    )
    hook = trim_text(
        f"{template_text['arena']}前夜，作为{signals.protagonist_public_identity}的主角发现："
        f"{template_text['relationship_setup']}；而一旦{template_text['secret']}见光，{template_text['cost']}会一起炸开。",
        220,
    )
    return UrbanPreviewBlueprint(
        preview_id=state.get("preview_id") or f"preview_{uuid4().hex[:12]}",
        prompt_seed=signals.raw_seed,
        fit_mode=fingerprint.fit_mode,
        template_id=matched_template.template_id,
        seed_fingerprint=fingerprint,
        protagonist_public_identity=signals.protagonist_public_identity,
        protagonist_hidden_need=signals.protagonist_hidden_need,
        social_arena=template_text["arena"],
        relationship_setup=template_text["relationship_setup"],
        taboo_secret=taboo_secret,
        worldly_desire_type=signals.worldly_desire_type,
        share_hook=template_text["share_hook"],
        hook=hook,
        route_promise=template_text["route_promise"],
        bomb_moment=template_text["bomb_moment"],
        cost_of_truth=template_text["cost_of_truth"],
        play_length_preset=play_length_preset,
        cast_count_target=cast_count_target,
        experience_band=experience_band,
        story_shell_id=signals.story_shell_id,
        route_target_count=route_target_count,
        target_gender_pref=state.get("target_gender_pref"),
    )


def _resolve_live_gateway(
    live_mode: AuthorV2RunMode,
    gateway: AuthorV2LLMGateway | None,
) -> list[tuple[str, AuthorV2LLMGateway]]:
    if live_mode == "deterministic":
        return []
    if gateway is not None:
        return [(gateway.profile_id, gateway)]
    resolved_gateways: list[tuple[str, AuthorV2LLMGateway]] = []
    for candidate_mode in resolve_author_v2_live_mode_chain(live_mode):
        try:
            resolved_gateways.append((candidate_mode, get_author_v2_llm_gateway(candidate_mode)))
        except Exception:  # noqa: BLE001
            continue
    return resolved_gateways


def _allow_live_downgrade(live_mode: AuthorV2RunMode) -> bool:
    return live_mode in _MAINLINE_LIVE_MODES


def _quality_metrics(
    *,
    requested_mode: str,
    actual_mode: str,
    used_live_output: bool,
    live_attempt_count: int,
    live_success_count: int,
    provider_failure_count: int,
    actual_modes: list[str] | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "requested_mode": requested_mode,
        "actual_mode": actual_mode,
        "used_live_output": used_live_output,
        "live_attempt_count": live_attempt_count,
        "live_success_count": live_success_count,
        "provider_failure_count": provider_failure_count,
    }
    if actual_modes:
        metrics["actual_modes"] = actual_modes
    return metrics


def _maybe_live_preview_blueprint(
    state: PreviewState,
    deterministic_blueprint: UrbanPreviewBlueprint,
) -> tuple[UrbanPreviewBlueprint, list[dict[str, Any]], list[str], str, str, dict[str, Any]]:
    live_mode = state.get("live_mode", "deterministic")
    if live_mode == "deterministic":
        return deterministic_blueprint, [], [], "accepted", "deterministic", _quality_metrics(
            requested_mode="deterministic",
            actual_mode="deterministic",
            used_live_output=False,
            live_attempt_count=0,
            live_success_count=0,
            provider_failure_count=0,
        )
    gateways = _resolve_live_gateway(live_mode, state.get("live_gateway"))
    if not gateways:
        outcome, reasons = retry_exhausted_outcome(
            strict_enabled=_strict_no_repair_fallback_enabled(),
            last_reason="live_gateway_unavailable",
        )
        return deterministic_blueprint, [], reasons, outcome, live_mode, _quality_metrics(
            requested_mode=live_mode,
            actual_mode="deterministic",
            used_live_output=False,
            live_attempt_count=0,
            live_success_count=0,
            provider_failure_count=0,
        )
    combined_trace: list[dict[str, Any]] = []
    attempt_failures: list[str] = []
    live_attempt_count = 0
    provider_failure_count = 0
    allow_live_downgrade = _allow_live_downgrade(live_mode)
    active_gateways = gateways if allow_live_downgrade else gateways[:1]
    gateway_index = 0
    while live_attempt_count < MAX_STAGE_REGEN_ATTEMPTS and active_gateways:
        source_mode, gateway = active_gateways[gateway_index % len(active_gateways)]
        if is_hero_template(deterministic_blueprint.template_id) and gateway.max_output_tokens_preview is not None and gateway.max_output_tokens_preview < 1200:
            if isinstance(gateway, AuthorV2LLMGateway):
                gateway = replace(gateway, max_output_tokens_preview=1200, call_trace=gateway.call_trace)
            else:
                gateway.max_output_tokens_preview = 1200  # type: ignore[attr-defined]
        trace_cursor = len(gateway.call_trace)
        live_attempt_count += 1
        started = perf_counter()
        try:
            retry_feedback = attempt_failures[-1] if attempt_failures else None
            request_payload: dict[str, Any] = {
                "seed_signals": state["seed_signals"].model_dump(mode="json"),
                "seed_fingerprint": state["seed_fingerprint"].model_dump(mode="json"),
                "template_id": deterministic_blueprint.template_id,
                "deterministic_draft": deterministic_blueprint.model_dump(mode="json"),
                "delta_required_fields": list(_PREVIEW_DELTA_REQUIRED_FIELDS),
                "delta_optional_fields": [field for field in _PREVIEW_DELTA_FIELDS if field not in _PREVIEW_DELTA_REQUIRED_FIELDS],
                "regeneration_index": live_attempt_count,
                "max_regeneration_attempts": MAX_STAGE_REGEN_ATTEMPTS,
            }
            if retry_feedback:
                request_payload["validation_feedback"] = retry_feedback
            response = _invoke_preview_synthesis(
                gateway=gateway,
                request_payload=request_payload,
            )
            combined_trace.extend(
                _extend_llm_trace(
                    state,
                    gateway,
                    start_index=trace_cursor,
                    stage="synthesize_preview_blueprint",
                    duration_seconds=perf_counter() - started,
                )
            )
            candidate = _validate_live_preview_blueprint(
                deterministic_blueprint,
                _coerce_preview_delta_payload(response.payload),
            )
            return (
                candidate,
                combined_trace,
                list(attempt_failures),
                "accepted",
                source_mode,
                _quality_metrics(
                    requested_mode=live_mode,
                    actual_mode=source_mode,
                    used_live_output=True,
                    live_attempt_count=live_attempt_count,
                    live_success_count=1,
                    provider_failure_count=provider_failure_count,
                    actual_modes=[source_mode],
                ),
            )
        except Exception as exc:  # noqa: BLE001
            combined_trace.extend(
                _extend_llm_trace(
                    state,
                    gateway,
                    start_index=trace_cursor,
                    stage="synthesize_preview_blueprint",
                    duration_seconds=perf_counter() - started,
                )
            )
            reason = f"{source_mode}:{fallback_reason(exc)}"
            attempt_failures.append(reason)
            if is_provider_failure(exc):
                provider_failure_count += 1
        gateway_index += 1
    exhausted_reason = attempt_failures[-1] if attempt_failures else "live_gateway_unavailable"
    outcome, reasons = retry_exhausted_outcome(
        strict_enabled=_strict_no_repair_fallback_enabled(),
        last_reason=exhausted_reason,
    )
    return deterministic_blueprint, combined_trace, reasons, outcome, live_mode, _quality_metrics(
        requested_mode=live_mode,
        actual_mode="deterministic",
        used_live_output=False,
        live_attempt_count=live_attempt_count,
        live_success_count=0,
        provider_failure_count=provider_failure_count,
    )


def synthesize_preview_blueprint(state: PreviewState) -> PreviewState:
    deterministic_blueprint = _build_deterministic_preview_blueprint(state)
    live_blueprint, trace, reasons, outcome, source, metrics = _maybe_live_preview_blueprint(state, deterministic_blueprint)
    return {
        "preview_blueprint": live_blueprint,
        "llm_call_trace": trace or list(state.get("llm_call_trace", [])),
        "quality_trace": _append_quality(
            state,
            stage="synthesize_preview_blueprint",
            outcome=outcome,
            reasons=reasons,
            source=source,
            metrics=metrics,
        ),
    }


def normalize_preview_blueprint(state: PreviewState) -> PreviewState:
    blueprint = state["preview_blueprint"]
    normalized = blueprint
    reasons: list[str] = []
    if not any(word in normalized.bomb_moment for word in PUBLIC_BOMB_WORDS):
        reasons.append("bomb_moment_needs_public_stage")
    expected_cast_count = _normalize_cast_count_for_preset(normalized.cast_count_target, normalized.play_length_preset)
    if normalized.cast_count_target != expected_cast_count:
        reasons.append("cast_count_target_mismatch")
    expected_route_target_count = _normalize_route_target_count(normalized.cast_count_target)
    if normalized.route_target_count != expected_route_target_count:
        reasons.append("route_target_count_mismatch")
    expected_experience_band = _experience_band_for_preset(normalized.play_length_preset)
    if normalized.experience_band != expected_experience_band:
        reasons.append("experience_band_mismatch")
    outcome = "accepted" if not reasons else ("retry_exhausted" if _strict_no_repair_fallback_enabled() else "fallback")
    return {
        "preview_blueprint": normalized,
        "quality_trace": _append_quality(
            state,
            stage="normalize_preview_blueprint",
            outcome=outcome,
            reasons=reasons,
        ),
    }


def build_preview_blueprint_graph() -> Any:
    graph = StateGraph(PreviewState)
    graph.add_node("extract_seed_signals", extract_seed_signals)
    graph.add_node("synthesize_preview_blueprint", synthesize_preview_blueprint)
    graph.add_node("normalize_preview_blueprint", normalize_preview_blueprint)
    graph.add_edge(START, "extract_seed_signals")
    graph.add_edge("extract_seed_signals", "synthesize_preview_blueprint")
    graph.add_edge("synthesize_preview_blueprint", "normalize_preview_blueprint")
    graph.add_edge("normalize_preview_blueprint", END)
    return graph.compile()


def run_preview_blueprint_graph(
    prompt_seed: str,
    *,
    preview_id: str | None = None,
    live_mode: AuthorV2RunMode = "deterministic",
    gateway: AuthorV2LLMGateway | None = None,
) -> tuple[UrbanPreviewBlueprint, PreviewState]:
    compiled = build_preview_blueprint_graph()
    initial_state: PreviewState = {
        "prompt_seed": normalize_whitespace(prompt_seed),
        "preview_id": preview_id or f"preview_{slugify(prompt_seed)[:24]}_{uuid4().hex[:8]}",
        "llm_call_trace": [],
        "quality_trace": [],
        "live_mode": live_mode,
        "live_gateway": gateway,
    }
    final_state = compiled.invoke(initial_state)
    return final_state["preview_blueprint"], final_state


def apply_blueprint_edits(
    blueprint: UrbanPreviewBlueprint,
    edits: BlueprintEdits | dict[str, Any] | None = None,
    *,
    accepted_id: str | None = None,
) -> AcceptedBlueprint:
    edit_model = edits if isinstance(edits, BlueprintEdits) else BlueprintEdits(**(edits or {}))
    allowed_updates = {
        key: value
        for key, value in edit_model.model_dump(exclude_none=True).items()
        if key
        in {
            "protagonist_public_identity",
            "protagonist_hidden_need",
            "social_arena",
            "relationship_setup",
            "taboo_secret",
            "route_promise",
            "play_length_preset",
            "cast_count_target",
            "experience_band",
            "story_shell_id",
            "bomb_moment",
            "target_gender_pref",
        }
    }
    updated = blueprint.model_copy(update=allowed_updates)
    normalized_state = normalize_preview_blueprint(
        {
            "preview_blueprint": updated,
            "quality_trace": [],
            "llm_call_trace": [],
        }
    )
    normalized = normalized_state["preview_blueprint"]
    return AcceptedBlueprint(
        **normalized.model_dump(),
        accepted_id=accepted_id or f"accepted_{uuid4().hex[:12]}",
    )
