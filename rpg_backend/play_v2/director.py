from __future__ import annotations

from dataclasses import dataclass, field

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author.normalize import unique_preserve
from rpg_backend.author_v2.contracts import CompiledPlayPlan, CompiledSegment
from rpg_backend.play_v2.contracts import UrbanTurnIntent, UrbanWorldState

_SECRET_OBJECT = {
    "will_evidence": "改写顺位的遗嘱证据",
    "hidden_heir": "把名分掀翻的私生身份",
    "black_ledger": "足够让人当场下台的黑账",
    "contract_flip": "能把发布会当场掀翻的合同反转",
    "scandal_video": "会把热搜和关系一起炸穿的偷拍视频",
    "old_recording": "会把脸面和前途一起撕开的旧录音",
    "legacy_contract_secret": "会把旧债和现在一起拖进现实的契约真相",
}

_COST_OBJECT = {
    "marriage_face": "婚约和整桌人的体面",
    "inheritance_status": "顺位和家族位置",
    "career_position": "位置和手里的发言权",
    "career_reputation": "前途和以后还能不能翻身的机会",
    "public_reputation": "名声和公众退路",
    "scholarship_future": "名额和前途",
    "legacy_normal_life": "正常生活和最后一点退路",
}


@dataclass(frozen=True)
class DirectedTurnOutcome:
    forced_public_event: bool = False
    event_tags: list[str] = field(default_factory=list)
    public_event_text: str | None = None
    collateral_global_deltas: dict[str, int] = field(default_factory=dict)
    collateral_relationship_deltas: dict[str, dict[str, int]] = field(default_factory=dict)
    pain_text: str | None = None
    no_return_text: str | None = None
    preferred_burst_move: RelationshipMoveFamily | None = None


class EventDirector:
    @staticmethod
    def _secret_object(plan: CompiledPlayPlan) -> str:
        return _SECRET_OBJECT.get(plan.seed_fingerprint.secret_class, "最不该见光的真相")

    @staticmethod
    def _cost_object(plan: CompiledPlayPlan) -> str:
        return _COST_OBJECT.get(plan.seed_fingerprint.cost_class, "退路和体面")

    @staticmethod
    def preferred_burst_move(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
        target_id: str | None,
        candidates: list[RelationshipMoveFamily],
    ) -> RelationshipMoveFamily | None:
        candidate_set = set(candidates)
        if "public_reveal" in candidate_set and segment.segment_role in {"reveal", "terminal"}:
            return "public_reveal"
        target_mind = state.npc_mind_states.get(target_id or "")
        pressure_load = target_mind.pressure_load if target_mind is not None else 0
        humiliation_risk = target_mind.humiliation_risk if target_mind is not None else 0
        jealousy = target_mind.jealousy if target_mind is not None else 0
        if segment.segment_role == "misread":
            if "public_reveal" in candidate_set and (state.secret_exposure >= 1 and (pressure_load >= 3 or humiliation_risk >= 3 or jealousy >= 3 or state.scene_heat >= 3)):
                return "public_reveal"
            if "accuse" in candidate_set and (pressure_load >= 3 or humiliation_risk >= 3 or jealousy >= 4):
                return "accuse"
            if "public_reveal" in candidate_set and (state.secret_exposure >= 2 or state.scene_heat >= 4):
                return "public_reveal"
        if segment.segment_role == "opening":
            if "accuse" in candidate_set and (pressure_load >= 3 or humiliation_risk >= 3):
                return "accuse"
            if "public_reveal" in candidate_set and state.secret_exposure >= 2 and (pressure_load >= 2 or humiliation_risk >= 2):
                return "public_reveal"
        if "public_reveal" in candidate_set and (state.secret_exposure >= 2 or state.scene_heat >= 4):
            return "public_reveal"
        return None

    @staticmethod
    def direct_turn_outcome(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
    ) -> DirectedTurnOutcome:
        forced_public_event = bool(
            segment.segment_role in {"reveal", "terminal"}
            and intent.move_family in {"public_reveal", "accuse", "betray"}
        )
        public_event_text = EventDirector._public_event_text(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
            forced_public_event=forced_public_event,
        )
        no_return_text = EventDirector._no_return_text(plan=plan, segment=segment, state=state, forced_public_event=forced_public_event)
        collateral_global_deltas, collateral_relationship_deltas = EventDirector._collateral_costs(
            plan=plan,
            segment=segment,
            intent=intent,
            state=state,
            forced_public_event=forced_public_event,
        )
        pain_text = EventDirector._pain_text(
            plan=plan,
            intent=intent,
            target_id=intent.target_id,
            forced_public_event=forced_public_event,
        )
        event_tags = []
        if forced_public_event or public_event_text:
            event_tags.append("public_event")
        if segment.segment_role in {"reveal", "terminal"}:
            event_tags.append("no_return")
        if pain_text:
            event_tags.append("pain_tradeoff")
        return DirectedTurnOutcome(
            forced_public_event=forced_public_event,
            event_tags=event_tags,
            public_event_text=public_event_text,
            collateral_global_deltas=collateral_global_deltas,
            collateral_relationship_deltas=collateral_relationship_deltas,
            pain_text=pain_text,
            no_return_text=no_return_text,
            preferred_burst_move=EventDirector.preferred_burst_move(
                plan=plan,
                segment=segment,
                state=state,
                target_id=intent.target_id,
                candidates=[intent.move_family],
            ),
        )

    @staticmethod
    def _other_target_ids(segment: CompiledSegment, target_id: str | None) -> list[str]:
        return [
            candidate
            for candidate in unique_preserve(segment.focus_target_ids + segment.rival_target_ids)
            if candidate != target_id
        ][:2]

    @staticmethod
    def _public_event_text(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
        forced_public_event: bool,
    ) -> str | None:
        if not forced_public_event and segment.segment_role not in {"reveal", "terminal"} and state.secret_exposure < 3:
            return None
        secret_object = EventDirector._secret_object(plan)
        if plan.story_shell_id == "wealth_families":
            if intent.move_family == "public_reveal":
                return f"主桌先静死了一秒，{secret_object}被你当众摔上桌面，刚才还端着体面的人第一个失了声。"
            if intent.move_family == "betray":
                return "主桌上的顺位和站边被你一句话当场改写，被推出去的人连筷子都没放稳，整桌人已经开始换边。"
            return "家宴被你当场掀成了公开清算，主桌先静后乱，最会维持体面的人第一个不敢接话。"
        if plan.story_shell_id == "office_power":
            if intent.move_family == "public_reveal":
                return f"会议桌先是死静，接着{secret_object}被你翻到台面和投屏上，原本的表决节奏当场折断。"
            if intent.move_family == "betray":
                return "背锅位被你当场点出来，刚才还在装中立的人立刻开始切责任和席位，谁都没法再说只是流程问题。"
            return "你这一句把会场直接打成了站边现场，谁先开口、谁来背锅，顺序都被当场改写了。"
        if plan.story_shell_id == "entertainment_scandal":
            if intent.move_family == "public_reveal":
                return f"镜头直接咬住这一下，{secret_object}已经不是后台传闻，而是所有人都看见的事故现场。"
            if intent.move_family == "betray":
                return "现场立场被你当场翻了面，镜头已经吃到最难看的那一秒，后面只会越传越大。"
            return "这一下已经从后台摩擦滚成了公开事故，现场和外面的风向一起歪过去了。"
        if intent.move_family == "public_reveal":
            return f"台下先静后炸，{secret_object}被你当场放出来，评审席和观众都开始偏头交换眼色。"
        if intent.move_family == "betray":
            return "最该藏着的站队被你当场掀开，台下的人直接换边，名额和风向一起松了口。"
        return "台下的风向被你这一手硬生生扳过去了，公开站队已经不是传闻，而是所有人都看见的事实。"

    @staticmethod
    def _no_return_text(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        state: UrbanWorldState,
        forced_public_event: bool,
    ) -> str | None:
        if segment.segment_role not in {"reveal", "terminal"} and not forced_public_event and state.route_lock < 3:
            return None
        cost_object = EventDirector._cost_object(plan)
        if plan.story_shell_id == "wealth_families":
            return f"从这一秒起，{cost_object}不再是桌下暗账，而是谁都看见的抢位和翻脸，没人还能把这桌收回去。"
        if plan.story_shell_id == "office_power":
            return f"这一步已经把牌桌上的敌我关系和{cost_object}一起钉死，后面谁想回头都会先被当成心虚。"
        if plan.story_shell_id == "entertainment_scandal":
            return f"这一幕已经滚进镜头和风向，后面不管谁解释，都只会变成围着{cost_object}展开的切割和追责。"
        return f"这一下已经把{cost_object}和站边一起钉到台面上，后面谁再装作没发生，只会更难看。"

    @staticmethod
    def _pain_text(
        *,
        plan: CompiledPlayPlan,
        intent: UrbanTurnIntent,
        target_id: str | None,
        forced_public_event: bool,
    ) -> str:
        target_name = next((member.display_name for member in plan.cast if member.character_id == target_id), "对方")
        lane_id = intent.lane_id
        cost_object = EventDirector._cost_object(plan)
        if lane_id == "relationship":
            if plan.story_shell_id == "entertainment_scandal":
                return f"你护住{target_name}的那一下太明显了，镜头和旁边的人已经把你们拍成同一边，后面谁都不会把这当成顺手。"
            if plan.story_shell_id == "campus_romance":
                return f"你替{target_name}挡的那一下太明，台下和熟人圈已经把你们算成一边，后面丢脸和前途都不会只落在她身上。"
            if plan.story_shell_id == "wealth_families":
                return f"你往{target_name}那边偏的这一下主桌看得太清楚了，另一边放下酒杯时记住的已经不是情分，而是谁先站过去了。"
            return f"你护住{target_name}的那一下落得太明，会上的人已经不再把你当还能模糊的人，后面谁记账都会先记到你头上。"
        if lane_id == "side":
            if plan.story_shell_id == "entertainment_scandal":
                return f"你这一下替{target_name}认边太像公开口径了，场边的人会先把你记成她那边的版本。"
            if plan.story_shell_id == "campus_romance":
                return f"你这一下替{target_name}认边太像当众选阵营了，台下和评审接下来都会按这个新位置看你。"
            if plan.story_shell_id == "wealth_families":
                return f"你替{target_name}认边时根本没留退路，主桌上的人接下来只会按新的敌我顺序看你。"
            return f"你替{target_name}认边的这一手太像公开表态了，后面谁要记账，都会先从你的站位开始算。"
        if intent.move_family == "betray":
            return f"你把{target_name}先推出去挡刀，台上台下都会记得是谁先下的手，后面想把这层关系补回去几乎不可能。"
        if forced_public_event:
            return f"你把最不该见光的东西拖上台面，也把自己的{cost_object}一起烧进去了，后面先疼的不会只有对面。"
        return f"你把{target_name}逼到台前的同时，也在拿自己的{cost_object}去换这一刀见血。"

    @staticmethod
    def _collateral_costs(
        *,
        plan: CompiledPlayPlan,
        segment: CompiledSegment,
        intent: UrbanTurnIntent,
        state: UrbanWorldState,
        forced_public_event: bool,
    ) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
        lane_id = intent.lane_id
        others = EventDirector._other_target_ids(segment, intent.target_id)
        global_deltas: dict[str, int] = {}
        relationship_deltas: dict[str, dict[str, int]] = {}
        if lane_id == "relationship":
            if others:
                relationship_deltas[others[0]] = {"suspicion": 1, "tension": 2, "trust": -1 if intent.scene_frame != "private" else 0}
            if intent.scene_frame != "private":
                global_deltas["public_image"] = -1
        elif lane_id == "side":
            if others:
                relationship_deltas[others[0]] = {"trust": -1, "suspicion": 1, "tension": 1}
            global_deltas["route_lock"] = 2 if segment.segment_role in {"reveal", "terminal"} else 1
            if segment.segment_role in {"reveal", "terminal"}:
                global_deltas["public_image"] = -1
        else:
            if intent.target_id is not None:
                relationship_deltas[intent.target_id] = {"trust": -2, "tension": 1}
            if others:
                relationship_deltas[others[0]] = {"suspicion": 1, "tension": 1}
            global_deltas["public_image"] = -2 if forced_public_event or intent.move_family == "public_reveal" else -1
            global_deltas["scene_heat"] = 1
            global_deltas["secret_exposure"] = 1
            if forced_public_event or segment.segment_role in {"reveal", "terminal"}:
                global_deltas["secret_exposure"] = max(global_deltas["secret_exposure"], 3 - state.secret_exposure)
                global_deltas["public_image"] = min(global_deltas["public_image"], -2)
        return global_deltas, relationship_deltas
