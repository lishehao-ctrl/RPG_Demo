from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from uuid import uuid4

from rpg_backend.author.contracts import RelationshipMoveFamily, StoryShellId
from rpg_backend.author_v2.contracts import (
    AcceptedBlueprint,
    ArcTemplateId,
    ArenaType,
    BeatDeltaKernel,
    BeatDeltaPack,
    BoundIPCastMember,
    CallbackCommitPolicyV2,
    CallbackPolicy,
    CallbackPolicyRule,
    CastSlotPlan,
    CausalContractPolicy,
    CausalContractRule,
    CompiledPlayPlan,
    CompiledSegment,
    CompiledToneExamplePack,
    ControlSignaturePolicyV8,
    CostEscalationLadderPolicyV8,
    CostIntensityProfile,
    CostNarrativeBindingPolicy,
    CostOwnershipMatrixV2,
    CostOwnershipPolicy,
    CostOwnershipRule,
    CostPrimaryDriverPolicyV7,
    CostReturnPolicy,
    CostRoutingMatrixPolicy,
    CostRoutingRule,
    CostVisibilityContract,
    CostClass,
    ConflictTemplateId,
    EndingMatrix,
    InvariantPolicy,
    NpcDramaProfile,
    NpcStrategicIntent,
    PlayLengthPresetId,
    PropagationPriorityBySegment,
    PropagationPriorityPolicy,
    ProtagonistIdentityClass,
    PublicBombFamily,
    QuestionArcPolicyV2,
    QuestionProgressPolicy,
    QuestionProgressPolicyV2,
    ReasonFamilyPriorityPolicy,
    RelationshipGeometryId,
    RoleDivergenceMatrix,
    RoleDivergenceMatrixV2,
    RouteEndingSpec,
    RoutePreferenceBias,
    SegmentContract,
    SegmentInterestPolicy,
    SegmentInterestPolicyItem,
    SegmentPlaybook,
    SegmentStyleProfile,
    SegmentSuggestionLane,
    SecretClass,
    SeedFingerprint,
    SeedFitMode,
    ShellPropagationEdgePolicy,
    ShellPropagationGraphPolicy,
    ShellSignalGraphV2,
    StakeAxisPriorityPolicy,
    StyleRegister,
    StyleRegisterSegmentRule,
    SupportingReasonPair,
    SupportingDivergencePolicy,
    TurnSemanticStrategyPack,
    UrbanAuthorBundle,
    UrbanPreviewBlueprint,
    UtilityWeightProfile,
    RoleFunctionLexiconPolicyV8,
    ToneBias,
)
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.author_v2.template_library import match_story_template
from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.quality_evaluator import QualityReport
from rpg_backend.author_v3.storylet_compiler import MappedSegment, StoryletPool
from rpg_backend.author_v3.tension_weaver import TensionWeb


@dataclass(frozen=True)
class _ShellDefaults:
    template_id: ConflictTemplateId
    fit_mode: SeedFitMode
    arena_type: ArenaType
    secret_class: SecretClass
    relationship_geometry: RelationshipGeometryId
    cost_class: CostClass
    public_bomb_family: PublicBombFamily
    play_length_preset: PlayLengthPresetId
    protagonist_identity_class: ProtagonistIdentityClass
    tone_bias: ToneBias
    route_preference_bias: RoutePreferenceBias


# Use "mixed" only where the current literal set does not imply a single clear route bias.
_SHELL_TO_TEMPLATE: dict[StoryShellId, _ShellDefaults] = {
    "wealth_families": _ShellDefaults(
        template_id="wealth_banquet_will_flip",
        fit_mode="direct_fit",
        arena_type="family_banquet",
        secret_class="will_evidence",
        relationship_geometry="fiance_oldlove_lawyer",
        cost_class="marriage_face",
        public_bomb_family="evidence_drop",
        play_length_preset="12_15",
        protagonist_identity_class="heiress_target",
        tone_bias="knife",
        route_preference_bias="relationship",
    ),
    "entertainment_scandal": _ShellDefaults(
        template_id="entertainment_awards_scandal",
        fit_mode="direct_fit",
        arena_type="awards_backstage",
        secret_class="scandal_video",
        relationship_geometry="idol_manager_ex",
        cost_class="public_reputation",
        public_bomb_family="hotsearch_flip",
        play_length_preset="12_15",
        protagonist_identity_class="industry_operator",
        tone_bias="melodramatic",
        route_preference_bias="burst",
    ),
    "office_power": _ShellDefaults(
        template_id="office_board_vote_blackledger",
        fit_mode="direct_fit",
        arena_type="board_vote",
        secret_class="black_ledger",
        relationship_geometry="boss_rival_legal",
        cost_class="career_reputation",
        public_bomb_family="vote_reveal",
        play_length_preset="12_15",
        protagonist_identity_class="project_lead",
        tone_bias="knife",
        route_preference_bias="mixed",
    ),
    "campus_romance": _ShellDefaults(
        template_id="campus_homecoming_recording",
        fit_mode="direct_fit",
        arena_type="homecoming_stage",
        secret_class="old_recording",
        relationship_geometry="scholarship_ex_recording",
        cost_class="scholarship_future",
        public_bomb_family="recording_drop",
        play_length_preset="12_15",
        protagonist_identity_class="campus_core",
        tone_bias="wistful",
        route_preference_bias="relationship",
    ),
    "urban_supernatural": _ShellDefaults(
        template_id="urban_supernatural_legacy_contract",
        fit_mode="direct_fit",
        arena_type="night_clubfront",
        secret_class="legacy_contract_secret",
        relationship_geometry="legacy_danger_ally",
        cost_class="legacy_normal_life",
        public_bomb_family="legacy_contract_exposure",
        play_length_preset="12_15",
        protagonist_identity_class="legacy_urban_outsider",
        tone_bias="cold",
        route_preference_bias="mixed",
    ),
}

_SHELL_KEYWORDS: dict[StoryShellId, tuple[str, ...]] = {
    "wealth_families": ("豪门", "联姻", "继承", "遗嘱", "婚约", "订婚", "未婚夫", "家宴", "继承人", "私生", "旧爱", "律师"),
    "office_power": ("董事会", "并购", "黑账", "上司", "法务", "发布会", "升职", "空降", "总裁"),
    "entertainment_scandal": ("娱乐圈", "热搜", "颁奖", "颁奖礼", "庆功夜", "彩排", "直播", "绯闻", "隐恋", "代言", "黑料", "顶流", "经纪人", "偷拍视频"),
    "campus_romance": ("校园", "校庆", "奖学金", "导师", "评审", "前任", "录音", "学生会"),
    "urban_supernatural": ("异能", "夜巡", "契约", "怪谈", "会所", "灵媒", "旧债"),
}


def _contains_any(seed: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in seed for keyword in keywords)


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


def _seed_text(
    config: WorldConfiguration,
    protagonist_public_identity: str,
    protagonist_hidden_need: str,
) -> str:
    return " ".join(
        part.strip()
        for part in (
            config.seed.raw_seed,
            config.setting,
            config.social_arena,
            protagonist_public_identity,
            protagonist_hidden_need,
        )
        if part and part.strip()
    )


def _infer_arena_type(seed: str, shell_id: StoryShellId, fallback: _ShellDefaults) -> ArenaType:
    if shell_id == "wealth_families":
        if "订婚" in seed:
            return "engagement_banquet"
        if "遗嘱" in seed:
            return "will_reading"
        return "family_banquet"
    if shell_id == "office_power":
        if "董事会" in seed:
            return "board_vote"
        if "发布会" in seed:
            return "launch_event"
        if "升职" in seed or "空降" in seed:
            return "promotion_review"
        if "并购" in seed:
            return "merger_close"
        return fallback.arena_type
    if shell_id == "entertainment_scandal":
        if "颁奖" in seed or "红毯" in seed or "奖项" in seed:
            return "awards_backstage"
        if "直播" in seed:
            return "livestream_room"
        if "综艺" in seed or "录制" in seed:
            return "variety_set"
        return fallback.arena_type
    if shell_id == "campus_romance":
        if "校庆" in seed:
            return "homecoming_stage"
        if "导师" in seed or "评审" in seed:
            return "mentor_review"
        if "社团" in seed:
            return "club_event"
        return fallback.arena_type
    return fallback.arena_type


def _infer_secret_class(seed: str, shell_id: StoryShellId, fallback: _ShellDefaults) -> SecretClass:
    if "遗嘱" in seed or "旧案证据" in seed:
        return "will_evidence"
    if "私生" in seed or "继承人" in seed:
        return "hidden_heir"
    if "黑账" in seed:
        return "black_ledger"
    if "合同" in seed:
        return "contract_flip"
    if "偷拍视频" in seed or "黑料" in seed or "热搜" in seed:
        return "scandal_video"
    if "录音" in seed:
        return "old_recording"
    if shell_id == "urban_supernatural":
        return "legacy_contract_secret"
    return fallback.secret_class


def _infer_relationship_geometry(seed: str, shell_id: StoryShellId, fallback: _ShellDefaults) -> RelationshipGeometryId:
    if shell_id == "wealth_families":
        if all(token in seed for token in ("未婚夫", "旧爱", "律师")):
            return "fiance_oldlove_lawyer"
        if "私生" in seed or "继承" in seed or "继承人" in seed:
            return "heir_oldlove_secret_keeper"
        return fallback.relationship_geometry
    if shell_id == "office_power":
        if all(token in seed for token in ("上司", "对手", "法务")):
            return "boss_rival_legal"
        return "power_circle_oldally"
    if shell_id == "entertainment_scandal":
        return "idol_manager_ex"
    if shell_id == "campus_romance":
        return "scholarship_ex_recording"
    return "legacy_danger_ally"


def _infer_cost_class(seed: str, shell_id: StoryShellId, fallback: _ShellDefaults) -> CostClass:
    if shell_id == "wealth_families":
        return "inheritance_status" if any(token in seed for token in ("继承", "遗嘱", "继承人")) else "marriage_face"
    if shell_id == "office_power":
        return "career_position" if "升职" in seed or "职位" in seed else "career_reputation"
    if shell_id == "entertainment_scandal":
        return "public_reputation"
    if shell_id == "campus_romance":
        return "scholarship_future"
    if shell_id == "urban_supernatural":
        return "legacy_normal_life"
    return fallback.cost_class


def _infer_public_bomb_family(secret_class: SecretClass, shell_id: StoryShellId, fallback: _ShellDefaults) -> PublicBombFamily:
    if shell_id == "office_power" and secret_class == "contract_flip":
        return "launch_crash"
    if shell_id == "office_power":
        return "vote_reveal"
    if shell_id == "entertainment_scandal":
        return "hotsearch_flip"
    if shell_id == "campus_romance":
        return "recording_drop"
    if shell_id == "urban_supernatural":
        return "legacy_contract_exposure"
    if shell_id == "wealth_families":
        return "evidence_drop"
    return fallback.public_bomb_family


def _infer_route_preference_bias(seed: str, fallback: _ShellDefaults) -> RoutePreferenceBias:
    if _contains_any(seed, ("站队", "表态", "背锅", "扛雷")):
        return "side"
    if _contains_any(seed, ("前任", "旧爱", "暧昧", "未婚夫")):
        return "relationship"
    if _contains_any(seed, ("放录音", "翻桌", "公开", "当众", "热搜")):
        return "burst"
    return fallback.route_preference_bias


def _resolve_shell_defaults(
    config: WorldConfiguration,
    protagonist_public_identity: str,
    protagonist_hidden_need: str,
) -> _ShellDefaults:
    fallback = _SHELL_TO_TEMPLATE[config.story_shell_id]
    seed = _seed_text(config, protagonist_public_identity, protagonist_hidden_need)
    play_length_preset = _infer_play_length_preset(seed)
    secret_class = _infer_secret_class(seed, config.story_shell_id, fallback)
    fingerprint = SeedFingerprint(
        public_shell_id=config.story_shell_id,
        fit_mode=fallback.fit_mode,
        arena_type=_infer_arena_type(seed, config.story_shell_id, fallback),
        secret_class=secret_class,
        relationship_geometry=_infer_relationship_geometry(seed, config.story_shell_id, fallback),
        cost_class=_infer_cost_class(seed, config.story_shell_id, fallback),
        public_bomb_family=_infer_public_bomb_family(secret_class, config.story_shell_id, fallback),
        play_length_preset=play_length_preset,
        protagonist_identity_class=fallback.protagonist_identity_class,
        tone_bias=fallback.tone_bias,
        route_preference_bias=_infer_route_preference_bias(seed, fallback),
        source_markers=_resolve_source_markers(
            config.story_shell_id,
            config.seed.raw_seed,
            config.setting,
            config.social_arena,
            protagonist_public_identity,
            protagonist_hidden_need,
        ),
    )
    template = match_story_template(fingerprint)
    return _ShellDefaults(
        template_id=template.template_id,
        fit_mode=fallback.fit_mode,
        arena_type=fingerprint.arena_type,
        secret_class=fingerprint.secret_class,
        relationship_geometry=fingerprint.relationship_geometry,
        cost_class=fingerprint.cost_class,
        public_bomb_family=fingerprint.public_bomb_family,
        play_length_preset=fingerprint.play_length_preset,
        protagonist_identity_class=fingerprint.protagonist_identity_class,
        tone_bias=fingerprint.tone_bias,
        route_preference_bias=fingerprint.route_preference_bias,
    )


def _resolve_source_markers(shell_id: StoryShellId, *texts: str) -> list[str]:
    haystack = " ".join(text for text in texts if text)
    return [keyword for keyword in _SHELL_KEYWORDS[shell_id] if keyword in haystack][:10]


def _build_cast_member(
    char: Any,
    slot_function: str,
    protagonist_id: str,
    relationship_summary: str,
) -> BoundIPCastMember:
    is_route = char.route_eligible
    return BoundIPCastMember(
        character_id=char.character_id,
        display_name=char.display_name,
        slot_id=f"slot_{char.character_id}",
        slot_function=slot_function,
        portrait_asset=f"portraits/urban/{char.character_id}.jpg",
        charisma_hook=char.public_identity[:180],
        danger_hook=char.hidden_need[:180],
        speech_pattern=char.speech_pattern[:180],
        gender=char.gender,
        public_role=char.public_identity[:120],
        public_mask=f"{char.display_name}维持着{char.public_identity}的形象"[:180],
        secret_pressure=char.hidden_need[:180],
        relationship_to_protagonist=relationship_summary[:180],
        shareable_labels=[char.worldly_desire, char.loyalty_bias],
        route_eligible=is_route,
        is_route_target=is_route and char.character_id != protagonist_id,
        selection_reason=f"v3世界锻造生成，欲望驱动：{char.worldly_desire}"[:220],
        drama_profile=NpcDramaProfile(
            character_id=char.character_id,
            public_role=char.public_identity[:120],
            archetype_label=f"{char.worldly_desire}驱动型"[:80],
            charisma_hook=char.public_identity[:180],
            danger_hook=char.hidden_need[:180],
            speech_pattern=char.speech_pattern[:180],
            public_mask=f"{char.display_name}维持着{char.public_identity}的形象"[:180],
            private_need=char.hidden_need[:180],
            status_need=f"追求{char.worldly_desire}"[:180],
            fear=char.fear[:180],
            shame_trigger=char.shame_trigger[:180],
            breaking_point=char.breaking_point[:180],
            loyalty_bias=char.loyalty_bias,
            secret_owner_ids=[],
            history_tags=[],
            line_they_wont_cross=char.breaking_point[:180],
        ),
        strategic_intent=NpcStrategicIntent(
            character_id=char.character_id,
            primary_stake="position",
            loss_trigger="public_humiliation",
            opportunism_target_ids=[],
            public_survival_mode="self_preserve",
            debt_memory_bias="scorekeeping",
            preferred_latent_kind="relationship_debt",
            sensitive_latent_kind="public_wave",
            delay_preference="quick_snap",
            regression_payoff="public_shame",
            protect_target_ids=[],
            sacrifice_target_ids=[],
        ),
    )


def _build_compiled_segment(
    seg: MappedSegment,
    *,
    source_storylet: dict[str, Any] | None = None,
) -> CompiledSegment:
    return CompiledSegment(
        segment_id=seg.segment_id,
        segment_role=seg.segment_role,
        source_storylet_id=seg.source_storylet_id,
        source_storylet=source_storylet,
        focus_target_ids=seg.focus_target_ids,
        rival_target_ids=seg.rival_target_ids,
        allocated_secret_ids=seg.allocated_secret_ids,
        is_terminal=seg.is_terminal,
        progress_required=2,
        segment_turn_floor=6,
        allowed_move_families=seg.allowed_move_families,
        venue_id=seg.venue_id,
        scene_goal=seg.scene_goal[:220],
        emotional_goal=seg.emotional_goal[:220],
        move_priorities=seg.move_priorities,
        public_pressure_cue=seg.public_pressure_cue[:220],
        private_pressure_cue=seg.private_pressure_cue[:220],
        progression_rule_summary=f"{seg.segment_role}阶段：推进叙事至下一个转折点"[:220],
        suggestion_lanes=[
            SegmentSuggestionLane(
                lane_id="relationship",
                label="关系推进",
                objective="深化角色间的关系和信任"[:220],
                candidate_move_families=["flirt", "comfort"],
                scene_frame_hint="private",
            ),
            SegmentSuggestionLane(
                lane_id="side",
                label="侧面探索",
                objective="探索隐藏线索和秘密"[:220],
                candidate_move_families=["probe_secret", "ally_with"],
                scene_frame_hint="semi_public",
            ),
            SegmentSuggestionLane(
                lane_id="burst",
                label="爆发对抗",
                objective="直面冲突，改变力量格局"[:220],
                candidate_move_families=["accuse", "public_reveal"],
                scene_frame_hint="public",
            ),
        ],
        render_cues=["角色表情变化", "环境氛围渲染", "对话节奏控制"],
    )


def _build_ending_matrix(
    config: WorldConfiguration,
    matrix: RelationshipMatrix,
    terminal_segment_id: str,
) -> EndingMatrix:
    protagonist = config.protagonist_id
    route_targets = [
        c.character_id for c in config.characters
        if c.route_eligible and c.character_id != protagonist
    ]
    endings: list[RouteEndingSpec] = []
    for rt in route_targets:
        endings.append(RouteEndingSpec(
            ending_id=f"ending_relationship_{rt}",
            label=f"与{rt}的关系结局",
            summary=f"通过深化与{rt}的关系达成的结局"[:220],
            lane_id="relationship",
            target_id=rt,
            min_affection=3,
            min_trust=2,
            terminal_segment_id=terminal_segment_id,
        ))
    endings.append(RouteEndingSpec(
        ending_id="ending_side_truth",
        label="真相大白",
        summary="揭露所有秘密后的结局"[:220],
        lane_id="side",
        min_secret_exposure=3,
        terminal_segment_id=terminal_segment_id,
    ))
    endings.append(RouteEndingSpec(
        ending_id="ending_burst_power",
        label="权力翻转",
        summary="通过公开对抗改变权力格局"[:220],
        lane_id="burst",
        min_scene_heat=4,
        min_public_events=3,
        terminal_segment_id=terminal_segment_id,
    ))
    endings.append(RouteEndingSpec(
        ending_id="ending_pyrrhic",
        label="惨胜",
        summary="付出巨大代价后的胜利"[:220],
        min_scene_heat=3,
        max_public_image=2,
        terminal_segment_id=terminal_segment_id,
    ))
    endings.append(RouteEndingSpec(
        ending_id="ending_burned",
        label="满盘皆输",
        summary="所有关系破裂的结局"[:220],
        max_secret_exposure=1,
        max_suspicion=5,
        terminal_segment_id=terminal_segment_id,
    ))
    while len(endings) < 4:
        endings.append(RouteEndingSpec(
            ending_id=f"ending_fallback_{len(endings)}",
            label="默认结局",
            summary="叙事自然收束"[:220],
            terminal_segment_id=terminal_segment_id,
        ))
    return EndingMatrix(endings=endings[:12])


def _default_shell_edge(shell_id: StoryShellId) -> ShellPropagationEdgePolicy:
    return ShellPropagationEdgePolicy(
        edge_id=f"edge_{shell_id}_default",
        from_node="秘密",
        to_node="关系",
        anchor_token="权力",
        signal_family="mixed",
    )


def _default_style_rule() -> StyleRegisterSegmentRule:
    return StyleRegisterSegmentRule(
        segment_role="opening",
        reason_families=["mixed"],
        signal_families=["mixed"],
        cost_families=["mixed"],
        cadence_order=["mixed"],
    )


def _build_default_cost_routing_rules() -> list[CostRoutingRule]:
    rule_specs = (
        ("flirt", "deferred_cost", "relationship_debt", True),
        ("probe_secret", "deferred_cost", "secret_pressure", True),
        ("comfort", "deferred_cost", "relationship_debt", True),
        ("deflect", "deferred_cost", None, False),
        ("accuse", "immediate_cost", None, False),
        ("ally_with", "deferred_cost", "relationship_debt", True),
        ("betray", "immediate_cost", None, False),
        ("public_reveal", "immediate_cost", None, False),
        ("private_confession", "deferred_cost", "relationship_debt", True),
        ("jealousy_trigger", "immediate_cost", None, False),
    )
    return [
        CostRoutingRule(
            rule_id=f"v3_default_{move_family}",
            move_family=move_family,
            route_kind=route_kind,
            deferred_kind=deferred_kind,
            enable_callback=enable_callback,
        )
        for move_family, route_kind, deferred_kind, enable_callback in rule_specs
    ]


def _default_callback_rule() -> CallbackPolicyRule:
    return CallbackPolicyRule(
        rule_id="default_callback",
        move_family="betray",
    )


def _callback_rule_from_template(
    template: CallbackPolicyRule,
    *,
    rule_id: str,
    move_family: RelationshipMoveFamily,
    due_turn_min_offset: int | None = None,
    due_turn_max_offset: int | None = None,
) -> CallbackPolicyRule:
    payload = template.model_dump()
    payload.update(
        rule_id=rule_id,
        move_family=move_family,
    )
    if due_turn_min_offset is not None:
        payload["due_turn_min_offset"] = due_turn_min_offset
    if due_turn_max_offset is not None:
        payload["due_turn_max_offset"] = due_turn_max_offset
    return CallbackPolicyRule(**payload)


def _default_callback_rules() -> list[CallbackPolicyRule]:
    template = _default_callback_rule()
    return [
        template,
        _callback_rule_from_template(
            template,
            rule_id="default_callback_flirt",
            move_family="flirt",
        ),
        _callback_rule_from_template(
            template,
            rule_id="default_callback_probe_secret",
            move_family="probe_secret",
            due_turn_min_offset=1,
            due_turn_max_offset=1,  # Secret callbacks should snap back quickly once the probing leaves exposed edges behind.
        ),
        _callback_rule_from_template(
            template,
            rule_id="default_callback_comfort",
            move_family="comfort",
        ),
        _callback_rule_from_template(
            template,
            rule_id="default_callback_ally_with",
            move_family="ally_with",
        ),
        _callback_rule_from_template(
            template,
            rule_id="default_callback_private_confession",
            move_family="private_confession",
        ),
    ]


def _default_cost_ownership_rule() -> CostOwnershipRule:
    return CostOwnershipRule(
        rule_id="default_ownership",
        move_family="accuse",
        owner_mode="target",
    )


def _default_causal_rule() -> CausalContractRule:
    return CausalContractRule(
        rule_id="default_causal",
        source_kind="callback",
        open_by_role="opening",
        resolve_by_role="terminal",
    )


def _build_semantic_strategy_pack(
    shell_id: StoryShellId,
    segments: list[CompiledSegment],
) -> TurnSemanticStrategyPack:
    seg_ids = {s.segment_id: s for s in segments}
    interest_items = {}
    for s in segments:
        interest_items[s.segment_id] = SegmentInterestPolicyItem(
            segment_id=s.segment_id,
            segment_role=s.segment_role,
            dominant_reason_family="mixed",
            reason_priority=["mixed"],
            stake_priority=["position"],
        )

    shell_edge = _default_shell_edge(shell_id)
    style_rule = _default_style_rule()

    return TurnSemanticStrategyPack(
        question_progress_policy=QuestionProgressPolicy(),
        question_progress_policy_v2=QuestionProgressPolicyV2(),
        question_arc_policy_v2=QuestionArcPolicyV2(),
        segment_interest_policy=SegmentInterestPolicy(
            by_segment_id=interest_items,
            default_reason_priority=["mixed"],
            default_stake_priority=["position"],
        ),
        role_divergence_matrix=RoleDivergenceMatrix(
            default_counter_reason_priority=["mixed"],
            default_crowd_reason_priority=["mixed"],
        ),
        role_divergence_matrix_v2=RoleDivergenceMatrixV2(),
        stake_axis_priority=StakeAxisPriorityPolicy(
            default_priority=["position"],
        ),
        reason_family_priority=ReasonFamilyPriorityPolicy(
            default_priority=["mixed"],
        ),
        supporting_divergence_policy=SupportingDivergencePolicy(
            key_segment_required_pairs=[
                SupportingReasonPair(counter_reason="mixed", crowd_reason="mixed"),
            ],
        ),
        cost_routing_matrix=CostRoutingMatrixPolicy(
            rules=_build_default_cost_routing_rules(),
        ),
        cost_ownership_policy=CostOwnershipPolicy(
            rules=[_default_cost_ownership_rule()],
        ),
        cost_ownership_matrix_v2=CostOwnershipMatrixV2(
            rules=[_default_cost_ownership_rule()],
        ),
        callback_policy=CallbackPolicy(
            rules=_default_callback_rules(),
        ),
        callback_commit_policy_v2=CallbackCommitPolicyV2(
            rules=_default_callback_rules(),
        ),
        cost_return_policy=CostReturnPolicy(),
        cost_narrative_binding_policy=CostNarrativeBindingPolicy(),
        cost_primary_driver_policy_v7=CostPrimaryDriverPolicyV7(),
        cost_escalation_ladder_policy_v8=CostEscalationLadderPolicyV8(),
        cost_visibility_contract=CostVisibilityContract(),
        control_signature_policy_v8=ControlSignaturePolicyV8(),
        role_function_lexicon_policy_v8=RoleFunctionLexiconPolicyV8(),
        utility_weight_profile=UtilityWeightProfile(),
        cost_intensity_profile=CostIntensityProfile(),
        shell_propagation_graph=ShellPropagationGraphPolicy(
            shell_id=shell_id,
            edges=[shell_edge],
        ),
        shell_signal_graph_v2=ShellSignalGraphV2(
            shell_id=shell_id,
            edges=[shell_edge],
        ),
        propagation_priority_policy=PropagationPriorityPolicy(shell_id=shell_id),
        propagation_priority_by_segment=PropagationPriorityBySegment(shell_id=shell_id),
        style_register=StyleRegister(
            default_rule=style_rule,
        ),
        invariant_policy=InvariantPolicy(),
        causal_contract_policy=CausalContractPolicy(
            rules=[_default_causal_rule()],
        ),
    )


def _build_delta_kernel(
    config: WorldConfiguration,
    cast: list[BoundIPCastMember],
    arc_template_id: ArcTemplateId,
    template_id: ConflictTemplateId,
) -> BeatDeltaKernel:
    protagonist = next(c for c in config.characters if c.character_id == config.protagonist_id)
    route_targets = [c.character_id for c in config.characters if c.route_eligible and c.character_id != config.protagonist_id]
    voice_axes = {
        m.character_id: f"{m.speech_pattern}；底层驱动是{m.drama_profile.status_need}"[:220]
        for m in cast
    }
    return BeatDeltaKernel(
        kernel_id=f"delta_kernel_{uuid4().hex[:12]}",
        story_shell_id=config.story_shell_id,
        template_id=template_id,
        route_promise_anchor=f"{protagonist.display_name}在权力斗争中寻找真相与盟友"[:220],
        bomb_moment_anchor="核心秘密曝光引发连锁反应"[:220],
        cost_of_truth_anchor="每个选择都有不可逆的代价"[:220],
        protagonist_need_anchor=protagonist.hidden_need[:180],
        route_target_ids=route_targets[:4],
        semantic_anchor_tokens=["权力", "秘密", "背叛", "选择"],
        character_voice_axes=voice_axes,
    )


def _build_initial_delta_pack(segments: list[CompiledSegment]) -> BeatDeltaPack:
    first_seg = segments[0] if segments else None
    return BeatDeltaPack(
        snapshot_id=f"initial_{uuid4().hex[:12]}",
        source="author_initial",
        beat_index=0,
        segment_id=first_seg.segment_id if first_seg else "seg_0_opening",
        segment_role=first_seg.segment_role if first_seg else "opening",
    )


def _relationship_summary_for(
    char_id: str,
    protagonist_id: str,
    config: WorldConfiguration,
) -> str:
    for e in config.relationship_edges:
        if e.character_a_id == protagonist_id and e.character_b_id == char_id:
            return e.public_facade
        if e.character_b_id == protagonist_id and e.character_a_id == char_id:
            return e.public_facade
    return "一般关系"


def bridge_to_plan(
    config: WorldConfiguration,
    matrix: RelationshipMatrix,
    web: TensionWeb,
    pool: StoryletPool,
    mapped_segments: list[MappedSegment],
    quality_report: QualityReport,
    *,
    arc_template_id: ArcTemplateId = "flagship_6",
) -> CompiledPlayPlan:
    protagonist = next(c for c in config.characters if c.character_id == config.protagonist_id)
    shell_defaults = _resolve_shell_defaults(
        config,
        protagonist.public_identity,
        protagonist.hidden_need,
    )
    source_markers = _resolve_source_markers(
        config.story_shell_id,
        config.seed.raw_seed,
        config.setting,
        config.social_arena,
        protagonist.public_identity,
        protagonist.hidden_need,
    )
    route_targets = [
        c.character_id for c in config.characters
        if c.route_eligible and c.character_id != config.protagonist_id
    ]

    cast: list[BoundIPCastMember] = []
    for char in config.characters:
        slot = matrix.slot_assignments.get(char.character_id, "wildcard")
        rel_summary = _relationship_summary_for(char.character_id, config.protagonist_id, config)
        cast.append(_build_cast_member(char, slot, config.protagonist_id, rel_summary))

    storylet_lookup = {
        storylet.storylet_id: storylet.model_dump(mode="json")
        for storylet in pool.storylets
    }
    compiled_segments = [
        _build_compiled_segment(
            seg,
            source_storylet=storylet_lookup.get(seg.source_storylet_id),
        )
        for seg in mapped_segments
    ]

    strategy_pack = _build_semantic_strategy_pack(config.story_shell_id, compiled_segments)
    delta_kernel = _build_delta_kernel(config, cast, arc_template_id, shell_defaults.template_id)
    initial_delta_pack = _build_initial_delta_pack(compiled_segments)
    terminal_seg_id = compiled_segments[-1].segment_id if compiled_segments else "seg_terminal"
    ending_matrix = _build_ending_matrix(config, matrix, terminal_seg_id)

    max_turns = len(compiled_segments) * 8

    return CompiledPlayPlan(
        story_id=f"v3_{uuid4().hex[:12]}",
        title=f"{config.setting}的故事"[:120],
        story_shell_id=config.story_shell_id,
        fit_mode=shell_defaults.fit_mode,
        template_id=shell_defaults.template_id,
        seed_fingerprint=SeedFingerprint(
            public_shell_id=config.story_shell_id,
            fit_mode=shell_defaults.fit_mode,
            arena_type=shell_defaults.arena_type,
            secret_class=shell_defaults.secret_class,
            relationship_geometry=shell_defaults.relationship_geometry,
            cost_class=shell_defaults.cost_class,
            public_bomb_family=shell_defaults.public_bomb_family,
            play_length_preset=shell_defaults.play_length_preset,
            protagonist_identity_class=shell_defaults.protagonist_identity_class,
            tone_bias=shell_defaults.tone_bias,
            route_preference_bias=shell_defaults.route_preference_bias,
            source_markers=source_markers,
        ),
        arc_template_id=arc_template_id,
        protagonist_public_identity=protagonist.public_identity[:120],
        protagonist_hidden_need=protagonist.hidden_need[:180],
        social_arena=config.social_arena[:120],
        play_length_preset=shell_defaults.play_length_preset,
        route_promise=f"{protagonist.display_name}在权力斗争中寻找真相与盟友"[:220],
        bomb_moment="核心秘密曝光引发连锁反应"[:220],
        cost_of_truth="每个选择都有不可逆的代价"[:220],
        cast=cast,
        route_target_ids=route_targets[:4] if len(route_targets) >= 2 else (route_targets + [cast[1].character_id])[:4],
        delta_pack_contract_version=5,
        delta_kernel=delta_kernel,
        initial_beat_delta_pack=initial_delta_pack,
        segments=compiled_segments,
        ending_matrix=ending_matrix,
        opening_narration=f"{protagonist.display_name}踏入{config.setting}，一切看似平静，暗流却已涌动。"[:320],
        max_turns=max(8, min(56, max_turns)),
        semantic_strategy_version=9,
        semantic_strategy_pack=strategy_pack,
        author_version="v3",
        storylet_pool=[s.model_dump(mode="json") for s in pool.storylets],
        organic_secrets=[s.model_dump() for s in web.secrets],
        hooks=[h.model_dump() for h in web.hooks],
        secret_chains=[c.model_dump() for c in web.chains],
    )


def package_from_v3_pipeline(
    *,
    preview_blueprint: UrbanPreviewBlueprint,
    accepted_blueprint: AcceptedBlueprint,
    plan: CompiledPlayPlan,
) -> RelationshipDramaV2Package:
    cast_slots = [
        CastSlotPlan(
            slot_id=m.slot_id,
            slot_function=m.slot_function,
            public_role_hint=m.public_role[:120],
            chemistry_hook=m.charisma_hook[:180],
            danger_hook=m.danger_hook[:180],
            secret_pressure=m.secret_pressure[:180],
            public_mask=m.public_mask[:180],
            route_eligible=m.route_eligible,
        )
        for m in plan.cast
    ]
    segment_contracts = [
        SegmentContract(
            segment_id=seg.segment_id,
            segment_role=seg.segment_role,
            focus_target_ids=seg.focus_target_ids,
            rival_target_ids=seg.rival_target_ids,
            allocated_secret_ids=seg.allocated_secret_ids,
            entry_contract=seg.scene_goal[:220],
            exit_contract=seg.emotional_goal[:220],
            handoff_contract=seg.progression_rule_summary[:220],
            is_terminal=seg.is_terminal,
            progress_required=seg.progress_required,
            segment_turn_floor=seg.segment_turn_floor,
            allowed_move_families=seg.allowed_move_families,
            venue_id=seg.venue_id[:120],
        )
        for seg in plan.segments
    ]
    segment_playbooks = [
        SegmentPlaybook(
            segment_id=seg.segment_id,
            scene_goal=seg.scene_goal[:220],
            emotional_goal=seg.emotional_goal[:220],
            move_priorities=seg.move_priorities,
            public_pressure_cue=seg.public_pressure_cue[:220],
            private_pressure_cue=seg.private_pressure_cue[:220],
            progression_rule_summary=seg.progression_rule_summary[:220],
            suggestion_lanes=seg.suggestion_lanes,
            render_cues=seg.render_cues,
        )
        for seg in plan.segments
    ]
    bundle = UrbanAuthorBundle(
        story_id=plan.story_id,
        title=plan.title,
        accepted_blueprint=accepted_blueprint,
        fit_mode=plan.fit_mode,
        template_id=plan.template_id,
        seed_fingerprint=plan.seed_fingerprint,
        arc_template_id=plan.arc_template_id,
        cast_slots=cast_slots,
        bound_cast=list(plan.cast),
        segment_contracts=segment_contracts,
        segment_playbooks=segment_playbooks,
        ending_matrix=plan.ending_matrix,
        opening_narration=plan.opening_narration[:320],
    )
    return RelationshipDramaV2Package(
        preview_blueprint=preview_blueprint,
        accepted_blueprint=accepted_blueprint,
        urban_bundle=bundle,
        compiled_play_plan=plan,
        quality_trace=[{"stage": "author_v3_quality_evaluator", "source": "author_v3", "outcome": "accepted"}],
    )
