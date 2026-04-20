from __future__ import annotations

from collections import Counter, defaultdict

from rpg_backend.author_v2.product_package import RelationshipDramaV2Package

_TEMPTATION_MARKERS = ("选谁", "选边", "站谁", "护谁", "信谁", "逼谁", "表态", "扛雷", "出局", "失控前", "两难", "代价")
_PUBLIC_BOMB_MARKERS = ("当众", "公开", "直播", "镜头", "董事会", "家宴", "会所", "晚会", "发布会", "热搜")
_NO_RETURN_MARKERS = ("说破", "回不去", "不可逆", "失控", "翻车", "代价", "摊牌", "掉位", "失手", "切人", "先静", "落到场上")
_NO_RETURN_STYLE_MARKERS = (
    "style:public_drop:enabled",
    "style:bomb:public_drop",
    "style:cost:landed",
    "style:bomb:short_hard_drop",
    "style:choice:force_alignment",
    "style:control:force_public_settlement",
)
_MATERIAL_COST_MARKERS = ("体面", "位置", "名声", "前途", "退路", "关系", "婚约", "资源", "奖学金", "自由", "生活")
_ARENA_MARKERS = {
    "family_banquet": ("家宴",),
    "engagement_banquet": ("订婚宴",),
    "will_reading": ("遗嘱", "宣读"),
    "board_vote": ("董事会",),
    "merger_close": ("并购",),
    "launch_event": ("发布会",),
    "promotion_review": ("升职", "评审"),
    "awards_backstage": ("颁奖礼", "后台"),
    "livestream_room": ("直播", "镜头"),
    "homecoming_stage": ("校庆",),
    "mentor_review": ("导师", "评审"),
    "club_event": ("社团",),
    "night_clubfront": ("会所", "夜色"),
}
_SECRET_MARKERS = {
    "will_evidence": ("遗嘱", "顺位", "旧案证据"),
    "hidden_heir": ("私生", "身世"),
    "black_ledger": ("黑账", "账"),
    "contract_flip": ("合同",),
    "scandal_video": ("偷拍视频", "热搜", "黑料"),
    "old_recording": ("录音",),
    "legacy_contract_secret": ("契约",),
}
_COST_CLASS_MARKERS = {
    "marriage_face": ("婚约", "名分", "体面"),
    "inheritance_status": ("继承", "顺位", "体面"),
    "career_position": ("位置", "牌桌", "升职"),
    "career_reputation": ("前途", "风评", "退路"),
    "public_reputation": ("名声", "热搜", "代言"),
    "scholarship_future": ("奖学金", "前途", "名声"),
    "legacy_normal_life": ("自由", "生活", "退路"),
}
_BOMB_MARKERS = {
    "evidence_drop": ("甩", "摔", "证据"),
    "side_switch": ("倒戈", "站队"),
    "vote_reveal": ("表态", "落票", "投票", "董事会"),
    "launch_crash": ("发布会", "翻车"),
    "hotsearch_flip": ("热搜", "镜头", "翻车"),
    "recording_drop": ("录音", "放出来"),
    "legacy_contract_exposure": ("契约", "现实"),
}
_GEOMETRY_SLOT_FUNCTIONS = {
    "fiance_oldlove_lawyer": ("lead_interest", "wildcard", "secret_keeper"),
    "heir_oldlove_secret_keeper": ("lead_interest", "wildcard", "secret_keeper"),
    "boss_rival_legal": ("lead_interest", "rival_interest", "secret_keeper"),
    "power_circle_oldally": ("lead_interest", "rival_interest", "hidden_ally"),
    "idol_manager_ex": ("lead_interest", "hidden_ally", "wildcard"),
    "scholarship_ex_recording": ("lead_interest", "rival_interest", "secret_keeper"),
    "legacy_danger_ally": ("lead_interest", "hidden_ally", "secret_keeper"),
}
_SHELL_SURFACE_MARKERS = {
    "wealth_families": ("主桌", "顺位", "家宴", "名分", "继承"),
    "office_power": ("牌桌", "会议", "话语权", "背锅", "位置"),
    "entertainment_scandal": ("镜头", "热搜", "公关", "切割", "商务"),
    "campus_romance": ("评审", "名额", "社团", "站队", "同圈"),
    "urban_supernatural": ("夜色", "契约", "旧债", "异象", "失控"),
}
_PUBLIC_COST_VISIBILITY_MARKERS = ("公开代价", "体面", "位置", "话语权", "名声", "前途", "名额", "商业价值", "退路")
_RELATIONSHIP_BACKLASH_MARKERS = ("反噬", "翻脸", "切割", "记账", "报复", "孤立", "断线", "失控")


def evaluate_preview_promise_gate(package: RelationshipDramaV2Package) -> list[str]:
    blueprint = package.preview_blueprint
    failures: list[str] = []
    if len(blueprint.hook.strip()) < 18:
        failures.append("hook_too_flat")
    if not any(marker in blueprint.route_promise for marker in _TEMPTATION_MARKERS):
        failures.append("route_promise_temptation_weak")
    if not any(marker in blueprint.bomb_moment for marker in _PUBLIC_BOMB_MARKERS):
        failures.append("bomb_moment_publicity_weak")
    if not any(marker in blueprint.cost_of_truth for marker in _MATERIAL_COST_MARKERS):
        failures.append("cost_of_truth_materiality_weak")
    if len({member.danger_hook for member in package.compiled_play_plan.cast if member.is_route_target}) < min(
        2,
        len([member for member in package.compiled_play_plan.cast if member.is_route_target]),
    ):
        failures.append("route_targets_not_differentiated")
    return failures


def evaluate_seed_preservation_gate(package: RelationshipDramaV2Package) -> list[str]:
    fingerprint = package.preview_blueprint.seed_fingerprint
    blueprint = package.preview_blueprint
    failures: list[str] = []
    arena_markers = _ARENA_MARKERS.get(fingerprint.arena_type, ())
    if arena_markers and not any(marker in blueprint.social_arena or marker in blueprint.bomb_moment for marker in arena_markers):
        failures.append("arena_preserved")
    secret_markers = _SECRET_MARKERS.get(fingerprint.secret_class, ())
    if secret_markers and not any(marker in blueprint.taboo_secret or marker in blueprint.bomb_moment for marker in secret_markers):
        failures.append("secret_class_preserved")
    cost_markers = _COST_CLASS_MARKERS.get(fingerprint.cost_class, ())
    if cost_markers and not any(marker in blueprint.cost_of_truth for marker in cost_markers):
        failures.append("cost_class_preserved")
    bomb_markers = _BOMB_MARKERS.get(fingerprint.public_bomb_family, ())
    if bomb_markers and not any(marker in blueprint.bomb_moment for marker in bomb_markers):
        failures.append("bomb_family_preserved")
    required_slots = set(_GEOMETRY_SLOT_FUNCTIONS.get(fingerprint.relationship_geometry, ()))
    actual_slots = {member.slot_function for member in package.compiled_play_plan.cast}
    if required_slots and len(required_slots & actual_slots) < min(2, len(required_slots)):
        failures.append("relationship_geometry_preserved")
    return failures


def evaluate_sibling_divergence_gate(packages: list[RelationshipDramaV2Package]) -> dict[str, list[str]]:
    grouped: dict[tuple[str, str], list[RelationshipDramaV2Package]] = defaultdict(list)
    for package in packages:
        grouped[(package.compiled_play_plan.story_shell_id, package.compiled_play_plan.template_id)].append(package)
    flags: dict[str, list[str]] = {}
    for (_, _), sibling_packages in grouped.items():
        if len(sibling_packages) < 2:
            continue
        signature_counter: Counter[tuple[str, str, str, str, str]] = Counter()
        by_story: dict[str, tuple[str, str, str, str, str]] = {}
        for package in sibling_packages:
            fingerprint = package.preview_blueprint.seed_fingerprint
            signature = (
                ",".join(package.preview_blueprint.route_promise.split("，")[:1]),
                fingerprint.arena_type,
                fingerprint.secret_class,
                fingerprint.cost_class,
                fingerprint.public_bomb_family,
            )
            by_story[package.compiled_play_plan.story_id] = signature
            signature_counter[signature] += 1
        for story_id, signature in by_story.items():
            if signature_counter[signature] > 1:
                flags.setdefault(story_id, []).append("seed_collapse")
    return flags


def evaluate_segment_tension_gate(package: RelationshipDramaV2Package) -> list[str]:
    failures: list[str] = []
    for segment in package.compiled_play_plan.segments:
        lane_ids = [lane.lane_id for lane in segment.suggestion_lanes]
        if lane_ids != ["relationship", "side", "burst"]:
            failures.append(f"{segment.segment_id}:suggestion_lanes_incomplete")
        if segment.segment_role in {"reveal", "terminal"}:
            text = f"{segment.scene_goal} {segment.emotional_goal}"
            has_text_irreversible = any(marker in text for marker in _NO_RETURN_MARKERS)
            has_style_irreversible = any(
                cue in _NO_RETURN_STYLE_MARKERS
                for cue in segment.render_cues
            )
            if not (has_text_irreversible or has_style_irreversible):
                failures.append(f"{segment.segment_id}:irreversibility_weak")
    return failures


def evaluate_surface_signal_readability(package: RelationshipDramaV2Package) -> list[str]:
    plan = package.compiled_play_plan
    shell_markers = _SHELL_SURFACE_MARKERS.get(plan.story_shell_id, ())
    if not shell_markers:
        return []
    failures: list[str] = []
    visible_shell_hits: set[str] = set()
    has_public_cost_visibility = False
    has_relationship_backlash = False
    for segment in plan.segments:
        text = " ".join(
            [
                segment.scene_goal,
                segment.emotional_goal,
                segment.public_pressure_cue,
                segment.private_pressure_cue,
                segment.progression_rule_summary,
                " ".join(segment.render_cues),
            ]
        )
        segment_hits = {marker for marker in shell_markers if marker in text}
        if not segment_hits:
            failures.append(f"{segment.segment_id}:shell_surface_missing")
        visible_shell_hits.update(segment_hits)
        if any(marker in text for marker in _PUBLIC_COST_VISIBILITY_MARKERS):
            has_public_cost_visibility = True
        if any(marker in text for marker in _RELATIONSHIP_BACKLASH_MARKERS):
            has_relationship_backlash = True
    if len(visible_shell_hits) < 3:
        failures.append("surface_signal_triplet_missing")
    if not has_public_cost_visibility:
        failures.append("public_cost_visibility_missing")
    if not has_relationship_backlash:
        failures.append("relationship_backlash_missing")
    return failures


def evaluate_ending_payoff_gate(package: RelationshipDramaV2Package) -> list[str]:
    endings = {ending.ending_id for ending in package.compiled_play_plan.ending_matrix.endings}
    failures: list[str] = []
    route_target_ids = package.compiled_play_plan.route_target_ids
    for target_id in route_target_ids:
        if f"relationship_{target_id}" not in endings:
            failures.append(f"missing_relationship_{target_id}")
        if f"side_{target_id}" not in endings:
            failures.append(f"missing_side_{target_id}")
    for ending_id in ("burst_reckoning", "pyrrhic_control", "burned_alone"):
        if ending_id not in endings:
            failures.append(f"missing_{ending_id}")
    return failures
