from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rpg_backend.author.normalize import unique_preserve
from rpg_backend.author_v2.contracts import (
    BoundIPCastMember,
    CompiledPlayPlan,
    CompiledSegment,
    NpcDramaProfile,
    NpcStrategicIntent,
    ToneExampleLine,
    ToneSceneExample,
)
from rpg_backend.config import get_settings
from rpg_backend.play_v2.contracts import NpcMindState, NpcSceneFrame, UrbanTurnIntent, UrbanWorldState

PressureLevel = Literal["low", "rising", "high", "critical"]
WitnessFocus = Literal["contained", "watching", "locked"]
MaskState = Literal["holding", "cracking", "cornered", "broken"]
DominantImpulse = Literal["protect", "retaliate", "confess", "deflect", "control", "betray"]
RelationShift = Literal["leaning_closer", "pulling_back", "selling_out", "locking_side", "testing"]
FalloutVector = Literal["reputation", "alliance", "exposure", "irreversible_stance"]
CharacterTone = Literal["razor", "soft_hook", "smiling_blade", "measured", "slow_pressure", "restrained"]
SupportingReactionRole = Literal["counter", "crowd"]
ToneLayer = Literal["primary", "supporting", "fallout"]
DramaticMode = Literal["steady", "rising", "explosive", "aftermath"]


@dataclass(frozen=True)
class ScenePressureBeat:
    visibility_level: Literal["private", "semi_public", "public"]
    pressure_level: PressureLevel
    witness_focus: WitnessFocus
    witness_pressure: int
    scene_heat: int
    secret_exposure: int
    route_lock: int
    public_event_active: bool


@dataclass(frozen=True)
class NarrationRenderSeed:
    character_id: str
    turn_index: int
    segment_role: str
    move_family: str
    scene_frame: str


@dataclass(frozen=True)
class NpcReactionBeat:
    shell_id: str
    arena_name: str
    target_name: str
    target_id: str
    scene_pressure: ScenePressureBeat
    mask_state: MaskState
    dominant_impulse: DominantImpulse
    relation_shift: RelationShift
    fallout_vector: FalloutVector
    character_tone: CharacterTone
    public_role_hint: str
    charisma_hint: str
    danger_hint: str
    public_mask_hint: str
    status_need_hint: str
    cost_hint: str
    public_event_hint: str | None
    pain_hint: str | None
    no_return_hint: str | None
    shame_hint: str
    breaking_hint: str
    speech_texture_hint: str
    forbidden_raw_phrases: tuple[str, ...]
    public_posture: str


@dataclass(frozen=True)
class SupportingReactionBeat:
    role: SupportingReactionRole
    beat: NpcReactionBeat
    seed: NarrationRenderSeed
    cause_tags: tuple[str, ...] = ()
    strategic_intent: NpcStrategicIntent | None = None
    reason_family: str = "mixed"


@dataclass(frozen=True)
class ToneExampleStyleHints:
    dramatic_mode: DramaticMode = "steady"
    line_bucket_id: str | None = None
    primary_line_bucket_id: str | None = None
    supporting_line_bucket_id: str | None = None
    fallout_line_bucket_id: str | None = None
    scene_bucket_id: str | None = None
    primary_anchor_tokens: tuple[str, ...] = ()
    supporting_anchor_tokens: tuple[str, ...] = ()
    fallout_anchor_tokens: tuple[str, ...] = ()
    anchor_tokens: tuple[str, ...] = ()
    primary_reason_family: str = "mixed"
    counter_reason_family: str = "mixed"
    crowd_reason_family: str = "mixed"
    fallout_reason_family: str = "mixed"
    signal_family: str = "mixed"
    cost_family: str = "mixed"
    cadence: str = "mixed"
    force_main_clause_cost_subject: bool = False
    cost_subject_payer_name: str | None = None
    cost_subject_beneficiary_name: str | None = None
    cost_subject_focus: str | None = None
    counter_function_role: str = "wait_flip"
    crowd_function_role: str = "wait_flip"
    counter_action_verb: str | None = None
    crowd_action_verb: str | None = None
    counter_receiver_template: str | None = None
    crowd_receiver_template: str | None = None
    role_lexicon_hit: bool = False
    primary_clause_family_id: str | None = None
    counter_clause_family_id: str | None = None
    crowd_clause_family_id: str | None = None
    fallout_clause_family_id: str | None = None
    used_bucket_ids: tuple[str, ...] = ()
    used_clause_family_ids: tuple[str, ...] = ()
    style_case_ids: tuple[str, ...] = ()
    style_case_keywords: tuple[str, ...] = ()
    style_case_slot_constraints: tuple[str, ...] = ()
    blocked_stems: tuple[str, ...] = ()
    style_case_text_items: tuple[tuple[str, str], ...] = field(default_factory=tuple)


_CONTROLLED_ANCHOR_TOKENS = (
    "镜头",
    "公屏",
    "热搜",
    "切割",
    "版本",
    "台下",
    "评审",
    "名额",
    "社团",
    "熟人",
    "站队",
    "主桌",
    "顺位",
    "牌桌",
    "背锅",
    "录音",
    "风向",
)

_STYLE_CASE_BLOCKED_STEMS: tuple[str, ...] = (
    "代价会先咬位置和发言权",
    "代价会把关系账一起拉上台面",
    "代价是体面先碎",
    "谁都很难再装作没站边",
    "后面每一步都更难回撤",
    "这路节奏",
    "没有替任何人收尾",
    "盯着的不是情绪",
    "把压力继续往外推",
    "这拍已经不是试探",
    "这拍已经完成落锤",
    "她还在找能把真正疼点藏回去的缝",
)


def _pressure_level(state: UrbanWorldState) -> PressureLevel:
    if state.scene_heat >= 5 or state.secret_exposure >= 4:
        return "critical"
    if state.scene_heat >= 4 or state.secret_exposure >= 3:
        return "high"
    if state.scene_heat >= 2 or state.route_lock >= 2:
        return "rising"
    return "low"


def _witness_focus(state: UrbanWorldState, scene_frame: str) -> WitnessFocus:
    if scene_frame == "public" or state.witness_pressure >= 3:
        return "locked"
    if scene_frame == "semi_public" or state.witness_pressure >= 2:
        return "watching"
    return "contained"


def _mask_state(scene_frame: NpcSceneFrame, mind: NpcMindState) -> MaskState:
    if mind.mask_integrity <= 0:
        return "broken"
    if scene_frame.public_posture == "cornered":
        return "cornered"
    if scene_frame.public_posture in {"brittle", "performative"} or mind.mask_integrity <= 2:
        return "cracking"
    return "holding"


def _dominant_impulse(mind: NpcMindState, scene_frame: NpcSceneFrame) -> DominantImpulse:
    if scene_frame.scene_intent == "protect":
        return "protect"
    if scene_frame.scene_intent == "betray" or mind.betrayal_readiness >= 4:
        return "betray"
    if scene_frame.scene_intent == "confess" or mind.confession_readiness >= 4:
        return "confess"
    if scene_frame.scene_intent == "retaliate" or mind.jealousy >= 4:
        return "retaliate"
    if mind.control_need >= 4:
        return "control"
    return "deflect"


def _relation_shift(mind: NpcMindState, state: UrbanWorldState, target_id: str) -> RelationShift:
    if mind.commitment_target_id == state.current_route_target_id and state.current_route_target_id == target_id:
        return "locking_side"
    if mind.protectiveness >= 3 or mind.trust >= 2:
        return "leaning_closer"
    if mind.betrayal_readiness >= 4:
        return "selling_out"
    if mind.suspicion >= 3:
        return "pulling_back"
    return "testing"


def _fallout_vector(state: UrbanWorldState, scene_frame: str) -> FalloutVector:
    if state.secret_exposure >= 3:
        return "exposure"
    if scene_frame == "public" or bool(state.public_event_ids):
        return "reputation"
    if state.route_lock >= 3:
        return "irreversible_stance"
    return "alliance"


def _public_mask_hint(profile: NpcDramaProfile) -> str:
    text = profile.public_mask
    if any(token in text for token in ("体面", "稳", "规矩", "场面")):
        return "最会稳场的样子"
    if any(token in text for token in ("无辜", "干净", "清白")):
        return "装得像完全无辜"
    if any(token in text for token in ("掌控", "拿捏", "主导", "压")):
        return "把局面攥在手里的样子"
    if any(token in text for token in ("专业", "职业", "冷静")):
        return "看上去最职业冷静的那层壳"
    return "还能把场面撑住的样子"


def _public_role_hint(profile: NpcDramaProfile) -> str:
    text = profile.public_role
    if any(token in text for token in ("董事", "总监", "负责人", "经理", "总裁", "合伙人", "评审")):
        return "平时最像规矩本身的人"
    if any(token in text for token in ("艺人", "明星", "演员", "主持", "嘉宾", "偶像", "经纪")):
        return "平时最懂怎么在镜头前接住场面的人"
    if any(token in text for token in ("学长", "学姐", "主席", "部长", "评审", "优等", "门面")):
        return "平时最像不会出错的人"
    if any(token in text for token in ("少爷", "小姐", "千金", "继承", "夫人")):
        return "平时最会在场面上压住体面的人"
    return "平时最像能稳住场面的人"


def _charisma_hint(profile: NpcDramaProfile) -> str:
    text = f"{profile.charisma_hook} {profile.speech_pattern}"
    if any(token in text for token in ("笑", "半真半假", "漫不经心", "玩笑")):
        return "笑着就能把人带过去"
    if any(token in text for token in ("温柔", "轻", "留白", "半句")):
        return "轻轻一勾就能让人自己往前走"
    if any(token in text for token in ("冷静", "条理", "清楚", "稳")):
        return "光靠分寸就能压住场面"
    if any(token in text for token in ("锋利", "狠", "压迫", "刀")):
        return "一句话就能让人不敢接茬"
    return "一开口就会有人下意识跟着她的节奏走"


def _danger_hint(profile: NpcDramaProfile) -> str:
    text = profile.danger_hook
    if any(token in text for token in ("背刺", "翻脸", "切割", "甩锅", "卖")):
        return "翻脸时从不提前提醒"
    if any(token in text for token in ("控制", "拿捏", "规矩", "处分", "资源", "压")):
        return "最会把人按进她的规矩里"
    if any(token in text for token in ("热搜", "舆论", "镜头", "公众")):
        return "一旦失手就会把事情推到所有人都收不住"
    if any(token in text for token in ("名额", "前途", "顺位", "继承", "位置")):
        return "真翻脸时会直接冲着前途和位置下手"
    return "真翻脸时下手从来不会轻"


def _status_need_hint(profile: NpcDramaProfile) -> str:
    text = profile.status_need
    if any(token in text for token in ("位置", "升职", "发言权", "牌桌")):
        return "位置"
    if any(token in text for token in ("名分", "婚约", "家族", "顺位")):
        return "名分"
    if any(token in text for token in ("热搜", "名声", "事业", "镜头")):
        return "名声"
    if any(token in text for token in ("奖学金", "前途", "名额", "评审")):
        return "名额"
    return "局面主动权"


def _shame_hint(profile: NpcDramaProfile) -> str:
    text = profile.shame_trigger
    if "立场" in text:
        return "被当众看穿立场"
    if any(token in text for token in ("录音", "证据", "黑账", "合同")):
        return "最不想见光的东西被掀出来"
    if any(token in text for token in ("关系", "旧情", "隐恋", "婚约")):
        return "关系被人当众说破"
    if "镜头" in text:
        return "被镜头钉在原地"
    return "最丢脸的那一面被人看见"


def _breaking_hint(profile: NpcDramaProfile) -> str:
    text = profile.breaking_point
    if any(token in text for token in ("说出来", "开口", "承认", "坦白")):
        return "差一点就要自己说破"
    if any(token in text for token in ("翻脸", "失控", "掀桌")):
        return "快要直接翻脸"
    if any(token in text for token in ("护", "保")):
        return "本能地想先护住人"
    return "底线已经快绷断了"


def _speech_texture_hint(profile: NpcDramaProfile) -> str:
    text = profile.speech_pattern
    if any(token in text for token in ("字少", "锋利", "狠")):
        return "字句都带刀"
    if any(token in text for token in ("轻", "半句", "留白")):
        return "声线轻但句尾都留钩子"
    if any(token in text for token in ("玩笑", "半真半假")):
        return "明明在笑，话里却藏着刀"
    if any(token in text for token in ("条理", "落点", "清楚")):
        return "每句话都收得很稳"
    if any(token in text for token in ("慢", "稳", "压迫")):
        return "语速不快，压迫感却一点点往上压"
    return "嘴上还稳，但劲儿已经不对了"


def _character_tone(profile: NpcDramaProfile) -> CharacterTone:
    text = profile.speech_pattern
    if any(token in text for token in ("字少", "锋利", "狠")):
        return "razor"
    if any(token in text for token in ("轻", "半句", "留半句")):
        return "soft_hook"
    if any(token in text for token in ("玩笑", "半真半假")):
        return "smiling_blade"
    if any(token in text for token in ("条理", "落点", "清楚")):
        return "measured"
    if any(token in text for token in ("慢", "压迫", "先表态")):
        return "slow_pressure"
    return "restrained"


def build_scene_pressure_beat(state: UrbanWorldState, intent: UrbanTurnIntent) -> ScenePressureBeat:
    visibility_level = intent.scene_frame if intent.scene_frame in {"private", "semi_public", "public"} else state.scene_frame
    return ScenePressureBeat(
        visibility_level=visibility_level,  # type: ignore[arg-type]
        pressure_level=_pressure_level(state),
        witness_focus=_witness_focus(state, visibility_level),
        witness_pressure=state.witness_pressure,
        scene_heat=state.scene_heat,
        secret_exposure=state.secret_exposure,
        route_lock=state.route_lock,
        public_event_active=bool(state.public_event_ids),
    )


def _build_reaction_beat_for_character(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    character_id: str | None,
    scene_pressure: ScenePressureBeat,
    scene_frame: NpcSceneFrame | None,
    public_event_hint: str | None,
    pain_hint: str | None,
    no_return_hint: str | None,
) -> NpcReactionBeat:
    target_member = next((member for member in plan.cast if member.character_id == character_id), None)
    target_name = target_member.display_name if target_member is not None else "对方"
    mind = state.npc_mind_states.get(character_id or "")
    profile = target_member.drama_profile if target_member is not None else None
    if target_member is None or mind is None or profile is None or scene_frame is None:
        return NpcReactionBeat(
            shell_id=plan.story_shell_id,
            arena_name=plan.social_arena,
            target_name=target_name,
            target_id=character_id or "unknown",
            scene_pressure=scene_pressure,
            mask_state="holding",
            dominant_impulse="deflect",
            relation_shift="testing",
            fallout_vector=_fallout_vector(state, scene_pressure.visibility_level),
            character_tone="restrained",
            public_role_hint="平时最像能稳住场面的人",
            charisma_hint="一开口就会有人跟着她的节奏走",
            danger_hint="真翻脸时下手从来不会轻",
            public_mask_hint="还能稳住",
            status_need_hint="局面主动权",
            cost_hint="体面和退路",
            public_event_hint=public_event_hint,
            pain_hint=pain_hint,
            no_return_hint=no_return_hint,
            shame_hint="最丢脸的那一面被人看见",
            breaking_hint="底线已经快绷断了",
            speech_texture_hint="嘴上还稳，但劲儿已经不对了",
            forbidden_raw_phrases=(),
            public_posture="composed",
        )
    return NpcReactionBeat(
        shell_id=plan.story_shell_id,
        arena_name=plan.social_arena,
        target_name=target_name,
        target_id=target_member.character_id,
        scene_pressure=scene_pressure,
        mask_state=_mask_state(scene_frame, mind),
        dominant_impulse=_dominant_impulse(mind, scene_frame),
        relation_shift=_relation_shift(mind, state, target_member.character_id),
        fallout_vector=_fallout_vector(state, scene_pressure.visibility_level),
        character_tone=_character_tone(profile),
        public_role_hint=_public_role_hint(profile),
        charisma_hint=_charisma_hint(profile),
        danger_hint=_danger_hint(profile),
        public_mask_hint=_public_mask_hint(profile),
        status_need_hint=_status_need_hint(profile),
        cost_hint=_status_need_hint(profile),
        public_event_hint=public_event_hint,
        pain_hint=pain_hint,
        no_return_hint=no_return_hint,
        shame_hint=_shame_hint(profile),
        breaking_hint=_breaking_hint(profile),
        speech_texture_hint=_speech_texture_hint(profile),
        forbidden_raw_phrases=tuple(
            phrase
            for phrase in (
                profile.public_mask,
                profile.status_need,
                profile.shame_trigger,
                profile.breaking_point,
                profile.speech_pattern,
            )
            if phrase
        ),
        public_posture=scene_frame.public_posture,
    )


def build_npc_reaction_beat(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    scene_frame: NpcSceneFrame | None,
) -> NpcReactionBeat:
    scene_pressure = build_scene_pressure_beat(state, intent)
    def _is_expository(text: str | None) -> bool:
        if not text:
            return False
        stripped = text.strip()
        return stripped.startswith(("你一", "你这一下", "你护住", "你替", "你把", "这一步已经", "这一下已经")) or "等于把" in stripped

    event_hint_candidates = [
        next((record.text for record in reversed(state.last_turn_escalations) if record.kind in {"public_wave", "secret_pressure"}), None),
        state.last_turn_public_event_text,
        next((line for line in state.last_turn_consequences if not _is_expository(line)), None),
        state.last_turn_consequences[0] if state.last_turn_consequences else None,
    ]
    primary_hint = next((item for item in event_hint_candidates if item), None)
    no_return_hint = (
        next((record.text for record in reversed(state.last_turn_escalations) if record.kind in {"relationship_debt", "npc_action"}), None)
        or state.last_turn_no_return_text
    )
    return _build_reaction_beat_for_character(
        plan=plan,
        state=state,
        character_id=intent.target_id,
        scene_pressure=scene_pressure,
        scene_frame=scene_frame,
        public_event_hint=primary_hint,
        pain_hint=state.last_turn_pain_text,
        no_return_hint=no_return_hint,
    )


def build_render_seed(
    *,
    member: BoundIPCastMember | None,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    segment_role: str,
) -> NarrationRenderSeed:
    return NarrationRenderSeed(
        character_id=member.character_id if member is not None else "unknown",
        turn_index=state.turn_index,
        segment_role=segment_role,
        move_family=intent.move_family,
        scene_frame=intent.scene_frame,
    )


def _dramatic_mode(segment: CompiledSegment, state: UrbanWorldState) -> DramaticMode:
    pressure_peak = max(
        state.scene_heat,
        state.relationship_debt_pressure,
        state.public_wave_pressure,
        state.secret_pressure,
        state.npc_action_pressure,
    )
    if state.last_turn_escalations:
        if state.last_turn_escalations[0].kind in {"public_wave", "npc_action", "secret_pressure"}:
            return "explosive"
        return "aftermath"
    if segment.segment_role in {"reveal", "terminal"}:
        if pressure_peak >= 2 or state.secret_exposure >= 1 or state.public_wave_pressure >= 1:
            return "explosive"
        return "rising"
    if pressure_peak >= 4:
        return "rising"
    if segment.segment_role in {"reversal"} or pressure_peak >= 2:
        return "rising"
    return "steady"


def _line_pool_for_layer(segment: CompiledSegment, *, layer: ToneLayer) -> list[ToneExampleLine]:
    def _dedupe(items: list[ToneExampleLine]) -> list[ToneExampleLine]:
        output: list[ToneExampleLine] = []
        seen: set[str] = set()
        for item in items:
            if item.bucket_id in seen:
                continue
            seen.add(item.bucket_id)
            output.append(item)
        return output

    if layer == "primary":
        return _dedupe(
            list(segment.tone_example_pack.play_reaction_example_lines)
            + list(segment.tone_example_pack.author_example_lines)
            + list(segment.template_tone_example_lines)
        )
    if layer == "supporting":
        return _dedupe(
            list(segment.tone_example_pack.play_supporting_example_lines)
            + list(segment.tone_example_pack.play_reaction_example_lines)
            + list(segment.template_tone_example_lines)
        )
    return _dedupe(
        list(segment.tone_example_pack.play_chain_example_lines)
        + list(segment.tone_example_pack.play_debt_example_lines)
        + list(segment.tone_example_pack.play_reaction_example_lines)
        + list(segment.template_tone_example_lines)
    )


def _scene_pool_for_layer(segment: CompiledSegment, *, layer: ToneLayer) -> list[ToneSceneExample]:
    scenes = list(segment.tone_example_pack.author_example_scene) + list(segment.template_tone_scene_examples)
    if not scenes:
        return []
    deduped: list[ToneSceneExample] = []
    seen: set[str] = set()
    for item in scenes:
        if item.bucket_id in seen:
            continue
        seen.add(item.bucket_id)
        deduped.append(item)
    scenes = deduped
    filtered = [item for item in scenes if item.layer == layer]
    return filtered or scenes


def _target_band(layer: ToneLayer, mode: DramaticMode, *, explosive_boost: bool = False) -> DramaticMode:
    if explosive_boost and mode == "explosive":
        if layer == "fallout":
            return "aftermath"
        return "explosive"
    if layer == "supporting" and mode == "steady":
        return "rising"
    if layer == "fallout" and mode == "steady":
        return "rising"
    return mode


def _select_bucket(
    *,
    segment: CompiledSegment,
    state: UrbanWorldState,
    kind: Literal["line", "scene"],
    layer: ToneLayer,
    desired_mode: DramaticMode,
    explosive_boost: bool,
    recent: set[str],
    used_now: set[str],
) -> tuple[str | None, str]:
    if kind == "line":
        items = _line_pool_for_layer(segment, layer=layer)
    else:
        items = _scene_pool_for_layer(segment, layer=layer)
    if not items:
        return None, ""
    target_mode = _target_band(layer, desired_mode, explosive_boost=explosive_boost)
    band_items = [item for item in items if getattr(item, "dramatic_band", "steady") == target_mode]
    candidates = band_items or items
    slot_seed = sum(ord(char) for char in f"{kind}:{layer}:{segment.segment_id}")
    start = (state.turn_index + slot_seed) % len(candidates)
    for offset in range(len(candidates)):
        item = candidates[(start + offset) % len(candidates)]
        if item.bucket_id in recent or item.bucket_id in used_now:
            continue
        used_now.add(item.bucket_id)
        return item.bucket_id, item.text
    item = candidates[start]
    used_now.add(item.bucket_id)
    return item.bucket_id, item.text


def _extract_anchor_tokens(texts: list[str]) -> tuple[str, ...]:
    return tuple(token for token in _CONTROLLED_ANCHOR_TOKENS if any(token in text for text in texts))


def _style_case_keywords_from_text(text: str) -> tuple[str, ...]:
    keywords: list[str] = []
    if not text:
        return ()
    for token in _CONTROLLED_ANCHOR_TOKENS:
        if token in text and token not in keywords:
            keywords.append(token)
    for token in ("公开", "暗线", "切割", "稳场", "翻盘", "护短", "失位", "自保", "失控", "风向", "名额", "主桌", "评审"):
        if token in text and token not in keywords:
            keywords.append(token)
    return tuple(keywords[:8])


def _build_style_case_registry(
    *,
    segment: CompiledSegment,
    selected: tuple[tuple[ToneLayer, str | None, str], ...],
    reason_family: dict[ToneLayer, str],
    signal_family: str,
    cost_family: str,
    shell_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...]]:
    case_ids: list[str] = []
    case_keywords: list[str] = []
    slot_constraints: list[str] = []
    case_text_items: list[tuple[str, str]] = []
    for layer, bucket_id, text in selected:
        layer_case_id = f"{layer}:{bucket_id or 'fallback'}"
        case_ids.append(layer_case_id)
        if text:
            case_text_items.append((layer_case_id, text))
        for keyword in _style_case_keywords_from_text(text):
            if keyword not in case_keywords:
                case_keywords.append(keyword)
        slot_constraints.extend(
            [
                f"shell:{shell_id}",
                f"segment_role:{segment.segment_role}",
                f"layer:{layer}",
                f"reason_family:{reason_family.get(layer, 'mixed')}",
                f"signal_family:{signal_family}",
                f"cost_family:{cost_family}",
            ]
        )
    deduped_constraints = tuple(unique_preserve([item for item in slot_constraints if item]))[:18]
    return (
        tuple(unique_preserve(case_ids)),
        tuple(case_keywords[:10]),
        deduped_constraints,
        tuple(case_text_items[:8]),
    )


def _infer_shell_id_from_anchor_tokens(tokens: list[str]) -> str:
    token_set = set(tokens)
    if token_set & {"镜头", "热搜", "公屏", "公关", "切割"}:
        return "entertainment_scandal"
    if token_set & {"台下", "评审", "名额", "社团", "熟人", "站队"}:
        return "campus_romance"
    if token_set & {"主桌", "顺位", "家宴", "继承"}:
        return "wealth_families"
    if token_set & {"会议桌", "席位", "口风", "背锅"}:
        return "office_power"
    return "unknown"


def _pick_clause_family(
    *,
    values: list[str],
    turn_index: int,
    slot_name: str,
    recent: set[str],
    used_now: set[str],
) -> str:
    cleaned = [item for item in values if isinstance(item, str) and item.strip()]
    if not cleaned:
        return "mixed"
    slot_seed = sum(ord(char) for char in f"{slot_name}:{len(cleaned)}")
    start = (turn_index + slot_seed) % len(cleaned)
    for offset in range(len(cleaned)):
        value = cleaned[(start + offset) % len(cleaned)]
        if value in recent or value in used_now:
            continue
        used_now.add(value)
        return value
    value = cleaned[start]
    used_now.add(value)
    return value


def build_tone_example_style_hints(segment: CompiledSegment, state: UrbanWorldState) -> ToneExampleStyleHints:
    mode = _dramatic_mode(segment, state)
    recent = set(state.recent_example_bucket_ids[:3])
    used_now: set[str] = set()
    explosive_boost = bool(getattr(segment.segment_style_profile, "explosive_boost", False))
    primary_bucket_id, primary_text = _select_bucket(
        segment=segment,
        state=state,
        kind="line",
        layer="primary",
        desired_mode=mode,
        explosive_boost=explosive_boost,
        recent=recent,
        used_now=used_now,
    )
    supporting_bucket_id, supporting_text = _select_bucket(
        segment=segment,
        state=state,
        kind="line",
        layer="supporting",
        desired_mode=mode,
        explosive_boost=explosive_boost,
        recent=recent,
        used_now=used_now,
    )
    fallout_bucket_id, fallout_text = _select_bucket(
        segment=segment,
        state=state,
        kind="line",
        layer="fallout",
        desired_mode=mode,
        explosive_boost=explosive_boost,
        recent=recent,
        used_now=used_now,
    )
    scene_bucket_id, scene_text = _select_bucket(
        segment=segment,
        state=state,
        kind="scene",
        layer="fallout",
        desired_mode=mode,
        explosive_boost=explosive_boost,
        recent=recent,
        used_now=used_now,
    )
    used = tuple(
        unique_preserve(
            [item for item in (primary_bucket_id, supporting_bucket_id, fallout_bucket_id, scene_bucket_id) if item]
        )
    )
    primary_tokens = _extract_anchor_tokens([primary_text])
    supporting_tokens = _extract_anchor_tokens([supporting_text])
    fallout_tokens = _extract_anchor_tokens([fallout_text, scene_text])
    merged_tokens = _extract_anchor_tokens([primary_text, supporting_text, fallout_text, scene_text])
    profile = segment.segment_style_profile
    role_reason_fallback = {
        "opening": ["opportunity_window", "self_preserve", "loss_position"],
        "misread": ["opportunity_window", "self_preserve", "loss_position"],
        "pressure": ["self_preserve", "loss_position", "old_debt"],
        "reversal": ["loss_position", "old_debt", "opportunity_window"],
        "reveal": ["loss_position", "old_debt", "self_preserve", "opportunity_window"],
        "terminal": ["old_debt", "loss_position", "self_preserve", "opportunity_window"],
    }
    reason_pool = unique_preserve(
        [*list(profile.reason_families or []), *(role_reason_fallback.get(segment.segment_role, [])), "mixed"]
    )[:4]
    signal_pool = unique_preserve([*list(profile.signal_families or []), "mixed"])[:4]
    cost_pool = unique_preserve([*list(profile.cost_families or []), "mixed"])[:4]
    cadence_pool = unique_preserve([*list(profile.cadence_order or []), "mixed"])[:4]
    recent_clause = {
        item.split(":")[-1]
        for item in state.recent_clause_family_ids[:3]
        if isinstance(item, str) and item
    }
    used_clause: set[str] = set()
    primary_reason = _pick_clause_family(
        values=reason_pool,
        turn_index=state.turn_index,
        slot_name="primary_reason",
        recent=recent_clause,
        used_now=used_clause,
    )
    counter_reason = _pick_clause_family(
        values=reason_pool,
        turn_index=state.turn_index,
        slot_name="counter_reason",
        recent=recent_clause,
        used_now=used_clause,
    )
    crowd_candidates = [value for value in reason_pool if value != counter_reason] or reason_pool
    crowd_reason = _pick_clause_family(
        values=crowd_candidates,
        turn_index=state.turn_index,
        slot_name="crowd_reason",
        recent=recent_clause,
        used_now=used_clause,
    )
    fallout_reason = _pick_clause_family(
        values=reason_pool,
        turn_index=state.turn_index,
        slot_name="fallout_reason",
        recent=recent_clause,
        used_now=used_clause,
    )
    signal_family = _pick_clause_family(
        values=signal_pool,
        turn_index=state.turn_index,
        slot_name="signal_family",
        recent=recent_clause,
        used_now=used_clause,
    )
    cost_family = _pick_clause_family(
        values=cost_pool,
        turn_index=state.turn_index,
        slot_name="cost_family",
        recent=recent_clause,
        used_now=used_clause,
    )
    cadence = _pick_clause_family(
        values=cadence_pool,
        turn_index=state.turn_index,
        slot_name="cadence",
        recent=recent_clause,
        used_now=used_clause,
    )
    key_segment = segment.segment_role in {"reveal", "terminal"}
    if key_segment:
        non_mixed_reason = [value for value in reason_pool if value != "mixed"]
        if non_mixed_reason:
            if primary_reason == "mixed":
                primary_reason = non_mixed_reason[0]
            if counter_reason == "mixed":
                counter_reason = next((value for value in non_mixed_reason if value != primary_reason), non_mixed_reason[0])
            if crowd_reason == "mixed":
                crowd_reason = next(
                    (
                        value
                        for value in non_mixed_reason
                        if value not in {primary_reason, counter_reason}
                    ),
                    non_mixed_reason[0],
                )
            if fallout_reason == "mixed":
                fallout_reason = next((value for value in reversed(non_mixed_reason) if value != crowd_reason), non_mixed_reason[-1])

        non_mixed_signal = [value for value in signal_pool if value != "mixed"]
        if non_mixed_signal:
            preferred_signal: str | None = None
            shell_anchor_tokens = set(profile.shell_anchor_tokens)
            if shell_anchor_tokens & {"镜头", "热搜", "公屏", "切割", "版本"}:
                preferred_signal = "public_wave"
            elif shell_anchor_tokens & {"台下", "评审", "名额", "社团", "熟人", "站队"}:
                preferred_signal = "peer_spread"
            if preferred_signal in non_mixed_signal:
                signal_family = preferred_signal
            elif signal_family == "mixed":
                signal_family = non_mixed_signal[0]
    clause_ids = unique_preserve(
        [
            f"reason:primary:{primary_reason}",
            f"reason:counter:{counter_reason}",
            f"reason:crowd:{crowd_reason}",
            f"reason:fallout:{fallout_reason}",
            f"signal:{signal_family}",
            f"cost:{cost_family}",
            f"cadence:{cadence}",
        ]
    )
    inferred_shell_id = _infer_shell_id_from_anchor_tokens(list(profile.shell_anchor_tokens))
    style_case_ids, style_case_keywords, style_case_slot_constraints, style_case_text_items = _build_style_case_registry(
        segment=segment,
        selected=(
            ("primary", primary_bucket_id, primary_text),
            ("supporting", supporting_bucket_id, supporting_text),
            ("fallout", fallout_bucket_id, fallout_text or scene_text),
        ),
        reason_family={
            "primary": primary_reason,
            "supporting": counter_reason,
            "fallout": fallout_reason,
        },
        signal_family=signal_family,
        cost_family=cost_family,
        shell_id=inferred_shell_id,
    )
    return ToneExampleStyleHints(
        dramatic_mode=mode,
        line_bucket_id=primary_bucket_id,
        primary_line_bucket_id=primary_bucket_id,
        supporting_line_bucket_id=supporting_bucket_id,
        fallout_line_bucket_id=fallout_bucket_id,
        scene_bucket_id=scene_bucket_id,
        primary_anchor_tokens=primary_tokens,
        supporting_anchor_tokens=supporting_tokens,
        fallout_anchor_tokens=fallout_tokens,
        anchor_tokens=merged_tokens,
        primary_reason_family=primary_reason,
        counter_reason_family=counter_reason,
        crowd_reason_family=crowd_reason,
        fallout_reason_family=fallout_reason,
        signal_family=signal_family,
        cost_family=cost_family,
        cadence=cadence,
        primary_clause_family_id=f"reason:primary:{primary_reason}",
        counter_clause_family_id=f"reason:counter:{counter_reason}",
        crowd_clause_family_id=f"reason:crowd:{crowd_reason}",
        fallout_clause_family_id=f"reason:fallout:{fallout_reason}",
        used_bucket_ids=used,
        used_clause_family_ids=tuple(clause_ids),
        style_case_ids=style_case_ids,
        style_case_keywords=style_case_keywords,
        style_case_slot_constraints=style_case_slot_constraints,
        blocked_stems=_STYLE_CASE_BLOCKED_STEMS,
        style_case_text_items=style_case_text_items,
    )


def _stake_score(cause_tags: tuple[str, ...]) -> int:
    score = 0
    if "debt_due" in cause_tags:
        score += 5
    if "covering_self" in cause_tags or "cutting_others" in cause_tags:
        score += 4
    if "camera_pressure" in cause_tags or "campus_spread" in cause_tags:
        score += 3
    if "saw_player_side" in cause_tags or "was_cut_out" in cause_tags or "forced_alignment" in cause_tags:
        score += 3
    if "kept_score" in cause_tags or "owes_debt" in cause_tags:
        score += 2
    return score


def _latent_pressure_score(mind: NpcMindState, cause_tags: tuple[str, ...]) -> int:
    score = mind.pressure_load + max(mind.tension - 1, 0)
    if "latent_pressure_high" in cause_tags:
        score += 3
    if "debt_due" in cause_tags:
        score += 2
    if "public_hit" in cause_tags:
        score += 1
    return score


def _intent_score(intent: NpcStrategicIntent | None, cause_tags: tuple[str, ...], *, target_id: str | None) -> int:
    if intent is None:
        return 0
    score = 0
    if "intent_loss_triggered" in cause_tags:
        score += 5
    if intent.public_survival_mode == "self_preserve" and any(tag in cause_tags for tag in ("covering_self", "public_hit", "interrupt_touched")):
        score += 4
    if intent.public_survival_mode == "cut_off" and any(tag in cause_tags for tag in ("cutting_others", "was_cut_out", "sacrifice_window")):
        score += 4
    if intent.public_survival_mode == "claim_narrative" and any(tag in cause_tags for tag in ("camera_pressure", "covering_self")):
        score += 4
    if intent.public_survival_mode == "align_early" and any(tag in cause_tags for tag in ("forced_alignment", "saw_player_side")):
        score += 4
    if intent.debt_memory_bias in {"scorekeeping", "late_payback"} and any(tag in cause_tags for tag in ("debt_due", "kept_score", "owes_debt")):
        score += 4
    if target_id is not None and target_id in set(intent.opportunism_target_ids) and any(tag in cause_tags for tag in ("opportunity_window", "public_hit", "at_center_of_event")):
        score += 3
    if target_id is not None and target_id in set(intent.protect_target_ids) and "protective_stake" in cause_tags:
        score += 2
    if target_id is not None and target_id in set(intent.sacrifice_target_ids) and "sacrifice_window" in cause_tags:
        score += 3
    return score


def _shell_role_bias(
    *,
    shell_id: str,
    role: SupportingReactionRole,
    beat: NpcReactionBeat,
    mind: NpcMindState,
    cause_tags: tuple[str, ...],
) -> int:
    if shell_id == "campus_romance":
        if role == "counter":
            bias = int(beat.relation_shift in {"pulling_back", "selling_out", "testing"}) + int("intent_loss_triggered" in cause_tags)
            return min(bias + int(mind.suspicion >= 3), 3)
        bias = int(mind.suspicion >= 3) + int(beat.public_posture == "composed")
        return min(bias + int("campus_spread" in cause_tags), 3)
    if shell_id == "entertainment_scandal":
        if role == "counter":
            bias = int(beat.character_tone in {"smiling_blade", "measured", "slow_pressure"}) + int("camera_pressure" in cause_tags)
            return min(bias + int(mind.control_need >= 3), 3)
        bias = int(beat.public_posture in {"performative", "composed"}) + int("camera_pressure" in cause_tags)
        return min(bias + int(mind.control_need >= 3), 3)
    return 0


def _supporting_reason_family(
    *,
    intent: NpcStrategicIntent | None,
    cause_tags: tuple[str, ...],
    utility_delta: int,
) -> str:
    if any(tag in cause_tags for tag in ("sacrifice_window", "forced_alignment", "blame_shift")):
        return "blame_shift"
    if any(tag in cause_tags for tag in ("debt_due", "kept_score", "owes_debt")):
        return "old_debt"
    if utility_delta <= -2:
        if intent is not None and intent.public_survival_mode in {"self_preserve", "cut_off", "claim_narrative"}:
            return "self_preserve"
        return "loss_position"
    if utility_delta >= 2:
        return "opportunity_window"
    if any(tag in cause_tags for tag in ("covering_self",)):
        return "self_preserve"
    return "mixed"


def _reason_priority_bonus(reason_family: str, priority: list[str]) -> int:
    if not priority:
        return 0
    try:
        idx = priority.index(reason_family)
    except ValueError:
        return 0
    return max(0, 3 - idx)


def _reason_function_role(reason_family: str) -> str:
    if reason_family in {"loss_position", "blame_shift"}:
        return "strike"
    if reason_family == "self_preserve":
        return "self_preserve"
    if reason_family == "old_debt":
        return "debt_play"
    if reason_family == "opportunity_window":
        return "wait_flip"
    return "wait_flip"


def _supporting_counter_score(
    plan: CompiledPlayPlan,
    beat: NpcReactionBeat,
    mind: NpcMindState,
    intent: NpcStrategicIntent | None,
    cause_tags: tuple[str, ...],
    utility_delta: int,
    target_id: str | None,
    reason_family: str,
    reason_priority: list[str],
) -> int:
    weights = plan.semantic_strategy_pack.utility_weight_profile
    intent_hit = _intent_score(intent, cause_tags, target_id=target_id)
    stake_hit = _stake_score(cause_tags)
    latent_pressure = _latent_pressure_score(mind, cause_tags)
    utility_hit = abs(utility_delta) + (2 if utility_delta < 0 else 1 if utility_delta > 0 else 0)
    role_diversity = 0
    if beat.dominant_impulse in {"retaliate", "betray", "control"}:
        role_diversity += 2
    if beat.relation_shift in {"selling_out", "pulling_back"}:
        role_diversity += 2
    if beat.public_posture in {"performative", "cornered"}:
        role_diversity += 1
    score = (
        intent_hit * weights.intent_hit_weight
        + stake_hit * weights.stake_hit_weight
        + latent_pressure * weights.latent_pressure_weight
        + role_diversity * weights.role_diversity_weight
        + utility_hit * weights.utility_delta_weight
    )
    score += _reason_priority_bonus(reason_family, reason_priority)
    shell_bias = _shell_role_bias(shell_id=plan.story_shell_id, role="counter", beat=beat, mind=mind, cause_tags=cause_tags)
    score += min(shell_bias * weights.shell_bias_weight, weights.shell_bias_cap)
    return score


def _supporting_crowd_score(
    plan: CompiledPlayPlan,
    beat: NpcReactionBeat,
    mind: NpcMindState,
    intent: NpcStrategicIntent | None,
    cause_tags: tuple[str, ...],
    utility_delta: int,
    target_id: str | None,
    reason_family: str,
    reason_priority: list[str],
) -> int:
    weights = plan.semantic_strategy_pack.utility_weight_profile
    intent_hit = _intent_score(intent, cause_tags, target_id=target_id)
    stake_hit = _stake_score(cause_tags)
    latent_pressure = _latent_pressure_score(mind, cause_tags)
    utility_hit = abs(utility_delta) + (1 if utility_delta < 0 else 0)
    role_diversity = 0
    if beat.character_tone in {"measured", "smiling_blade", "slow_pressure"}:
        role_diversity += 2
    if beat.public_posture in {"composed", "performative"}:
        role_diversity += 2
    if beat.relation_shift in {"testing", "locking_side"}:
        role_diversity += 1
    score = (
        intent_hit * weights.intent_hit_weight
        + stake_hit * weights.stake_hit_weight
        + latent_pressure * weights.latent_pressure_weight
        + role_diversity * weights.role_diversity_weight
        + utility_hit * weights.utility_delta_weight
    )
    score += _reason_priority_bonus(reason_family, reason_priority)
    shell_bias = _shell_role_bias(shell_id=plan.story_shell_id, role="crowd", beat=beat, mind=mind, cause_tags=cause_tags)
    score += min(shell_bias * weights.shell_bias_weight, weights.shell_bias_cap)
    return score


def build_supporting_reaction_beats(
    *,
    plan: CompiledPlayPlan,
    state: UrbanWorldState,
    intent: UrbanTurnIntent,
    segment_id: str | None,
    segment_role: str,
    scene_frames_by_id: dict[str, NpcSceneFrame],
) -> list[SupportingReactionBeat]:
    settings = get_settings()
    use_divergence_v2 = bool(settings.play_v2_policy_role_divergence_v2_enabled)
    scene_pressure = build_scene_pressure_beat(state, intent)
    segment_interest = plan.semantic_strategy_pack.segment_interest_policy
    segment_interest_item = segment_interest.by_segment_id.get(segment_id or "")
    divergence = plan.semantic_strategy_pack.supporting_divergence_policy
    divergence_v2 = (
        plan.semantic_strategy_pack.role_divergence_matrix_v2.by_segment_id.get(segment_id or "")
        if use_divergence_v2
        else None
    )
    counter_reason_priority = list(divergence.counter_reason_priority_by_segment_role.get(segment_role, []))
    crowd_reason_priority = list(divergence.crowd_reason_priority_by_segment_role.get(segment_role, []))
    if segment_interest_item is not None:
        counter_reason_priority = unique_preserve([*segment_interest_item.reason_priority, *counter_reason_priority])[:4]
        crowd_reason_priority = unique_preserve([*counter_reason_priority, *crowd_reason_priority])[:4]
    else:
        counter_reason_priority = unique_preserve([*counter_reason_priority, *segment_interest.default_reason_priority])[:4]
        crowd_reason_priority = unique_preserve([*crowd_reason_priority, *segment_interest.default_reason_priority])[:4]
    candidates: list[
        tuple[
            str,
            BoundIPCastMember,
            NpcReactionBeat,
            NpcMindState,
            NarrationRenderSeed,
            tuple[str, ...],
            int,
            str,
        ]
    ] = []
    for character_id in state.active_character_ids:
        if character_id == intent.target_id:
            continue
        member = next((item for item in plan.cast if item.character_id == character_id), None)
        mind = state.npc_mind_states.get(character_id)
        scene_frame = scene_frames_by_id.get(character_id)
        if member is None or mind is None or scene_frame is None:
            continue
        beat = _build_reaction_beat_for_character(
            plan=plan,
            state=state,
            character_id=character_id,
            scene_pressure=scene_pressure,
            scene_frame=scene_frame,
            public_event_hint=None,
            pain_hint=None,
            no_return_hint=None,
        )
        seed = build_render_seed(
            member=member,
            state=state,
            intent=intent,
            segment_role=segment_role,
        )
        cause_tags = tuple(state.last_turn_reaction_causes.get(character_id, []))
        utility_delta = int(state.last_turn_utility_delta_by_character.get(character_id, 0))
        reason_family = _supporting_reason_family(
            intent=member.strategic_intent,
            cause_tags=cause_tags,
            utility_delta=utility_delta,
        )
        candidates.append((character_id, member, beat, mind, seed, cause_tags, utility_delta, reason_family))
    if not candidates:
        return []

    def _counter_score(item) -> int:  # noqa: ANN001
        return _supporting_counter_score(
            plan,
            item[2],
            item[3],
            item[1].strategic_intent,
            item[5],
            utility_delta=item[6],
            target_id=intent.target_id,
            reason_family=item[7],
            reason_priority=counter_reason_priority,
        )

    def _crowd_score(item) -> int:  # noqa: ANN001
        return _supporting_crowd_score(
            plan,
            item[2],
            item[3],
            item[1].strategic_intent,
            item[5],
            utility_delta=item[6],
            target_id=intent.target_id,
            reason_family=item[7],
            reason_priority=crowd_reason_priority,
        )

    counter_choice = max(
        candidates,
        key=lambda item: (_counter_score(item), item[0]),
    )
    remaining = [item for item in candidates if item[0] != counter_choice[0]]
    crowd_choice = None
    if remaining:
        crowd_choice = max(
            remaining,
            key=lambda item: (_crowd_score(item), item[0]),
        )
    if crowd_choice is not None and divergence.require_reason_family_split and crowd_choice[7] == counter_choice[7]:
        split_candidates = [item for item in remaining if item[7] != counter_choice[7]]
        if split_candidates:
            crowd_choice = max(split_candidates, key=lambda item: (_crowd_score(item), item[0]))
    if crowd_choice is not None and divergence_v2 is not None:
        counter_fn = _reason_function_role(counter_choice[7])
        crowd_fn = _reason_function_role(crowd_choice[7])
        required_functions = set(divergence_v2.required_functions)
        min_distinct = max(1, int(divergence_v2.min_distinct_functions))
        distinct_functions = {counter_fn, crowd_fn}
        required_hits = len(distinct_functions & required_functions) if required_functions else len(distinct_functions)
        needs_reselect = (
            (divergence_v2.require_counter_crowd_reason_split and crowd_choice[7] == counter_choice[7])
            or len(distinct_functions) < min(2, min_distinct)
            or required_hits < min(2, min_distinct)
        )
        if needs_reselect:
            alt_candidates = [item for item in remaining if item[0] != counter_choice[0]]
            if alt_candidates:
                def _div_v2_score(item) -> tuple[int, int, str]:  # noqa: ANN001
                    fn = _reason_function_role(item[7])
                    function_bonus = 2 if fn in required_functions else 0
                    split_bonus = 1 if fn != counter_fn else 0
                    return (_crowd_score(item) + function_bonus + split_bonus, function_bonus + split_bonus, item[0])

                candidate = max(alt_candidates, key=_div_v2_score)
                if _reason_function_role(candidate[7]) != counter_fn or candidate[7] != counter_choice[7]:
                    crowd_choice = candidate
    key_segment_roles = set(divergence.key_segment_roles)
    if crowd_choice is not None and segment_role in key_segment_roles and divergence.key_segment_required_pairs:
        current_pair = (counter_choice[7], crowd_choice[7])
        required_pairs = {(pair.counter_reason, pair.crowd_reason) for pair in divergence.key_segment_required_pairs}
        if current_pair not in required_pairs:
            best_pair = None
            best_score = None
            for counter_reason, crowd_reason in required_pairs:
                counter_candidates = [item for item in candidates if item[7] == counter_reason]
                crowd_candidates = [item for item in candidates if item[7] == crowd_reason]
                if not counter_candidates or not crowd_candidates:
                    continue
                for counter_item in counter_candidates:
                    for crowd_item in crowd_candidates:
                        if counter_item[0] == crowd_item[0]:
                            continue
                        combo_score = _counter_score(counter_item) + _crowd_score(crowd_item)
                        if best_pair is None or combo_score > int(best_score or 0):
                            best_pair = (counter_item, crowd_item)
                            best_score = combo_score
            if best_pair is not None:
                counter_choice, crowd_choice = best_pair
    output = [
        SupportingReactionBeat(
            role="counter",
            beat=counter_choice[2],
            seed=counter_choice[4],
            cause_tags=counter_choice[5],
            strategic_intent=counter_choice[1].strategic_intent,
            reason_family=counter_choice[7],
        ),
    ]
    if crowd_choice is not None:
        output.append(
            SupportingReactionBeat(
                role="crowd",
                beat=crowd_choice[2],
                seed=crowd_choice[4],
                cause_tags=crowd_choice[5],
                strategic_intent=crowd_choice[1].strategic_intent,
                reason_family=crowd_choice[7],
            )
        )
    return output
