from __future__ import annotations

from collections import Counter, deque
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import StoryShellId
from rpg_backend.author_v3.contracts import (
    ForgedCharacter,
    RelationshipEdge,
    RelationshipStance,
    WorldConfiguration,
    WorldSeed,
)
from rpg_backend.author_v3.gateway import AuthorV3LLMGateway


_SEED_PARSE_SYSTEM_PROMPT = """
你是剧情世界构建器的第一阶段。
目标：把用户种子解析为 WorldSeed JSON。
必须输出一个 JSON 对象，不要输出任何解释文字。
字段必须覆盖：
- raw_seed
- detected_shell
- setting_description
- tone
- character_count
- theme_keywords
要求：
- detected_shell 只能取 StoryShellId 的合法值
- character_count 在 4 到 7 之间
- theme_keywords 控制在 3 到 6 个
- setting_description 具体、可视觉化
- tone 用简洁短语
""".strip()

_CHARACTER_BATCH_SYSTEM_PROMPT = """
你是剧情世界构建器的第二阶段。
输入是一个已经通过校验的 WorldSeed。
输出必须是 JSON 对象，用于生成角色与主配置信息。
必须输出以下顶层字段：
- characters: ForgedCharacter 数组
- protagonist_id: 主角角色 ID
- setting: 场景文本
- social_arena: 社交竞技场文本
- story_shell_id: 壳类型
每个 characters[i] 必须只包含以下字段：
- character_id: 小写下划线 ID
- display_name: 中文角色名
- gender: 只能是 male 或 female
- public_identity: 角色公开身份
- hidden_need: 角色隐藏需求
- worldly_desire: 只能是 love / status / money / revenge / freedom / control / identity
- fear: 最害怕失去或面对的东西
- shame_trigger: 最怕被揭穿的羞耻点
- breaking_point: 情绪或关系彻底失控的临界点
- speech_pattern: 说话风格
- loyalty_bias: 只能是 self / protagonist / family / institution / chaos / testing
- route_eligible: 布尔值
约束：
- 角色数量应匹配 seed.character_count
- 每个角色必须有稳定动机与破防点
- character_id 使用小写下划线格式
- story_shell_id 必须等于 seed.detected_shell
- social_arena 控制在 120 个字符以内
- 生成的 4 到 7 名角色整体上至少覆盖 2 种彼此对立的 worldly_desire（例如 love vs control、money vs freedom），不要把同一种 desire 分配给所有角色
- 至少要有一对角色共享同一个 worldly_desire，用于形成欲望冲突
- 不要输出 name / role / archetype / public_image / core_motivation / vulnerability / current_stance 等额外字段
- 不要输出额外说明，不要 markdown
""".strip()

_RELATIONSHIP_NEGOTIATION_SYSTEM_PROMPT = """
你是剧情世界构建器的第三阶段。
输入是角色数组。
输出是 JSON 对象，包含完整关系边。
顶层字段必须是：
- relationship_edges: RelationshipEdge 数组
每个 relationship_edges[i] 必须只包含：
- character_a_id
- character_b_id
- public_facade
- hidden_truth
- tension_score
- hooks
- stance_a_to_b
- stance_b_to_a
其中 stance_a_to_b / stance_b_to_a 必须只包含：
- trust_level
- dependency_level
- hidden_dynamic
- tension_source
- power_asymmetry
约束：
- 每条边都要有 public_facade 与 hidden_truth
- 每条边要提供 stance_a_to_b 与 stance_b_to_a
- tension_score 在 0 到 1
- hooks 尽量给出 1 到 3 个可触发线索
- 输出必须是可直接结构化解析的 JSON
""".strip()

_WORLDLY_DESIRE_CONFLICT_ERROR = "world configuration requires at least one conflicting worldly_desire pair"
_WORLDLY_DESIRE_DIVERSITY_ERROR = "world configuration must include at least 2 distinct worldly_desire types"
_WORLDLY_DESIRE_VALIDATION_ERRORS = frozenset(
    {_WORLDLY_DESIRE_CONFLICT_ERROR, _WORLDLY_DESIRE_DIVERSITY_ERROR}
)


class _CharacterBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    characters: list[ForgedCharacter] = Field(min_length=4, max_length=7)
    protagonist_id: str | None = Field(default=None, min_length=1, max_length=64)
    setting: str | None = Field(default=None, min_length=1, max_length=200)
    social_arena: str | None = Field(default=None, min_length=1, max_length=120)
    story_shell_id: StoryShellId | None = None


class _RelationshipNegotiationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_edges: list[RelationshipEdge] = Field(min_length=3)


def forge_world(
    seed_text: str,
    *,
    gateway: AuthorV3LLMGateway | None = None,
    shell_hint: StoryShellId | None = None,
    validation_feedback: str | None = None,
    validation_retry: int = 0,
) -> WorldConfiguration:
    if gateway is None:
        config = _forge_world_deterministic()
        return config
    config = _forge_world_with_gateway(
        seed_text=seed_text,
        gateway=gateway,
        shell_hint=shell_hint,
        validation_feedback=validation_feedback,
        validation_retry=validation_retry,
    )
    _validate_world_config(config)
    return config


def _forge_world_deterministic() -> WorldConfiguration:
    seed = WorldSeed(
        raw_seed="董事会权力斗争",
        detected_shell="office_power",
        setting_description="科技公司总部大楼",
        tone="紧张压抑",
        character_count=5,
        theme_keywords=["权力", "背叛", "秘密"],
    )
    characters = _build_deterministic_characters()
    relationship_edges = _build_deterministic_relationship_edges()
    config = WorldConfiguration(
        seed=seed,
        setting="科技公司总部大楼",
        social_arena="董事会与高管闭门博弈",
        story_shell_id="office_power",
        characters=characters,
        relationship_edges=relationship_edges,
        protagonist_id="zhang_hao",
    )
    _validate_world_config(config)
    return config


def _forge_world_with_gateway(
    *,
    seed_text: str,
    gateway: AuthorV3LLMGateway,
    shell_hint: StoryShellId | None,
    validation_feedback: str | None,
    validation_retry: int,
) -> WorldConfiguration:
    seed_response = gateway.invoke_json(
        system_prompt=_SEED_PARSE_SYSTEM_PROMPT,
        user_payload={"seed_text": seed_text, "shell_hint": shell_hint},
        max_output_tokens=gateway.max_output_tokens_world_forge,
        operation_name="author_v3.world_forge.seed_parsing",
        response_model=WorldSeed,
        max_retries=3,
    )
    seed = _parse_seed_payload(seed_response.payload)

    character_user_payload: dict[str, Any] = {"seed": seed.dict()}
    if validation_feedback:
        character_user_payload["validation_feedback"] = validation_feedback
        character_user_payload["validation_retry"] = validation_retry

    characters_response = gateway.invoke_json(
        system_prompt=_character_batch_system_prompt(validation_feedback=validation_feedback),
        user_payload=character_user_payload,
        max_output_tokens=gateway.max_output_tokens_world_forge,
        operation_name="author_v3.world_forge.character_batch",
        response_model=_CharacterBatchResponse,
        max_retries=3,
    )
    characters_payload = _parse_character_batch_payload(characters_response.payload)
    characters = characters_payload["characters"]

    relationships_response = gateway.invoke_json(
        system_prompt=_RELATIONSHIP_NEGOTIATION_SYSTEM_PROMPT,
        user_payload={"characters": [character.dict() for character in characters]},
        max_output_tokens=gateway.max_output_tokens_world_forge,
        operation_name="author_v3.world_forge.relationship_negotiation",
        response_model=_RelationshipNegotiationResponse,
        max_retries=3,
    )
    relationship_edges = _parse_relationship_payload(relationships_response.payload)

    protagonist_id = str(characters_payload.get("protagonist_id") or _fallback_protagonist_id(characters))
    setting = str(characters_payload.get("setting") or seed.setting_description)
    social_arena = str(characters_payload.get("social_arena") or seed.setting_description)
    story_shell_id = str(characters_payload.get("story_shell_id") or seed.detected_shell)

    config = WorldConfiguration(
        seed=seed,
        setting=setting,
        social_arena=social_arena,
        story_shell_id=story_shell_id,
        characters=characters,
        relationship_edges=relationship_edges,
        protagonist_id=protagonist_id,
    )
    return config


def _parse_seed_payload(payload: Any) -> WorldSeed:
    base = _coerce_mapping(payload)
    target = _extract_mapping(base, ["seed", "world_seed", "result"])
    if target is None:
        target = base
    return WorldSeed.model_validate(target)


def _parse_character_batch_payload(payload: Any) -> dict[str, Any]:
    base = _coerce_mapping(payload)
    target = _extract_mapping(base, ["character_batch", "characters_payload", "result"])
    if target is None:
        target = base

    raw_characters = _extract_list(target, ["characters", "cast", "forged_characters"])
    if raw_characters is None:
        raw_characters = _extract_list(base, ["characters", "cast", "forged_characters"])
    if raw_characters is None:
        raise ValueError("character batch response missing characters list")

    characters = [ForgedCharacter.model_validate(item) for item in raw_characters]

    protagonist_id = _extract_str(target, ["protagonist_id", "protagonist", "lead_character_id"])
    if protagonist_id is None:
        protagonist_id = _extract_str(base, ["protagonist_id", "protagonist", "lead_character_id"])

    setting = _extract_str(target, ["setting", "setting_description", "world_setting"])
    if setting is None:
        setting = _extract_str(base, ["setting", "setting_description", "world_setting"])

    social_arena = _extract_str(target, ["social_arena", "arena", "social_context"])
    if social_arena is None:
        social_arena = _extract_str(base, ["social_arena", "arena", "social_context"])

    story_shell_id = _extract_str(target, ["story_shell_id", "shell_id", "detected_shell"])
    if story_shell_id is None:
        story_shell_id = _extract_str(base, ["story_shell_id", "shell_id", "detected_shell"])

    return {
        "characters": characters,
        "protagonist_id": protagonist_id,
        "setting": setting,
        "social_arena": social_arena,
        "story_shell_id": story_shell_id,
    }


_NUMERIC_STANCE_FIELDS = ("trust_level", "dependency_level", "power_asymmetry")


def _coerce_float_field(value: Any, *, default: float, lo: float, hi: float) -> float:
    """Best-effort coercion of an LLM-emitted value into a clamped float.

    qwen3.5-flash routinely fills numeric stance fields with prose
    ("李伟占据绝对权力优势...") instead of a number. Pydantic's float_parsing
    then fails the whole edge, retries don't fix it, and the author job dies
    before world_forge completes. We accept a string only if it looks like a
    parseable float; otherwise fall back to `default`. Bounds-clamp to [lo, hi].
    """
    if isinstance(value, bool):
        return default  # bools are ints in Python; not a real number here
    if isinstance(value, (int, float)):
        return max(lo, min(hi, float(value)))
    if isinstance(value, str):
        try:
            return max(lo, min(hi, float(value.strip())))
        except (TypeError, ValueError):
            return default
    return default


def _sanitize_stance(raw: Any) -> dict[str, Any]:
    """Patch a single stance dict so RelationshipStance.model_validate succeeds
    even when the LLM filled numeric fields with prose."""
    if not isinstance(raw, Mapping):
        return {}
    patched: dict[str, Any] = dict(raw)
    if "trust_level" in patched:
        patched["trust_level"] = _coerce_float_field(patched["trust_level"], default=0.5, lo=0.0, hi=1.0)
    if "dependency_level" in patched:
        patched["dependency_level"] = _coerce_float_field(patched["dependency_level"], default=0.5, lo=0.0, hi=1.0)
    if "power_asymmetry" in patched:
        patched["power_asymmetry"] = _coerce_float_field(patched["power_asymmetry"], default=0.0, lo=-1.0, hi=1.0)
    return patched


def _parse_relationship_payload(payload: Any) -> list[RelationshipEdge]:
    base = _coerce_mapping(payload)
    target = _extract_mapping(base, ["relationship_batch", "relationships", "result"])
    if target is None:
        target = base

    raw_edges = _extract_list(target, ["relationship_edges", "edges", "relations"])
    if raw_edges is None:
        raw_edges = _extract_list(base, ["relationship_edges", "edges", "relations"])
    if raw_edges is None:
        raise ValueError("relationship negotiation response missing edges list")

    edges: list[RelationshipEdge] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping):
            continue
        # Sanitize the two stance objects before pydantic validation, then also
        # coerce the edge-level tension_score in case the LLM put prose there too.
        patched_edge: dict[str, Any] = dict(raw_edge)
        if "stance_a_to_b" in patched_edge:
            patched_edge["stance_a_to_b"] = _sanitize_stance(patched_edge["stance_a_to_b"])
        if "stance_b_to_a" in patched_edge:
            patched_edge["stance_b_to_a"] = _sanitize_stance(patched_edge["stance_b_to_a"])
        if "tension_score" in patched_edge:
            patched_edge["tension_score"] = _coerce_float_field(
                patched_edge["tension_score"], default=0.5, lo=0.0, hi=1.0
            )
        try:
            edges.append(RelationshipEdge.model_validate(patched_edge))
        except Exception:  # noqa: BLE001 — skip malformed edges, don't kill the job
            continue
    if not edges:
        raise ValueError("relationship negotiation produced no usable edges")
    return edges


def _coerce_mapping(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    raise ValueError(f"gateway payload must be an object, got {type(payload).__name__}")


def _extract_mapping(source: Mapping[str, Any], keys: list[str]) -> Mapping[str, Any] | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _extract_list(source: Mapping[str, Any], keys: list[str]) -> list[Any] | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            return value
    return None


def _extract_str(source: Mapping[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _fallback_protagonist_id(characters: list[ForgedCharacter]) -> str:
    for character in characters:
        if character.route_eligible:
            return character.character_id
    if characters:
        return characters[0].character_id
    raise ValueError("cannot infer protagonist_id from empty character list")


def _character_batch_system_prompt(*, validation_feedback: str | None) -> str:
    if not validation_feedback:
        return _CHARACTER_BATCH_SYSTEM_PROMPT
    return (
        f"{_CHARACTER_BATCH_SYSTEM_PROMPT}\n\n"
        "⚠️ 上次世界配置验证失败，请修正后重新输出完整角色配置。\n"
        f"上次错误：\n{validation_feedback}\n\n"
        "重点检查 worldly_desire 的分布，确保既有冲突也有多样性。"
    )


def _build_deterministic_characters() -> list[ForgedCharacter]:
    return [
        ForgedCharacter(
            character_id="chen_weiming",
            display_name="陈伟明",
            gender="male",
            public_identity="科技公司CEO，行业领袖",
            hidden_need="掩盖早年财务造假的真相",
            worldly_desire="control",
            fear="被董事会罢免",
            shame_trigger="创业期间的背叛行为",
            breaking_point="私生子身份曝光",
            speech_pattern="冷静克制，喜欢用商业术语",
            loyalty_bias="institution",
            route_eligible=False,
        ),
        ForgedCharacter(
            character_id="lin_yuxin",
            display_name="林雨欣",
            gender="female",
            public_identity="VP of Marketing，公司形象代言人",
            hidden_need="取代CEO成为实际掌权者",
            worldly_desire="status",
            fear="被发现学历造假",
            shame_trigger="曾为上位出卖前任",
            breaking_point="与CEO的秘密交易曝光",
            speech_pattern="优雅得体但暗藏锋芒",
            loyalty_bias="self",
            route_eligible=True,
        ),
        ForgedCharacter(
            character_id="zhang_hao",
            display_name="张浩",
            gender="male",
            public_identity="CTO，技术天才",
            hidden_need="拿回被窃取的核心专利",
            worldly_desire="revenge",
            fear="技术被彻底边缘化",
            shame_trigger="曾因懦弱放弃维权",
            breaking_point="发现CEO利用他的技术牟利的证据",
            speech_pattern="技术宅，说话直接不拐弯",
            loyalty_bias="protagonist",
            route_eligible=True,
        ),
        ForgedCharacter(
            character_id="wang_siyu",
            display_name="王思雨",
            gender="female",
            public_identity="CFO，财务专家",
            hidden_need="保护自己参与的灰色交易记录",
            worldly_desire="money",
            fear="审计暴露关联交易",
            shame_trigger="挪用公款填补个人亏空",
            breaking_point="被迫在忠诚和自保间选择",
            speech_pattern="数字精确，措辞谨慎",
            loyalty_bias="family",
            route_eligible=True,
        ),
        ForgedCharacter(
            character_id="liu_jianfeng",
            display_name="刘建锋",
            gender="male",
            public_identity="外部投资人代表",
            hidden_need="通过收购获取公司控制权",
            worldly_desire="control",
            fear="投资失败导致基金崩盘",
            shame_trigger="曾操纵市场被私下和解",
            breaking_point="对手掌握了他操纵市场的录音",
            speech_pattern="圆滑世故，善于画饼",
            loyalty_bias="chaos",
            route_eligible=False,
        ),
    ]


def _build_deterministic_relationship_edges() -> list[RelationshipEdge]:
    return [
        RelationshipEdge(
            character_a_id="chen_weiming",
            character_b_id="lin_yuxin",
            public_facade="CEO与市场副总保持对外一致口径",
            hidden_truth="两人曾签下互保协议，任何一方失势都会拖垮另一方",
            tension_score=0.82,
            hooks=["chen_weiming", "lin_yuxin", "旧协议副本"],
            stance_a_to_b=_build_stance(
                trust_level=0.44,
                dependency_level=0.71,
                hidden_dynamic="把她当棋子也当保险",
                tension_source="她不断试探董事会风向",
                power_asymmetry=0.36,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.31,
                dependency_level=0.64,
                hidden_dynamic="表面追随，实则等待反噬时机",
                tension_source="担心自己成为替罪羊",
                power_asymmetry=-0.22,
            ),
        ),
        RelationshipEdge(
            character_a_id="chen_weiming",
            character_b_id="zhang_hao",
            public_facade="CEO公开称赞CTO是公司技术中枢",
            hidden_truth="CEO压住专利署名并将收益导向影子实体",
            tension_score=0.88,
            hooks=["chen_weiming", "zhang_hao", "专利原始提交记录"],
            stance_a_to_b=_build_stance(
                trust_level=0.25,
                dependency_level=0.79,
                hidden_dynamic="需要技术成果但不愿放权",
                tension_source="担心他掌握翻盘证据",
                power_asymmetry=0.51,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.18,
                dependency_level=0.53,
                hidden_dynamic="被压制多年后转为沉默复仇",
                tension_source="专利收益被侵占",
                power_asymmetry=-0.47,
            ),
        ),
        RelationshipEdge(
            character_a_id="chen_weiming",
            character_b_id="wang_siyu",
            public_facade="CEO与CFO在财报发布会上配合默契",
            hidden_truth="CFO掌握能指向CEO的灰账流向，双方互相挟持",
            tension_score=0.76,
            hooks=["chen_weiming", "wang_siyu", "审计前夜邮件"],
            stance_a_to_b=_build_stance(
                trust_level=0.39,
                dependency_level=0.82,
                hidden_dynamic="需要她封口，也怕她反水",
                tension_source="审计团队开始追问异常科目",
                power_asymmetry=0.28,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.34,
                dependency_level=0.76,
                hidden_dynamic="以专业忠诚维持脆弱平衡",
                tension_source="任何一方先弃车都会引发连锁爆雷",
                power_asymmetry=-0.18,
            ),
        ),
        RelationshipEdge(
            character_a_id="chen_weiming",
            character_b_id="liu_jianfeng",
            public_facade="CEO与外部投资人共同宣称支持公司长期战略",
            hidden_truth="投资人逼迫触发对赌条款，意图在危机中夺权",
            tension_score=0.79,
            hooks=["chen_weiming", "liu_jianfeng", "对赌补充条款"],
            stance_a_to_b=_build_stance(
                trust_level=0.22,
                dependency_level=0.61,
                hidden_dynamic="把资本当止血包却惧怕被反噬",
                tension_source="增发与控制权条款冲突",
                power_asymmetry=0.12,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.27,
                dependency_level=0.48,
                hidden_dynamic="保持合作姿态以拖到收购窗口",
                tension_source="CEO拖延董事会重组",
                power_asymmetry=-0.08,
            ),
        ),
        RelationshipEdge(
            character_a_id="lin_yuxin",
            character_b_id="zhang_hao",
            public_facade="市场与技术部门在新品发布前频繁联动",
            hidden_truth="林雨欣暗中鼓动张浩揭露CEO，以便自己上位",
            tension_score=0.69,
            hooks=["lin_yuxin", "zhang_hao", "发布会脚本改版记录"],
            stance_a_to_b=_build_stance(
                trust_level=0.57,
                dependency_level=0.52,
                hidden_dynamic="把他视作扳倒CEO的关键证人",
                tension_source="他随时可能拒绝被利用",
                power_asymmetry=0.11,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.46,
                dependency_level=0.41,
                hidden_dynamic="接受合作但提防她借刀杀人",
                tension_source="担心真相被她包装成个人战绩",
                power_asymmetry=-0.15,
            ),
        ),
        RelationshipEdge(
            character_a_id="lin_yuxin",
            character_b_id="wang_siyu",
            public_facade="营销与财务在预算会上互相背书",
            hidden_truth="林雨欣握有CFO私人账户转账线索，长期施压换取资源",
            tension_score=0.66,
            hooks=["lin_yuxin", "wang_siyu", "异常报销流水"],
            stance_a_to_b=_build_stance(
                trust_level=0.42,
                dependency_level=0.49,
                hidden_dynamic="以人情与威胁并用维持联盟",
                tension_source="预算削减触发互相甩锅",
                power_asymmetry=0.18,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.29,
                dependency_level=0.58,
                hidden_dynamic="被迫配合以换取对方暂缓爆料",
                tension_source="害怕私账曝光导致职业终结",
                power_asymmetry=-0.24,
            ),
        ),
        RelationshipEdge(
            character_a_id="lin_yuxin",
            character_b_id="liu_jianfeng",
            public_facade="市场副总与投资人代表常在公开场合互相吹捧",
            hidden_truth="两人私下谈判过权力置换，彼此都准备随时毁约",
            tension_score=0.73,
            hooks=["lin_yuxin", "liu_jianfeng", "并购前夜饭局录音"],
            stance_a_to_b=_build_stance(
                trust_level=0.33,
                dependency_level=0.55,
                hidden_dynamic="想借资本力量抬升自己的谈判筹码",
                tension_source="担心被投资人当成过渡棋子",
                power_asymmetry=-0.05,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.36,
                dependency_level=0.43,
                hidden_dynamic="愿意扶持她挑战CEO但只为收购服务",
                tension_source="她可能在关键投票倒向别派",
                power_asymmetry=0.14,
            ),
        ),
        RelationshipEdge(
            character_a_id="zhang_hao",
            character_b_id="wang_siyu",
            public_facade="CTO与CFO在公开会议上以专业数据互证",
            hidden_truth="王思雨曾建议冻结张浩项目预算以换取财务安全",
            tension_score=0.67,
            hooks=["zhang_hao", "wang_siyu", "预算冻结审批链"],
            stance_a_to_b=_build_stance(
                trust_level=0.38,
                dependency_level=0.47,
                hidden_dynamic="需要她配合还原资金流向",
                tension_source="不确定她会不会再次站队CEO",
                power_asymmetry=-0.09,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.41,
                dependency_level=0.36,
                hidden_dynamic="认可他的技术价值但不愿承担连带风险",
                tension_source="怕他公开证据时把自己一并卷入",
                power_asymmetry=0.07,
            ),
        ),
        RelationshipEdge(
            character_a_id="zhang_hao",
            character_b_id="liu_jianfeng",
            public_facade="CTO与投资人对外表现为理性讨论研发投入",
            hidden_truth="投资人想低价买断其技术资产，张浩则在反向搜证",
            tension_score=0.84,
            hooks=["zhang_hao", "liu_jianfeng", "技术估值底稿"],
            stance_a_to_b=_build_stance(
                trust_level=0.21,
                dependency_level=0.32,
                hidden_dynamic="把对方视作第二掠夺者",
                tension_source="担心专利再次被资本包装转移",
                power_asymmetry=-0.27,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.24,
                dependency_level=0.51,
                hidden_dynamic="用收购承诺诱导他交出核心算法",
                tension_source="他已察觉条款陷阱",
                power_asymmetry=0.33,
            ),
        ),
        RelationshipEdge(
            character_a_id="wang_siyu",
            character_b_id="liu_jianfeng",
            public_facade="CFO与投资人代表在资本会议中保持专业合作",
            hidden_truth="双方共同参与过边缘交易，彼此都留有可致命证据",
            tension_score=0.77,
            hooks=["wang_siyu", "liu_jianfeng", "离岸账户授权书"],
            stance_a_to_b=_build_stance(
                trust_level=0.28,
                dependency_level=0.63,
                hidden_dynamic="依赖其资金续命又惧怕被切割",
                tension_source="基金方要求她单独背责",
                power_asymmetry=-0.19,
            ),
            stance_b_to_a=_build_stance(
                trust_level=0.32,
                dependency_level=0.46,
                hidden_dynamic="以救火者姿态掩饰清算意图",
                tension_source="她掌握能触发监管调查的原始票据",
                power_asymmetry=0.21,
            ),
        ),
    ]


def _build_stance(
    *,
    trust_level: float,
    dependency_level: float,
    hidden_dynamic: str,
    tension_source: str,
    power_asymmetry: float,
) -> RelationshipStance:
    return RelationshipStance(
        trust_level=trust_level,
        dependency_level=dependency_level,
        hidden_dynamic=hidden_dynamic,
        tension_source=tension_source,
        power_asymmetry=power_asymmetry,
    )


def _validate_world_config(config: WorldConfiguration) -> None:
    character_ids = [character.character_id for character in config.characters]
    character_id_set = set(character_ids)

    if config.protagonist_id not in character_id_set:
        raise ValueError(f"protagonist_id '{config.protagonist_id}' is not present in characters")

    edge_count_by_character = {character_id: 0 for character_id in character_ids}
    adjacency: dict[str, set[str]] = {character_id: set() for character_id in character_ids}

    for edge in config.relationship_edges:
        char_a_id = edge.character_a_id
        char_b_id = edge.character_b_id

        if char_a_id not in character_id_set or char_b_id not in character_id_set:
            raise ValueError(
                "relationship edge references unknown characters: "
                f"{char_a_id}, {char_b_id}"
            )

        edge_count_by_character[char_a_id] += 1
        edge_count_by_character[char_b_id] += 1
        adjacency[char_a_id].add(char_b_id)
        adjacency[char_b_id].add(char_a_id)

    low_degree_characters = [
        character_id for character_id, edge_count in edge_count_by_character.items() if edge_count < 2
    ]
    if low_degree_characters:
        joined = ", ".join(sorted(low_degree_characters))
        raise ValueError(f"every character must have at least 2 relationship edges: {joined}")

    visited: set[str] = set()
    queue: deque[str] = deque([config.protagonist_id])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for neighbor in adjacency.get(current, set()):
            if neighbor not in visited:
                queue.append(neighbor)

    if len(visited) != len(character_ids):
        missing = ", ".join(sorted(character_id_set - visited))
        raise ValueError(f"relationship graph is disconnected from protagonist: {missing}")

    worldly_desire_counts = Counter(character.worldly_desire for character in config.characters)
    if len(worldly_desire_counts) < 2:
        raise ValueError(_WORLDLY_DESIRE_DIVERSITY_ERROR)
    has_conflict = any(count >= 2 for count in worldly_desire_counts.values())
    if not has_conflict:
        raise ValueError(_WORLDLY_DESIRE_CONFLICT_ERROR)
