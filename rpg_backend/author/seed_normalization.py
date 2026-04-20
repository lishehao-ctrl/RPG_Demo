from __future__ import annotations

from dataclasses import dataclass

from rpg_backend.author.contracts import NormalizedSeedPacket, StoryShellId
from rpg_backend.author.normalize import normalize_whitespace, trim_ellipsis


_SHELL_KEYWORDS: dict[StoryShellId, tuple[str, ...]] = {
    "wealth_families": (
        "豪门",
        "联姻",
        "继承",
        "遗嘱",
        "婚约",
        "家族",
        "晚宴",
        "继承人",
        "heir",
        "inheritance",
        "will",
        "engagement",
        "family",
        "gala",
        "estate",
    ),
    "entertainment_scandal": (
        "娱乐圈",
        "明星",
        "艺人",
        "经纪人",
        "热搜",
        "偷拍",
        "绯闻",
        "塌房",
        "演员",
        "歌手",
        "paparazzi",
        "celebrity",
        "scandal",
        "idol",
        "actor",
        "actress",
    ),
    "office_power": (
        "职场",
        "办公室",
        "总裁",
        "上司",
        "合伙人",
        "公司",
        "项目",
        "并购",
        "升职",
        "office",
        "boss",
        "executive",
        "firm",
        "company",
        "partner",
    ),
    "campus_romance": (
        "校园",
        "大学",
        "学长",
        "社团",
        "宿舍",
        "校庆",
        "学生会",
        "campus",
        "school",
        "college",
        "student",
        "dorm",
        "club",
    ),
    "urban_supernatural": (
        "都市异能",
        "异能",
        "灵异",
        "怪谈",
        "诅咒",
        "妖",
        "鬼",
        "夜行",
        "supernatural",
        "ghost",
        "curse",
        "occult",
        "power",
    ),
}

_DEFAULT_RELATIONSHIP_HOOK: dict[StoryShellId, str] = {
    "wealth_families": "一场联姻、继承和旧爱回归把主角同时卷进危险吸引与公开站队。",
    "entertainment_scandal": "一场绯闻、偷拍视频和资源争夺让关系、热搜与真心同时失控。",
    "office_power": "一段暧昧、一次站队和一场升职博弈让办公室关系开始失衡。",
    "campus_romance": "一次心动、一次误会和一场公开站队把青春关系推向修罗场。",
    "urban_supernatural": "一段危险羁绊和被压住的秘密让都市夜色里的关系不断反转。",
}

_DEFAULT_SECRET_HOOK: dict[StoryShellId, str] = {
    "wealth_families": "这场体面的关系背后藏着足以改写继承顺序的秘密。",
    "entertainment_scandal": "镜头之外的秘密一旦曝光，就会连带所有关系一起塌陷。",
    "office_power": "有人把真正的交易和情感动机藏在体面的职场规则后面。",
    "campus_romance": "真正的秘密不是谁喜欢谁，而是谁先把这段关系变成了局。",
    "urban_supernatural": "每一段靠近都在逼近一个不能被公开的真相。",
}

_DEFAULT_REWRITE_REASON: dict[StoryShellId, str] = {
    "wealth_families": "rewritten_to_wealth_families_shell",
    "entertainment_scandal": "rewritten_to_entertainment_scandal_shell",
    "office_power": "rewritten_to_office_power_shell",
    "campus_romance": "rewritten_to_campus_romance_shell",
    "urban_supernatural": "rewritten_to_urban_supernatural_shell",
}


@dataclass(frozen=True)
class RelationshipDramaShellDefaults:
    story_frame_strategy: str
    cast_strategy: str
    beat_plan_strategy: str
    primary_theme: str
    route_fantasy: str
    surface_signal_ids: tuple[str, ...]
    surface_signal_summary: str
    target_visibility_summary: str


_SHELL_DEFAULTS: dict[StoryShellId, RelationshipDramaShellDefaults] = {
    "wealth_families": RelationshipDramaShellDefaults(
        story_frame_strategy="legitimacy_story",
        cast_strategy="legitimacy_cast",
        beat_plan_strategy="conservative_direct_draft",
        primary_theme="legitimacy_crisis",
        route_fantasy="卷入联姻、继承与旧爱回归的豪门修罗场。",
        surface_signal_ids=("money", "status", "power_access", "public_marriage_optics"),
        surface_signal_summary="钱、继承顺位、婚约体面和家族地位会一直压在关系选择之上。",
        target_visibility_summary="每个关键对象都同时带着身份标签、家族位置和公开体面压力出场。",
    ),
    "entertainment_scandal": RelationshipDramaShellDefaults(
        story_frame_strategy="public_order_story",
        cast_strategy="public_order_cast",
        beat_plan_strategy="conservative_direct_draft",
        primary_theme="public_order_crisis",
        route_fantasy="在热搜、偷拍与绯闻发酵中站队、心动与反转。",
        surface_signal_ids=("fame", "public_image", "rumor_velocity", "scandal_risk"),
        surface_signal_summary="名声、热搜、偷拍和舆论反噬会持续扭曲每一段关系。",
        target_visibility_summary="关键对象都带着公众身份和被围观压力，任何靠近都可能被放大成热搜。",
    ),
    "office_power": RelationshipDramaShellDefaults(
        story_frame_strategy="generic_civic_story",
        cast_strategy="generic_civic_cast",
        beat_plan_strategy="conservative_direct_draft",
        primary_theme="generic_civic_crisis",
        route_fantasy="在权力、暧昧和背刺之间选边站队。",
        surface_signal_ids=("title_status", "promotion_leverage", "team_alignment", "internal_reputation"),
        surface_signal_summary="职位、升职筹码和办公室风评会不断改变关系里的上下位和风险。",
        target_visibility_summary="每个关键对象都带着职位、派系和可失去的利益，不只是情感对象。",
    ),
    "campus_romance": RelationshipDramaShellDefaults(
        story_frame_strategy="generic_civic_story",
        cast_strategy="generic_civic_cast",
        beat_plan_strategy="conservative_direct_draft",
        primary_theme="generic_civic_crisis",
        route_fantasy="在心动、误会与公开站队里推动一段校园关系失控。",
        surface_signal_ids=("social_visibility", "clique_status", "rumor_spread", "emotional_hierarchy"),
        surface_signal_summary="社交圈层、流言扩散和公开站队会让每次靠近都更像一次冒险。",
        target_visibility_summary="关键对象都处在社团、年级或校园舆论中心，不会只是安静恋爱对象。",
    ),
    "urban_supernatural": RelationshipDramaShellDefaults(
        story_frame_strategy="truth_record_story",
        cast_strategy="truth_record_cast",
        beat_plan_strategy="single_semantic_compile",
        primary_theme="truth_record_crisis",
        route_fantasy="在都市异能与危险秘密里推进关系反转和命运锁定。",
        surface_signal_ids=("forbidden_knowledge", "hidden_rank", "exposure_risk", "underworld_attention"),
        surface_signal_summary="禁忌知识、隐藏位阶和暴露风险会让每段关系天然带着危险感。",
        target_visibility_summary="关键对象都不只是情感目标，也各自背着不可公开的能力或世界位置。",
    ),
}


def relationship_drama_shell_defaults(shell: StoryShellId) -> RelationshipDramaShellDefaults:
    return _SHELL_DEFAULTS[shell]


def normalize_seed_packet(raw_seed: str) -> NormalizedSeedPacket:
    normalized = normalize_whitespace(raw_seed)
    lowered = normalized.casefold()
    scores = {
        shell: sum(1 for keyword in keywords if keyword.casefold() in lowered)
        for shell, keywords in _SHELL_KEYWORDS.items()
    }
    best_shell = max(scores, key=scores.get)
    best_score = int(scores.get(best_shell) or 0)
    if best_score >= 2:
        fit_mode = "direct_fit"
    elif best_score == 1:
        fit_mode = "soft_fit"
    else:
        fit_mode = "out_of_range"
        best_shell = "wealth_families"
    defaults = relationship_drama_shell_defaults(best_shell)
    rewritten_seed = trim_ellipsis(
        normalize_whitespace(
            f"{normalized}. Relationship hook: {_DEFAULT_RELATIONSHIP_HOOK[best_shell]} Secret hook: {_DEFAULT_SECRET_HOOK[best_shell]}"
        ),
        4000,
    )
    return NormalizedSeedPacket(
        accepted_shell=best_shell,
        fit_mode=fit_mode,
        relationship_hook=_DEFAULT_RELATIONSHIP_HOOK[best_shell],
        secret_hook=_DEFAULT_SECRET_HOOK[best_shell],
        surface_signal_ids=list(defaults.surface_signal_ids),
        surface_signal_summary=defaults.surface_signal_summary,
        target_visibility_summary=defaults.target_visibility_summary,
        rewritten_seed=rewritten_seed,
        rewrite_reason=_DEFAULT_REWRITE_REASON[best_shell] if fit_mode != "direct_fit" else "seed_direct_fit",
    )
