from __future__ import annotations

import pytest

from rpg_backend.author.contracts import StoryShellId
from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.contracts import (
    ForgedCharacter,
    RelationshipEdge,
    RelationshipStance,
    WorldConfiguration,
    WorldSeed,
)
from rpg_backend.author_v3.plan_bridge import bridge_to_plan
from rpg_backend.author_v3.world_forge import (
    _WORLDLY_DESIRE_CONFLICT_ERROR,
    _WORLDLY_DESIRE_DIVERSITY_ERROR,
    _validate_world_config,
)
from rpg_backend.author_v3.workflow import run_author_v3_pipeline


@pytest.fixture(scope="module")
def base_pipeline_result() -> dict:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")


def _build_shell_plan(
    base_pipeline_result: dict,
    *,
    shell_id: StoryShellId,
    setting: str,
    social_arena: str,
    protagonist_public_identity: str,
    protagonist_hidden_need: str,
    raw_seed: str,
) -> CompiledPlayPlan:
    base_config = base_pipeline_result["world_config"]
    characters = [
        character.model_copy(
            update={
                "public_identity": protagonist_public_identity,
                "hidden_need": protagonist_hidden_need,
            }
        )
        if character.character_id == base_config.protagonist_id else character.model_copy()
        for character in base_config.characters
    ]
    config = base_config.model_copy(
        update={
            "seed": base_config.seed.model_copy(
                update={
                    "raw_seed": raw_seed,
                    "detected_shell": shell_id,
                    "setting_description": setting,
                }
            ),
            "setting": setting,
            "social_arena": social_arena,
            "story_shell_id": shell_id,
            "characters": characters,
        }
    )
    return bridge_to_plan(
        config,
        base_pipeline_result["relationship_matrix"],
        base_pipeline_result["tension_web"],
        base_pipeline_result["storylet_pool"],
        base_pipeline_result["mapped_segments"],
        base_pipeline_result["quality_report"],
    )


def _assert_roundtrip(plan: CompiledPlayPlan) -> CompiledPlayPlan:
    dumped = plan.model_dump(mode="json")
    reloaded = CompiledPlayPlan.model_validate(dumped)
    assert reloaded.template_id == plan.template_id
    assert reloaded.seed_fingerprint.secret_class == plan.seed_fingerprint.secret_class
    assert all(value is not None for value in reloaded.seed_fingerprint.model_dump().values())
    return reloaded


def _build_test_stance(label: str) -> RelationshipStance:
    return RelationshipStance(
        trust_level=0.5,
        dependency_level=0.5,
        hidden_dynamic=f"{label}暗线",
        tension_source=f"{label}旧账",
        power_asymmetry=0.0,
    )


def _build_minimal_world_config(shell_id: StoryShellId, desires: list[str]) -> WorldConfiguration:
    characters = [
        ForgedCharacter(
            character_id=f"char_{index}",
            display_name=f"角色{index}",
            gender="male" if index % 2 else "female",
            public_identity=f"公开身份{index}",
            hidden_need=f"隐藏需求{index}",
            worldly_desire=desire,
            fear=f"恐惧{index}",
            shame_trigger=f"羞耻点{index}",
            breaking_point=f"崩溃点{index}",
            speech_pattern=f"说话方式{index}",
            loyalty_bias="self" if index == 1 else "institution",
            route_eligible=index == 1,
        )
        for index, desire in enumerate(desires, start=1)
    ]
    edges = [
        RelationshipEdge(
            character_a_id="char_1",
            character_b_id="char_2",
            public_facade="表面同盟",
            hidden_truth="私下互相试探",
            tension_score=0.6,
            hooks=["char_1", "char_2"],
            stance_a_to_b=_build_test_stance("12A"),
            stance_b_to_a=_build_test_stance("12B"),
        ),
        RelationshipEdge(
            character_a_id="char_2",
            character_b_id="char_3",
            public_facade="公开合作",
            hidden_truth="暗中互相卡位",
            tension_score=0.65,
            hooks=["char_2", "char_3"],
            stance_a_to_b=_build_test_stance("23A"),
            stance_b_to_a=_build_test_stance("23B"),
        ),
        RelationshipEdge(
            character_a_id="char_3",
            character_b_id="char_4",
            public_facade="维持体面",
            hidden_truth="共同掩盖旧事",
            tension_score=0.7,
            hooks=["char_3", "char_4"],
            stance_a_to_b=_build_test_stance("34A"),
            stance_b_to_a=_build_test_stance("34B"),
        ),
        RelationshipEdge(
            character_a_id="char_4",
            character_b_id="char_1",
            public_facade="相互背书",
            hidden_truth="都在等待翻盘",
            tension_score=0.75,
            hooks=["char_4", "char_1"],
            stance_a_to_b=_build_test_stance("41A"),
            stance_b_to_a=_build_test_stance("41B"),
        ),
    ]
    return WorldConfiguration(
        seed=WorldSeed(
            raw_seed=f"{shell_id} seed",
            detected_shell=shell_id,
            setting_description=f"{shell_id} 场景",
            tone="高压",
            character_count=len(characters),
            theme_keywords=["秘密", "博弈"],
        ),
        setting=f"{shell_id} 场景",
        social_arena=f"{shell_id} 社交场",
        story_shell_id=shell_id,
        characters=characters,
        relationship_edges=edges,
        protagonist_id="char_1",
    )


def test_wealth_families_dispatches_to_wealth_template(base_pipeline_result: dict) -> None:
    plan = _build_shell_plan(
        base_pipeline_result,
        shell_id="wealth_families",
        setting="继承委员会与家宴并行推进的继承夜",
        social_arena="跨夜听证与家宴",
        protagonist_public_identity="被推上继承桌面的豪门继承人",
        protagonist_hidden_need="想查清私生证据并保住旧爱",
        raw_seed="继承委员会跨夜听证与家宴并行推进，联姻席位、私生证据和旧爱回潮反复换手，目标做成30到45分钟的超级旗舰局。",
    )

    assert plan.template_id == "wealth_private_heir_return"
    assert "wealth" in plan.template_id
    assert plan.seed_fingerprint.secret_class == "hidden_heir"
    assert plan.seed_fingerprint.play_length_preset == "30_45"
    _assert_roundtrip(plan)


def test_wealth_families_light_dispatches_to_engagement_template(base_pipeline_result: dict) -> None:
    plan = _build_shell_plan(
        base_pipeline_result,
        shell_id="wealth_families",
        setting="豪门订婚宴前夜的排位战",
        social_arena="订婚宴前夜",
        protagonist_public_identity="被联姻安排围住的豪门继承人",
        protagonist_hidden_need="想顶住婚约压力并保住旧爱",
        raw_seed="豪门订婚宴前夜的排位战里，未婚夫、旧爱和律师轮流加压，目标做成15到20分钟轻量长局并确保代价落地。",
    )

    assert plan.template_id == "wealth_engagement_sideswitch"
    assert plan.seed_fingerprint.arena_type == "engagement_banquet"
    assert plan.seed_fingerprint.relationship_geometry == "fiance_oldlove_lawyer"
    assert plan.seed_fingerprint.play_length_preset == "15_20"
    _assert_roundtrip(plan)


def test_entertainment_scandal_dispatches_to_entertainment_template(base_pipeline_result: dict) -> None:
    plan = _build_shell_plan(
        base_pipeline_result,
        shell_id="entertainment_scandal",
        setting="颁奖礼后台的热搜翻车夜",
        social_arena="颁奖礼后台",
        protagonist_public_identity="被热搜追着跑的行业操盘手",
        protagonist_hidden_need="想压住偷拍视频并保住代言",
        raw_seed="颁奖礼 热搜 顶流 经纪人 偷拍",
    )

    assert plan.template_id == "entertainment_awards_scandal"
    assert plan.template_id.startswith("entertainment_")
    assert plan.seed_fingerprint.secret_class == "scandal_video"
    _assert_roundtrip(plan)


def test_office_power_keeps_office_template(base_pipeline_result: dict) -> None:
    plan = _build_shell_plan(
        base_pipeline_result,
        shell_id="office_power",
        setting="并购终局拆成多会场长链路推进",
        social_arena="并购终局会场",
        protagonist_public_identity="被高层围猎的项目负责人",
        protagonist_hidden_need="想扛住并购清洗并保住站位",
        raw_seed="并购终局拆成多会场长链路推进，总裁、法务、董事与旧同盟轮流逼她让步，每次拒绝都触发更高层级公开后果，目标30到45分钟。",
    )

    assert plan.template_id == "office_merger_scapegoat"
    assert plan.template_id.startswith("office_")
    assert plan.seed_fingerprint.secret_class == "black_ledger"
    assert plan.seed_fingerprint.arena_type == "merger_close"
    assert plan.seed_fingerprint.relationship_geometry == "power_circle_oldally"
    assert plan.seed_fingerprint.play_length_preset == "30_45"
    _assert_roundtrip(plan)


def test_campus_romance_dispatches_to_campus_template(base_pipeline_result: dict) -> None:
    plan = _build_shell_plan(
        base_pipeline_result,
        shell_id="campus_romance",
        setting="校庆夜里响起的旧录音",
        social_arena="校庆舞台",
        protagonist_public_identity="奖学金竞争里的校园核心人物",
        protagonist_hidden_need="想守住前途并面对前任录音",
        raw_seed="校园 校庆 奖学金 前任 录音 评审",
    )

    assert plan.template_id == "campus_homecoming_recording"
    assert not plan.template_id.startswith("office_")
    assert plan.seed_fingerprint.secret_class == "old_recording"
    _assert_roundtrip(plan)


def test_urban_supernatural_dispatches_to_urban_template(base_pipeline_result: dict) -> None:
    plan = _build_shell_plan(
        base_pipeline_result,
        shell_id="urban_supernatural",
        setting="夜巡会所外的契约怪谈",
        social_arena="会所街口",
        protagonist_public_identity="被异能旧债追上的普通人",
        protagonist_hidden_need="想查清契约真相并守住正常生活",
        raw_seed="夜巡 契约 怪谈 异能 会所 旧债",
    )

    assert plan.template_id == "urban_supernatural_legacy_contract"
    assert not plan.template_id.startswith("office_")
    assert plan.seed_fingerprint.secret_class == "legacy_contract_secret"
    _assert_roundtrip(plan)


@pytest.mark.parametrize(
    ("shell_id", "setting", "social_arena", "protagonist_public_identity", "protagonist_hidden_need", "raw_seed", "expected_template_id"),
    [
        (
            "wealth_families",
            "继承委员会与家宴并行推进的继承夜",
            "跨夜听证与家宴",
            "被推上继承桌面的豪门继承人",
            "想查清私生证据并保住旧爱",
            "继承委员会跨夜听证与家宴并行推进，联姻席位、私生证据和旧爱回潮反复换手，目标做成30到45分钟的超级旗舰局。",
            "wealth_private_heir_return",
        ),
        (
            "office_power",
            "并购终局拆成多会场长链路推进",
            "并购终局会场",
            "被高层围猎的项目负责人",
            "想扛住并购清洗并保住站位",
            "并购终局拆成多会场长链路推进，总裁、法务、董事与旧同盟轮流逼她让步，每次拒绝都触发更高层级公开后果，目标30到45分钟。",
            "office_merger_scapegoat",
        ),
        (
            "entertainment_scandal",
            "颁奖礼后台的热搜翻车夜",
            "颁奖礼后台",
            "被热搜追着跑的行业操盘手",
            "想压住偷拍视频并保住代言",
            "颁奖礼 热搜 顶流 经纪人 偷拍",
            "entertainment_awards_scandal",
        ),
        (
            "campus_romance",
            "校庆夜里响起的旧录音",
            "校庆舞台",
            "奖学金竞争里的校园核心人物",
            "想守住前途并面对前任录音",
            "校园 校庆 奖学金 前任 录音 评审",
            "campus_homecoming_recording",
        ),
        (
            "urban_supernatural",
            "夜巡会所外的契约怪谈",
            "会所街口",
            "被异能旧债追上的普通人",
            "想查清契约真相并守住正常生活",
            "夜巡 契约 怪谈 异能 会所 旧债",
            "urban_supernatural_legacy_contract",
        ),
    ],
)
def test_each_shell_roundtrips_with_valid_seed_fingerprint(
    base_pipeline_result: dict,
    capsys: pytest.CaptureFixture[str],
    *,
    shell_id: StoryShellId,
    setting: str,
    social_arena: str,
    protagonist_public_identity: str,
    protagonist_hidden_need: str,
    raw_seed: str,
    expected_template_id: str,
) -> None:
    plan = _build_shell_plan(
        base_pipeline_result,
        shell_id=shell_id,
        setting=setting,
        social_arena=social_arena,
        protagonist_public_identity=protagonist_public_identity,
        protagonist_hidden_need=protagonist_hidden_need,
        raw_seed=raw_seed,
    )

    reloaded = _assert_roundtrip(plan)
    assert reloaded.template_id == expected_template_id
    assert reloaded.seed_fingerprint.public_shell_id == shell_id
    with capsys.disabled():
        print(
            f"{shell_id}: template_id={reloaded.template_id} "
            f"seed_fingerprint={reloaded.seed_fingerprint.model_dump(mode='json')}"
        )


@pytest.mark.parametrize(
    "shell_id",
    [
        "wealth_families",
        "office_power",
        "entertainment_scandal",
        "campus_romance",
        "urban_supernatural",
    ],
)
def test_validate_world_config_accepts_opposing_desires_for_each_shell(shell_id: StoryShellId) -> None:
    config = _build_minimal_world_config(shell_id, ["love", "control", "love", "money"])

    _validate_world_config(config)


def test_validate_world_config_rejects_all_unique_worldly_desires() -> None:
    config = _build_minimal_world_config(
        "wealth_families",
        ["love", "control", "money", "freedom"],
    )

    with pytest.raises(ValueError, match=_WORLDLY_DESIRE_CONFLICT_ERROR):
        _validate_world_config(config)


def test_validate_world_config_rejects_all_same_worldly_desire() -> None:
    config = _build_minimal_world_config(
        "wealth_families",
        ["money", "money", "money", "money"],
    )

    with pytest.raises(ValueError, match=_WORLDLY_DESIRE_DIVERSITY_ERROR):
        _validate_world_config(config)
