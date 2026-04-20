from __future__ import annotations

from pathlib import Path

from rpg_backend.author.contracts import (
    AffordanceEffectProfile,
    AffordanceWeight,
    AxisDefinition,
    BeatSpec,
    CastMember,
    ConditionBlock,
    EndingItem,
    EndingRule,
    StoryFunction,
    TruthItem,
)
from rpg_backend.config import Settings
from rpg_backend.play.contracts import PlayPlan, PlayProtagonist, PlayTurnRequest
from rpg_backend.play.service import PlaySessionService
from rpg_backend.play.storage import SQLitePlaySessionStorage


def _relationship_plan() -> PlayPlan:
    protagonist = PlayProtagonist(
        title="落入豪门风暴的新主角",
        mandate="先在这场联姻与继承战里保住自己。",
        identity_summary="你突然被卷进豪门晚宴、旧爱回归和偷拍视频的三重失控。",
        role_label="公关顾问",
        core_desire="查清联姻背后的真实交易，同时决定自己到底要站谁。",
        hidden_risk="你手里握着一段能毁掉所有人的偷拍视频。",
    )
    cast = [
        CastMember(
            npc_id="gu_chengye",
            name="顾承野",
            role="危险未婚夫",
            agenda="稳住联姻和继承权，不惜牺牲所有人的体面。",
            red_line="任何人都不能公开动摇他的继承位置。",
            pressure_signature="越被逼到角落，越会用体面掩饰控制欲。",
        ),
        CastMember(
            npc_id="lin_man",
            name="林蔓",
            role="前任白月光",
            agenda="把当年的真相翻出来，逼所有人重新站队。",
            red_line="绝不接受自己被写成可替代的过去。",
            pressure_signature="她越冷静，场面越危险。",
        ),
        CastMember(
            npc_id="xu_zhiyao",
            name="许知遥",
            role="家族律师",
            agenda="守住遗嘱和证据链，但从不把全部底牌亮出来。",
            red_line="任何人都不能越过她私下处理文件。",
            pressure_signature="她总在最晚的时候递出最致命的一页。",
        ),
    ]
    beats = [
        BeatSpec(
            beat_id="beat_hook",
            title="订婚宴开场",
            goal="让关系在宴会开始时就失衡。",
            return_hooks=["今晚所有人都在看谁先失态。"],
                affordances=[AffordanceWeight(tag="build_trust", weight=2), AffordanceWeight(tag="reveal_truth", weight=2)],
            phase="hook",
            scene_goal="建立主角与顾承野之间的危险吸引力。",
            emotional_goal="让暧昧和提防同时出现。",
            required_heat=2,
            focus_character_ids=["gu_chengye"],
            preferred_move_families=["flirt", "probe_secret", "comfort"],
            fallback_scene_prompt="晚宴灯光很亮，但每个人都在等第一句失控的话。",
        ),
        BeatSpec(
            beat_id="beat_pressure",
            title="旧爱回归",
            goal="让主角必须在旧爱和未婚夫之间站队。",
            return_hooks=["前任一出现，所有人都开始重新演戏。"],
                affordances=[AffordanceWeight(tag="build_trust", weight=2), AffordanceWeight(tag="reveal_truth", weight=2)],
            phase="pressure",
            scene_goal="逼主角公开表态。",
            emotional_goal="把暧昧推成修罗场。",
            required_heat=3,
            required_secret_ids=["secret_video"],
            focus_character_ids=["gu_chengye"],
            rival_character_ids=["lin_man"],
            preferred_move_families=["accuse", "ally_with", "jealousy_trigger"],
            reveal_candidates=["secret_video"],
            fallback_scene_prompt="大厅还在奏乐，但空气已经像掐着火苗。",
        ),
        BeatSpec(
            beat_id="beat_reveal",
            title="视频曝光",
            goal="逼所有人承认谁在操盘这场联姻。",
            return_hooks=["今晚过后，没有人还能假装一切都没有发生。"],
                affordances=[AffordanceWeight(tag="build_trust", weight=2), AffordanceWeight(tag="reveal_truth", weight=2)],
            phase="reveal",
            scene_goal="让偷拍视频改变局势。",
            emotional_goal="把关系推向无法回头的边界。",
            required_heat=3,
            required_secret_ids=["secret_video"],
            focus_character_ids=["lin_man"],
            rival_character_ids=["gu_chengye"],
            preferred_move_families=["public_reveal", "private_confession", "betray"],
            reveal_candidates=["secret_contract"],
            fallback_scene_prompt="屏幕一亮，所有人的体面都开始裂开。",
        ),
        BeatSpec(
            beat_id="beat_lock",
            title="结局落锤",
            goal="锁定最终站队和关系结局。",
            return_hooks=["今晚之后，你不可能再同时拥有所有人。"],
                affordances=[AffordanceWeight(tag="build_trust", weight=2), AffordanceWeight(tag="reveal_truth", weight=2)],
            phase="lock",
            scene_goal="收束最终关系。",
            emotional_goal="让选择变成代价。",
            required_heat=2,
            focus_character_ids=["gu_chengye"],
            rival_character_ids=["lin_man"],
            preferred_move_families=["ally_with", "betray", "private_confession"],
            fallback_scene_prompt="每个人都在等你最后一句话。",
        ),
    ]
    return PlayPlan(
        story_id="story_relationship_drama",
        story_mode="relationship_drama",
        story_shell_id="wealth_families",
        story_title="修罗场晚宴",
        protagonist=protagonist,
        protagonist_name="沈知微",
        closeout_profile="legacy_civic_placeholder",
        closeout_router_reason="relationship_drama_transition",
        runtime_policy_profile="legacy_civic_placeholder",
        runtime_router_reason="relationship_drama_transition",
        premise="一场豪门订婚宴在旧爱回归和偷拍视频的冲击下彻底失控。",
        tone="轻奢都市抓马",
        style_guard="人物关系优先于世界观说明，名场面优先于制度设定。",
        cast=cast,
        truths=[
            TruthItem(truth_id="secret_video", text="偷拍视频的真正来源能毁掉这场联姻。"),
            TruthItem(truth_id="secret_contract", text="遗嘱和婚约背后藏着同一份交易。"),
        ],
        endings=[
            EndingItem(ending_id="route_lock", label="路线锁定", summary="你终于把这段关系推到了无法退回的地方。"),
            EndingItem(ending_id="bittersweet", label="苦涩成局", summary="你得到了想要的人，却失去了体面和余地。"),
            EndingItem(ending_id="breakdown", label="关系翻车", summary="所有人的秘密一起爆炸，谁都没有赢。"),
            EndingItem(ending_id="open_loop", label="悬而未决", summary="没人真正离开，但真正的结局还没有发生。"),
        ],
        axes=[
            AxisDefinition(axis_id="legacy_pressure", label="Legacy Pressure", kind="pressure"),
            AxisDefinition(axis_id="legacy_exposure", label="Legacy Exposure", kind="exposure"),
        ],
        stances=[],
        flags=[],
        beats=beats,
        route_unlock_rules=[],
        ending_rules=[EndingRule(ending_id="open_loop", conditions=ConditionBlock())],
        affordance_effect_profiles=[
            AffordanceEffectProfile(affordance_tag="build_trust", default_story_function="advance"),
            AffordanceEffectProfile(affordance_tag="reveal_truth", default_story_function="reveal"),
        ],
        available_affordance_tags=["build_trust", "reveal_truth"],
        max_turns=5,
        opening_narration="宴会厅的灯光太亮，亮到每个人都像在等今晚谁先把体面摔碎。",
        relationship_hook="订婚宴、旧爱回归和偷拍视频，让你被迫决定要和谁一起失控。",
        secret_hook="你知道那段视频真正的来源，但还没决定何时公开。",
        route_target_ids=["gu_chengye", "lin_man", "xu_zhiyao"],
    )


def test_relationship_drama_session_updates_relationship_state(tmp_path: Path) -> None:
    storage = SQLitePlaySessionStorage(str(tmp_path / "runtime_state.sqlite3"))
    service = PlaySessionService(
        story_library_service=object(),  # type: ignore[arg-type]
        storage=storage,
        settings=Settings(_env_file=None),
    )
    plan = _relationship_plan()

    created = service.create_session_from_plan(plan, actor_user_id="user-1")

    assert created.story_mode == "relationship_drama"
    assert created.current_route_target_id == "gu_chengye"
    assert created.relationship_state is not None
    assert len(created.relationship_state.targets) == 3

    updated = service.submit_turn(
        created.session_id,
        PlayTurnRequest(input_text="我先安抚顾承野，告诉他今晚我不会当众拆穿他。"),
        actor_user_id="user-1",
    )

    assert updated.story_mode == "relationship_drama"
    assert updated.feedback is not None
    assert updated.feedback.last_turn_relationship_deltas["gu_chengye"]["trust"] > 0
    assert updated.feedback.last_turn_global_deltas["route_lock"] > 0
    target = next(item for item in (updated.relationship_state.targets if updated.relationship_state else []) if item.character_id == "gu_chengye")
    assert target.affection >= 0
    assert target.trust > 0
    trace = service.get_turn_traces(created.session_id, actor_user_id="user-1")[0]
    assert trace.move_family == "comfort"
    assert trace.target_character_ids == ["gu_chengye"]


def test_relationship_drama_session_persists_new_state_fields(tmp_path: Path) -> None:
    db_path = str(tmp_path / "runtime_state.sqlite3")
    storage = SQLitePlaySessionStorage(db_path)
    settings = Settings(_env_file=None)
    plan = _relationship_plan()

    service = PlaySessionService(
        story_library_service=object(),  # type: ignore[arg-type]
        storage=storage,
        settings=settings,
    )
    created = service.create_session_from_plan(plan, actor_user_id="user-1")
    service.submit_turn(
        created.session_id,
        PlayTurnRequest(input_text="我逼问顾承野，偷拍视频背后的秘密到底是谁放出来的。"),
        actor_user_id="user-1",
    )

    reloaded_service = PlaySessionService(
        story_library_service=object(),  # type: ignore[arg-type]
        storage=SQLitePlaySessionStorage(db_path),
        settings=settings,
    )
    reloaded = reloaded_service.get_session(created.session_id, actor_user_id="user-1")
    traces = reloaded_service.get_turn_traces(created.session_id, actor_user_id="user-1")

    assert reloaded.story_mode == "relationship_drama"
    assert reloaded.relationship_state is not None
    assert reloaded.relationship_state.secret_exposure > 0
    assert traces[0].revealed_secret_ids
    assert traces[0].move_family == "probe_secret"
