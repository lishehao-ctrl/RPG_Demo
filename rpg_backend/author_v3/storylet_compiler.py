from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author_v2.contracts import SegmentRoleId
from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.gateway import AuthorV3LLMGateway
from rpg_backend.author_v3.tension_weaver import TensionWeb


NarrativeFunction = Literal[
    "hook",
    "escalation",
    "reversal",
    "revelation",
    "cost",
    "resolution",
]

_FUNCTION_TO_SEGMENT_ROLE: dict[NarrativeFunction, SegmentRoleId] = {
    "hook": "opening",
    "escalation": "misread",
    "reversal": "reversal",
    "revelation": "reveal",
    "cost": "pressure",
    "resolution": "terminal",
}

_SEGMENT_ROLE_MOVE_DEFAULTS: dict[SegmentRoleId, list[RelationshipMoveFamily]] = {
    "opening": ["flirt", "comfort", "probe_secret"],
    "misread": ["flirt", "deflect", "ally_with", "probe_secret"],
    "pressure": ["accuse", "probe_secret", "jealousy_trigger", "deflect"],
    "reversal": ["betray", "accuse", "public_reveal", "private_confession"],
    "reveal": ["public_reveal", "private_confession", "probe_secret", "accuse"],
    "terminal": ["ally_with", "betray", "public_reveal", "private_confession"],
}


class StoryletCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_secrets_known: list[str] = Field(default_factory=list, max_length=3)
    required_relationships: list[str] = Field(default_factory=list, max_length=3)
    min_tension_score: float = Field(default=0.0, ge=0.0, le=1.0)
    required_segment_roles: list[SegmentRoleId] = Field(default_factory=list, max_length=3)


class StoryletEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secrets_revealed: list[str] = Field(default_factory=list, max_length=3)
    relationship_shifts: dict[str, float] = Field(default_factory=dict)
    tension_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    triggers_chain: str | None = Field(default=None, max_length=64)


class Storylet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storylet_id: str = Field(min_length=1, max_length=64)
    narrative_function: NarrativeFunction
    title: str = Field(min_length=1, max_length=120)
    scene_text: str = Field(min_length=1, max_length=500)
    characters_involved: list[str] = Field(min_length=1, max_length=5)
    venue_hint: str = Field(min_length=1, max_length=120)
    dramatic_weight: float = Field(ge=0.0, le=1.0)
    cooldown_turns: int = Field(default=0, ge=0, le=6)
    preconditions: StoryletCondition = Field(default_factory=StoryletCondition)
    effects: StoryletEffect = Field(default_factory=StoryletEffect)


class StoryletPool(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storylets: list[Storylet] = Field(min_length=4, max_length=60)
    function_counts: dict[NarrativeFunction, int] = Field(default_factory=dict)


class MappedSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    segment_role: SegmentRoleId
    source_storylet_id: str = Field(min_length=1, max_length=64)
    focus_target_ids: list[str] = Field(default_factory=list, max_length=2)
    rival_target_ids: list[str] = Field(default_factory=list, max_length=2)
    allocated_secret_ids: list[str] = Field(default_factory=list, max_length=3)
    is_terminal: bool = False
    allowed_move_families: list[RelationshipMoveFamily] = Field(min_length=2, max_length=6)
    venue_id: str = Field(min_length=1, max_length=120)
    scene_goal: str = Field(min_length=1, max_length=220)
    emotional_goal: str = Field(min_length=1, max_length=220)
    move_priorities: list[RelationshipMoveFamily] = Field(min_length=2, max_length=6)
    public_pressure_cue: str = Field(min_length=1, max_length=220)
    private_pressure_cue: str = Field(min_length=1, max_length=220)


_ARC_SEGMENT_SEQUENCE: dict[str, list[SegmentRoleId]] = {
    "short_3": ["opening", "reversal", "terminal"],
    "compact_4": ["opening", "pressure", "reversal", "terminal"],
    "standard_4": ["opening", "misread", "reversal", "terminal"],
    "long_5": ["opening", "misread", "pressure", "reversal", "terminal"],
    "flagship_6": ["opening", "misread", "pressure", "reversal", "reveal", "terminal"],
    "super_flagship_8": ["opening", "misread", "pressure", "misread", "reversal", "pressure", "reveal", "terminal"],
}


class StoryletCompilerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _deterministic_storylets(
    config: WorldConfiguration,
    web: TensionWeb,
    matrix: RelationshipMatrix,
) -> list[Storylet]:
    protagonist = config.protagonist_id
    chars = {c.character_id: c for c in config.characters}
    secret_map = {s.secret_id: s for s in web.secrets}

    rival_id = None
    ally_id = None
    for cid, slot in matrix.slot_assignments.items():
        if slot == "rival_interest":
            rival_id = cid
        elif slot == "hidden_ally":
            ally_id = cid
    if rival_id is None:
        rival_id = [c for c in chars if c != protagonist][0]
    if ally_id is None:
        ally_id = [c for c in chars if c not in (protagonist, rival_id)][0]

    other_ids = [c for c in chars if c not in (protagonist, rival_id, ally_id)]

    storylets: list[Storylet] = []

    storylets.append(Storylet(
        storylet_id="st_opening_tension",
        narrative_function="hook",
        title="暗流涌动的开场",
        scene_text=f"{chars[protagonist].display_name}踏入公司高层会议，空气中弥漫着不安的气息。{chars[rival_id].display_name}的眼神意味深长。",
        characters_involved=[protagonist, rival_id],
        venue_hint=config.social_arena,
        dramatic_weight=0.5,
        preconditions=StoryletCondition(),
        effects=StoryletEffect(tension_delta=0.1),
    ))
    storylets.append(Storylet(
        storylet_id="st_opening_alliance",
        narrative_function="hook",
        title="不期而遇的善意",
        scene_text=f"{chars[ally_id].display_name}在走廊拦住{chars[protagonist].display_name}，低声透露了一个不安的消息。",
        characters_involved=[protagonist, ally_id],
        venue_hint="走廊",
        dramatic_weight=0.4,
        preconditions=StoryletCondition(),
        effects=StoryletEffect(tension_delta=0.05),
    ))

    storylets.append(Storylet(
        storylet_id="st_escalation_misread",
        narrative_function="escalation",
        title="错误的信任",
        scene_text=f"{chars[protagonist].display_name}误解了{chars[rival_id].display_name}的意图，在公开场合做出了错误判断。",
        characters_involved=[protagonist, rival_id, ally_id],
        venue_hint=config.social_arena,
        dramatic_weight=0.6,
        preconditions=StoryletCondition(min_tension_score=0.3),
        effects=StoryletEffect(tension_delta=0.15),
    ))
    storylets.append(Storylet(
        storylet_id="st_escalation_secret_hint",
        narrative_function="escalation",
        title="秘密的端倪",
        scene_text=f"一份意外发现的文件让{chars[protagonist].display_name}开始怀疑事情并非表面所见。",
        characters_involved=[protagonist] + other_ids[:1],
        venue_hint="档案室",
        dramatic_weight=0.55,
        preconditions=StoryletCondition(),
        effects=StoryletEffect(
            secrets_revealed=[web.secrets[0].secret_id] if web.secrets else [],
            tension_delta=0.1,
        ),
    ))

    pressure_secrets = [s for s in web.secrets if s.lethality_score >= 0.7]
    storylets.append(Storylet(
        storylet_id="st_pressure_confrontation",
        narrative_function="cost",
        title="逼迫与抉择",
        scene_text=f"{chars[rival_id].display_name}利用手中的筹码向{chars[protagonist].display_name}施压，要求做出选择。",
        characters_involved=[protagonist, rival_id],
        venue_hint="私人办公室",
        dramatic_weight=0.75,
        preconditions=StoryletCondition(min_tension_score=0.5),
        effects=StoryletEffect(tension_delta=0.2),
    ))
    storylets.append(Storylet(
        storylet_id="st_pressure_public_wave",
        narrative_function="cost",
        title="舆论风暴",
        scene_text=f"关于{chars[protagonist].display_name}的传闻开始在公司内部流传，{chars.get(other_ids[0], chars[rival_id]).display_name}暗中推波助澜。",
        characters_involved=[protagonist] + other_ids[:2],
        venue_hint="公司大厅",
        dramatic_weight=0.65,
        preconditions=StoryletCondition(min_tension_score=0.4),
        effects=StoryletEffect(tension_delta=0.15),
    ))

    storylets.append(Storylet(
        storylet_id="st_reversal_betrayal",
        narrative_function="reversal",
        title="意想不到的背叛",
        scene_text=f"{chars[ally_id].display_name}在关键时刻倒戈，{chars[protagonist].display_name}发现自己一直被蒙在鼓里。",
        characters_involved=[protagonist, ally_id, rival_id],
        venue_hint=config.social_arena,
        dramatic_weight=0.85,
        preconditions=StoryletCondition(min_tension_score=0.6),
        effects=StoryletEffect(tension_delta=0.25, relationship_shifts={ally_id: -0.4}),
    ))
    storylets.append(Storylet(
        storylet_id="st_reversal_power_shift",
        narrative_function="reversal",
        title="权力的翻转",
        scene_text=f"一封被截获的邮件彻底改变了力量对比，{chars[rival_id].display_name}的真实目的暴露无遗。",
        characters_involved=[protagonist, rival_id] + other_ids[:1],
        venue_hint="会议室",
        dramatic_weight=0.8,
        preconditions=StoryletCondition(min_tension_score=0.5),
        effects=StoryletEffect(
            secrets_revealed=[pressure_secrets[0].secret_id] if pressure_secrets else [],
            tension_delta=0.2,
        ),
    ))

    storylets.append(Storylet(
        storylet_id="st_revelation_truth",
        narrative_function="revelation",
        title="真相大白",
        scene_text=f"所有隐藏的秘密在众人面前被逐一揭开，{chars[protagonist].display_name}终于看清了全貌。",
        characters_involved=[protagonist, rival_id, ally_id] + other_ids[:1],
        venue_hint=config.social_arena,
        dramatic_weight=0.9,
        preconditions=StoryletCondition(min_tension_score=0.7),
        effects=StoryletEffect(
            secrets_revealed=[s.secret_id for s in web.secrets[:2]],
            tension_delta=0.1,
        ),
    ))
    storylets.append(Storylet(
        storylet_id="st_revelation_chain",
        narrative_function="revelation",
        title="连锁曝光",
        scene_text=f"一个秘密的暴露引发了连锁反应，更多不可告人的真相浮出水面。",
        characters_involved=list(chars.keys())[:4],
        venue_hint="董事会议室",
        dramatic_weight=0.85,
        preconditions=StoryletCondition(
            required_secrets_known=[web.secrets[0].secret_id] if web.secrets else [],
            min_tension_score=0.6,
        ),
        effects=StoryletEffect(
            secrets_revealed=[s.secret_id for s in web.secrets[1:3]],
            triggers_chain=web.chains[0].unlocks_secret_id if web.chains else None,
        ),
    ))

    storylets.append(Storylet(
        storylet_id="st_resolution_cost",
        narrative_function="resolution",
        title="代价与选择",
        scene_text=f"{chars[protagonist].display_name}面临最终的抉择——每条路都有不可逆的代价。",
        characters_involved=[protagonist, rival_id],
        venue_hint=config.social_arena,
        dramatic_weight=0.95,
        preconditions=StoryletCondition(min_tension_score=0.7),
        effects=StoryletEffect(tension_delta=-0.3),
    ))
    storylets.append(Storylet(
        storylet_id="st_resolution_reconcile",
        narrative_function="resolution",
        title="和解或毁灭",
        scene_text=f"尘埃落定，{chars[protagonist].display_name}与{chars[ally_id].display_name}之间的关系走向最终定论。",
        characters_involved=[protagonist, ally_id],
        venue_hint="天台",
        dramatic_weight=0.9,
        preconditions=StoryletCondition(min_tension_score=0.5),
        effects=StoryletEffect(tension_delta=-0.2, relationship_shifts={ally_id: 0.3}),
    ))

    return storylets


def _count_functions(storylets: list[Storylet]) -> dict[NarrativeFunction, int]:
    counts: dict[NarrativeFunction, int] = defaultdict(int)
    for s in storylets:
        counts[s.narrative_function] += 1
    return dict(counts)


def _best_storylet_for_role(
    role: SegmentRoleId,
    pool: list[Storylet],
    used: set[str],
) -> Storylet | None:
    candidates = []
    for s in pool:
        if s.storylet_id in used:
            continue
        if _FUNCTION_TO_SEGMENT_ROLE.get(s.narrative_function) == role:
            candidates.append(s)
    if not candidates:
        for s in pool:
            if s.storylet_id not in used:
                candidates.append(s)
    if not candidates:
        return None
    candidates.sort(key=lambda s: s.dramatic_weight, reverse=True)
    return candidates[0]


def map_storylets_to_segments(
    pool: StoryletPool,
    arc_template_id: str,
    config: WorldConfiguration,
    web: TensionWeb,
    matrix: RelationshipMatrix,
) -> list[MappedSegment]:
    sequence = _ARC_SEGMENT_SEQUENCE.get(arc_template_id)
    if sequence is None:
        raise StoryletCompilerError(
            "unknown_arc_template", f"arc_template_id={arc_template_id!r} not recognized"
        )

    protagonist = config.protagonist_id
    chars = {c.character_id: c for c in config.characters}
    secret_map = {s.secret_id: s for s in web.secrets}

    rival_id = None
    for cid, slot in matrix.slot_assignments.items():
        if slot == "rival_interest":
            rival_id = cid
            break

    used: set[str] = set()
    segments: list[MappedSegment] = []

    for idx, role in enumerate(sequence):
        storylet = _best_storylet_for_role(role, pool.storylets, used)
        if storylet is None:
            raise StoryletCompilerError(
                "insufficient_storylets",
                f"no storylet available for segment {idx} role={role}",
            )
        used.add(storylet.storylet_id)

        focus_ids = [c for c in storylet.characters_involved if c == protagonist][:1]
        if not focus_ids:
            focus_ids = storylet.characters_involved[:1]

        rival_ids = []
        if rival_id and rival_id in storylet.characters_involved:
            rival_ids = [rival_id]

        secret_ids = storylet.effects.secrets_revealed[:3]

        moves = _SEGMENT_ROLE_MOVE_DEFAULTS.get(role, ["flirt", "comfort", "probe_secret"])
        is_terminal = role == "terminal"

        scene_goal = f"{storylet.title}——{storylet.scene_text[:100]}"
        emotional_goal = _emotional_goal_for_role(role, storylet, chars, protagonist)

        public_cue = _pressure_cue(role, "public", storylet, chars)
        private_cue = _pressure_cue(role, "private", storylet, chars)

        segments.append(MappedSegment(
            segment_id=f"seg_{idx}_{role}",
            segment_role=role,
            source_storylet_id=storylet.storylet_id,
            focus_target_ids=focus_ids,
            rival_target_ids=rival_ids,
            allocated_secret_ids=secret_ids,
            is_terminal=is_terminal,
            allowed_move_families=moves,
            venue_id=storylet.venue_hint,
            scene_goal=scene_goal[:220],
            emotional_goal=emotional_goal[:220],
            move_priorities=moves[:4],
            public_pressure_cue=public_cue[:220],
            private_pressure_cue=private_cue[:220],
        ))

    return segments


def _emotional_goal_for_role(
    role: SegmentRoleId,
    storylet: Storylet,
    chars: dict[str, Any],
    protagonist: str,
) -> str:
    goals: dict[SegmentRoleId, str] = {
        "opening": "建立角色间的初始张力和好奇心",
        "misread": "制造误解和错位，让玩家基于不完整信息做出判断",
        "pressure": "升级压力，迫使角色做出有代价的选择",
        "reversal": "颠覆预期，重新定义角色关系和力量对比",
        "reveal": "揭示真相，让积累的秘密和线索汇聚成冲击",
        "terminal": "收束叙事，让玩家的选择产生不可逆的后果",
    }
    return goals.get(role, "推动叙事发展")


def _pressure_cue(
    role: SegmentRoleId,
    mode: str,
    storylet: Storylet,
    chars: dict[str, Any],
) -> str:
    if mode == "public":
        cues: dict[SegmentRoleId, str] = {
            "opening": "社交场合中的微妙试探和观察",
            "misread": "公开场合的误判引发连锁反应",
            "pressure": "舆论和公众目光加剧压力",
            "reversal": "公开场合的突然翻转震惊众人",
            "reveal": "真相在众目睽睽下曝光",
            "terminal": "最终决定在公众见证下做出",
        }
    else:
        cues = {
            "opening": "私下交流中透露不安的信号",
            "misread": "私密对话中的信息不对称",
            "pressure": "密室中的逼迫和要挟",
            "reversal": "私下的背叛和密谋浮出水面",
            "reveal": "最隐秘的真相在私下被揭开",
            "terminal": "一对一的最终对质和抉择",
        }
    return cues.get(role, "叙事推进")


_COMPILE_SYSTEM = """你是一个叙事片段编译器。根据世界配置、关系网和张力网，生成一组动态叙事片段(storylet)。

每个storylet是一个独立的叙事单元，有前置条件和效果。

返回JSON格式：
{
  "storylets": [
    {
      "storylet_id": "唯一标识符",
      "narrative_function": "从以下选择: hook/escalation/reversal/revelation/cost/resolution",
      "title": "片段标题",
      "scene_text": "场景描述文本(不超过500字)",
      "characters_involved": ["参与角色的character_id列表"],
      "venue_hint": "场景地点",
      "dramatic_weight": 0.0到1.0的戏剧权重,
      "cooldown_turns": 冷却回合数(0-6),
      "preconditions": {
        "required_secrets_known": ["需要已知的secret_id列表"],
        "required_relationships": ["需要的关系条件"],
        "min_tension_score": 最低张力阈值,
        "required_segment_roles": ["适用的segment_role列表"]
      },
      "effects": {
        "secrets_revealed": ["会揭露的secret_id列表"],
        "relationship_shifts": {"character_id": 关系变化值},
        "tension_delta": 张力变化(-1.0到1.0),
        "triggers_chain": "触发的秘密链secret_id或null"
      }
    }
  ]
}

要求：
1. 每种narrative_function至少生成2个storylet
2. 所有主要角色都要参与
3. storylet之间要有逻辑连贯性
4. dramatic_weight应随叙事进展递增
5. 确保秘密的揭露有合理的前置条件"""


def _parse_storylets_from_llm(raw: dict[str, Any], char_ids: set[str], secret_ids: set[str]) -> list[Storylet]:
    storylets_raw = raw.get("storylets", [])
    if not isinstance(storylets_raw, list):
        raise StoryletCompilerError("llm_bad_storylets", "expected storylets array")
    valid_functions: set[str] = {"hook", "escalation", "reversal", "revelation", "cost", "resolution"}
    storylets: list[Storylet] = []
    seen_ids: set[str] = set()
    for s in storylets_raw[:60]:
        sid = str(s.get("storylet_id", f"st_{len(storylets)}"))[:64]
        if sid in seen_ids:
            sid = f"{sid}_{len(storylets)}"
        seen_ids.add(sid)
        func = str(s.get("narrative_function", "hook"))
        if func not in valid_functions:
            func = "hook"
        involved = [str(c) for c in s.get("characters_involved", []) if str(c) in char_ids][:5]
        if not involved:
            continue
        pre_raw = s.get("preconditions", {}) or {}
        pre = StoryletCondition(
            required_secrets_known=[sid for sid in (pre_raw.get("required_secrets_known") or []) if sid in secret_ids][:3],
            required_relationships=[str(r)[:120] for r in (pre_raw.get("required_relationships") or [])][:3],
            min_tension_score=max(0.0, min(1.0, float(pre_raw.get("min_tension_score", 0.0)))),
        )
        eff_raw = s.get("effects", {}) or {}
        eff = StoryletEffect(
            secrets_revealed=[sid for sid in (eff_raw.get("secrets_revealed") or []) if sid in secret_ids][:3],
            relationship_shifts={
                k: max(-1.0, min(1.0, float(v)))
                for k, v in (eff_raw.get("relationship_shifts") or {}).items()
                if k in char_ids
            },
            tension_delta=max(-1.0, min(1.0, float(eff_raw.get("tension_delta", 0.0)))),
            triggers_chain=str(eff_raw["triggers_chain"])[:64] if eff_raw.get("triggers_chain") and str(eff_raw["triggers_chain"]) in secret_ids else None,
        )
        storylets.append(Storylet(
            storylet_id=sid,
            narrative_function=func,  # type: ignore[arg-type]
            title=str(s.get("title", "未命名"))[:120],
            scene_text=str(s.get("scene_text", "场景描述"))[:500],
            characters_involved=involved,
            venue_hint=str(s.get("venue_hint", "未知地点"))[:120],
            dramatic_weight=max(0.0, min(1.0, float(s.get("dramatic_weight", 0.5)))),
            cooldown_turns=max(0, min(6, int(s.get("cooldown_turns", 0)))),
            preconditions=pre,
            effects=eff,
        ))
    return storylets


def compile_storylet_pool(
    config: WorldConfiguration,
    web: TensionWeb,
    matrix: RelationshipMatrix,
    *,
    gateway: AuthorV3LLMGateway | None = None,
) -> StoryletPool:
    if gateway is None:
        storylets = _deterministic_storylets(config, web, matrix)
    else:
        storylets = _compile_live(config, web, matrix, gateway)
    return StoryletPool(
        storylets=storylets,
        function_counts=_count_functions(storylets),
    )


def _compile_live(
    config: WorldConfiguration,
    web: TensionWeb,
    matrix: RelationshipMatrix,
    gateway: AuthorV3LLMGateway,
) -> list[Storylet]:
    char_ids = {c.character_id for c in config.characters}
    secret_ids = {s.secret_id for s in web.secrets}
    char_summaries = [
        {
            "character_id": c.character_id,
            "display_name": c.display_name,
            "public_identity": c.public_identity,
            "worldly_desire": c.worldly_desire,
        }
        for c in config.characters
    ]
    secret_summaries = [
        {
            "secret_id": s.secret_id,
            "title": s.title,
            "holders": s.holders,
            "lethality_score": s.lethality_score,
            "chain_targets": s.chain_targets,
        }
        for s in web.secrets
    ]
    hook_summaries = [
        {"holder": h.holder_id, "target": h.target_id, "type": h.leverage_type}
        for h in web.hooks
    ]

    result = gateway.invoke_json(
        system_prompt=_COMPILE_SYSTEM,
        user_payload={
            "characters": char_summaries,
            "secrets": secret_summaries,
            "hooks": hook_summaries,
            "protagonist_id": config.protagonist_id,
            "setting": config.setting,
            "social_arena": config.social_arena,
            "slot_assignments": matrix.slot_assignments,
        },
        max_output_tokens=gateway.max_output_tokens_storylet_compiler,
        operation_name="author_v3_compile_storylets",
    )
    return _parse_storylets_from_llm(result.parsed, char_ids, secret_ids)
