from __future__ import annotations

from typing import Any

from rpg_backend.author.normalize import trim_text
from rpg_backend.author_v2.contracts import (
    ArenaType,
    ConflictTemplateId,
    TemplateToneExamplePack,
    CostClass,
    HeroTemplateSpec,
    LightTemplateSpec,
    ProtagonistIdentityClass,
    PublicBombFamily,
    RelationshipGeometryId,
    RoutePreferenceBias,
    SecretClass,
    SeedFingerprint,
    SeedFitMode,
    StoryShellId,
    ToneCadence,
    ToneCostFamily,
    ToneExampleLine,
    ToneExampleSemanticTag,
    ToneReasonFamily,
    ToneSceneExample,
    ToneSignalFamily,
    ToneBias,
)

PROMO_SHELLS: tuple[StoryShellId, ...] = (
    "wealth_families",
    "office_power",
    "entertainment_scandal",
    "campus_romance",
)
HERO_TEMPLATE_IDS: set[ConflictTemplateId] = {
    "wealth_banquet_will_flip",
    "wealth_engagement_sideswitch",
    "wealth_inheritance_evidence_drop",
    "wealth_private_heir_return",
    "office_board_vote_blackledger",
    "office_merger_scapegoat",
    "office_launch_contract_flip",
    "office_promotion_side_betrayal",
}
SUPPORTED_TEMPLATE_IDS: tuple[ConflictTemplateId, ...] = (
    "wealth_banquet_will_flip",
    "wealth_engagement_sideswitch",
    "wealth_inheritance_evidence_drop",
    "wealth_private_heir_return",
    "office_board_vote_blackledger",
    "office_merger_scapegoat",
    "office_launch_contract_flip",
    "office_promotion_side_betrayal",
    "entertainment_awards_scandal",
    "entertainment_livestream_hotsearch_flip",
    "entertainment_variety_blackmail_flip",
    "campus_homecoming_recording",
    "campus_mentor_review_sideswitch",
    "campus_club_campaign_flip",
    "urban_supernatural_legacy_contract",
)

_SHELL_KEYWORDS: dict[StoryShellId, tuple[str, ...]] = {
    "wealth_families": ("豪门", "联姻", "继承", "遗嘱", "婚约", "订婚", "未婚夫", "家宴", "继承人", "私生", "旧爱", "律师"),
    "office_power": ("董事会", "并购", "黑账", "上司", "法务", "发布会", "升职", "空降", "总裁"),
    "entertainment_scandal": ("娱乐圈", "热搜", "颁奖", "颁奖礼", "庆功夜", "彩排", "直播", "绯闻", "隐恋", "代言", "黑料", "顶流", "经纪人", "偷拍视频"),
    "campus_romance": ("校园", "校庆", "奖学金", "导师", "评审", "前任", "录音", "学生会"),
    "urban_supernatural": ("异能", "夜巡", "契约", "怪谈", "会所", "灵媒", "旧债"),
}


def _contains_any(seed: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in seed for keyword in keywords)


def _best_shell(seed: str) -> tuple[StoryShellId, int]:
    scores = {
        shell_id: sum(1 for keyword in keywords if keyword in seed)
        for shell_id, keywords in _SHELL_KEYWORDS.items()
    }
    shell_id = max(scores.items(), key=lambda item: (item[1], item[0]))[0]
    return shell_id, int(scores[shell_id])


def _arena_type(seed: str, shell_id: StoryShellId) -> ArenaType:
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
        return "board_vote"
    if shell_id == "entertainment_scandal":
        if "颁奖" in seed or "红毯" in seed or "奖项" in seed:
            return "awards_backstage"
        if "直播" in seed:
            return "livestream_room"
        if "综艺" in seed or "录制" in seed:
            return "variety_set"
        return "awards_backstage"
    if shell_id == "campus_romance":
        if "校庆" in seed:
            return "homecoming_stage"
        if "导师" in seed or "评审" in seed:
            return "mentor_review"
        if "社团" in seed:
            return "club_event"
        return "homecoming_stage"
    return "night_clubfront"


def _secret_class(seed: str, shell_id: StoryShellId) -> SecretClass:
    if "遗嘱" in seed or "旧案证据" in seed:
        return "will_evidence"
    if "私生" in seed:
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
    return {
        "wealth_families": "will_evidence",
        "office_power": "black_ledger",
        "entertainment_scandal": "scandal_video",
        "campus_romance": "old_recording",
        "urban_supernatural": "legacy_contract_secret",
    }[shell_id]


def _relationship_geometry(seed: str, shell_id: StoryShellId) -> RelationshipGeometryId:
    if shell_id == "wealth_families":
        if all(token in seed for token in ("未婚夫", "旧爱", "律师")):
            return "fiance_oldlove_lawyer"
        if "私生" in seed or "继承" in seed:
            return "heir_oldlove_secret_keeper"
        return "fiance_oldlove_lawyer"
    if shell_id == "office_power":
        if all(token in seed for token in ("上司", "对手", "法务")):
            return "boss_rival_legal"
        return "power_circle_oldally"
    if shell_id == "entertainment_scandal":
        return "idol_manager_ex"
    if shell_id == "campus_romance":
        return "scholarship_ex_recording"
    return "legacy_danger_ally"


def _cost_class(seed: str, shell_id: StoryShellId) -> CostClass:
    if shell_id == "wealth_families":
        return "inheritance_status" if "继承" in seed or "遗嘱" in seed else "marriage_face"
    if shell_id == "office_power":
        return "career_position" if "升职" in seed or "职位" in seed else "career_reputation"
    if shell_id == "entertainment_scandal":
        return "public_reputation"
    if shell_id == "campus_romance":
        return "scholarship_future"
    return "legacy_normal_life"


def _bomb_family(secret_class: SecretClass, shell_id: StoryShellId) -> PublicBombFamily:
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
    return "evidence_drop"


def _protagonist_identity_class(seed: str, shell_id: StoryShellId) -> ProtagonistIdentityClass:
    if shell_id == "wealth_families":
        return "heiress_target"
    if shell_id == "office_power":
        return "project_lead"
    if shell_id == "entertainment_scandal":
        return "industry_operator"
    if shell_id == "campus_romance":
        return "campus_core"
    return "legacy_urban_outsider"


def _tone_bias(seed: str, shell_id: StoryShellId) -> ToneBias:
    if shell_id in {"wealth_families", "office_power"}:
        return "knife"
    if shell_id == "entertainment_scandal":
        return "melodramatic"
    if shell_id == "campus_romance":
        return "wistful"
    return "cold"


def _route_preference_bias(seed: str) -> RoutePreferenceBias:
    if _contains_any(seed, ("站队", "表态", "背锅", "扛雷")):
        return "side"
    if _contains_any(seed, ("前任", "旧爱", "暧昧", "未婚夫")):
        return "relationship"
    if _contains_any(seed, ("放录音", "翻桌", "公开", "当众", "热搜")):
        return "burst"
    return "mixed"


def _template_shell_id(template_id: ConflictTemplateId) -> StoryShellId:
    if template_id.startswith("wealth_"):
        return "wealth_families"
    if template_id.startswith("office_"):
        return "office_power"
    if template_id.startswith("entertainment_"):
        return "entertainment_scandal"
    if template_id.startswith("campus_"):
        return "campus_romance"
    return "urban_supernatural"


def _default_signal_family(shell_id: StoryShellId) -> ToneSignalFamily:
    if shell_id == "entertainment_scandal":
        return "public_wave"
    if shell_id == "campus_romance":
        return "peer_spread"
    if shell_id == "office_power":
        return "institutional_shift"
    if shell_id == "wealth_families":
        return "relationship_pressure"
    return "public_wave"


def _default_cost_family(shell_id: StoryShellId) -> ToneCostFamily:
    if shell_id == "entertainment_scandal":
        return "narrative_control"
    if shell_id == "campus_romance":
        return "eligibility"
    if shell_id == "office_power":
        return "position"
    if shell_id == "wealth_families":
        return "position"
    return "relationship"


def _line_semantic_tag(template_id: ConflictTemplateId, slot: str) -> ToneExampleSemanticTag:
    shell_id = _template_shell_id(template_id)
    signal = _default_signal_family(shell_id)
    shell_cost = _default_cost_family(shell_id)
    by_slot: dict[str, tuple[ToneReasonFamily, ToneCadence, ToneCostFamily]] = {
        "hook": ("opportunity_window", "contrast", shell_cost),
        "route_promise": ("self_preserve", "slow_press", shell_cost),
        "bomb": ("loss_position", "staccato", shell_cost),
        "cost": ("old_debt", "broken", "face" if shell_id in {"campus_romance", "entertainment_scandal"} else shell_cost),
        "supporting": ("old_debt" if shell_id in {"campus_romance", "wealth_families"} else "self_preserve", "slow_press", shell_cost),
    }
    reason, cadence, cost = by_slot.get(slot, ("mixed", "mixed", "mixed"))
    return ToneExampleSemanticTag(
        reason_family=reason,
        signal_family=signal,
        cost_family=cost,
        cadence=cadence,
    )


def _scene_semantic_tag(template_id: ConflictTemplateId, slot: str) -> ToneExampleSemanticTag:
    shell_id = _template_shell_id(template_id)
    signal = _default_signal_family(shell_id)
    shell_cost = _default_cost_family(shell_id)
    if slot == "public_escalation":
        return ToneExampleSemanticTag(
            reason_family="loss_position",
            signal_family=signal,
            cost_family=shell_cost,
            cadence="staccato",
        )
    return ToneExampleSemanticTag(
        reason_family="old_debt",
        signal_family="relationship_pressure" if shell_id in {"wealth_families", "urban_supernatural"} else signal,
        cost_family="relationship" if shell_id in {"wealth_families", "urban_supernatural"} else shell_cost,
        cadence="slow_press",
    )


def _tone_pack(
    template_id: ConflictTemplateId,
    *,
    hook: str,
    route: str,
    bomb: str,
    cost: str,
    supporting: str,
    public_scene: str,
    private_scene: str,
) -> TemplateToneExamplePack:
    return TemplateToneExamplePack(
        lines=[
            ToneExampleLine(
                bucket_id=f"{template_id}:hook",
                slot="hook",
                layer="primary",
                dramatic_band="steady",
                semantic_tag=_line_semantic_tag(template_id, "hook"),
                text=trim_text(hook, 180),
            ),
            ToneExampleLine(
                bucket_id=f"{template_id}:route",
                slot="route_promise",
                layer="primary",
                dramatic_band="rising",
                semantic_tag=_line_semantic_tag(template_id, "route_promise"),
                text=trim_text(route, 180),
            ),
            ToneExampleLine(
                bucket_id=f"{template_id}:bomb",
                slot="bomb",
                layer="fallout",
                dramatic_band="explosive",
                semantic_tag=_line_semantic_tag(template_id, "bomb"),
                text=trim_text(bomb, 180),
            ),
            ToneExampleLine(
                bucket_id=f"{template_id}:cost",
                slot="cost",
                layer="fallout",
                dramatic_band="aftermath",
                semantic_tag=_line_semantic_tag(template_id, "cost"),
                text=trim_text(cost, 180),
            ),
            ToneExampleLine(
                bucket_id=f"{template_id}:supporting",
                slot="supporting",
                layer="supporting",
                dramatic_band="rising",
                semantic_tag=_line_semantic_tag(template_id, "supporting"),
                text=trim_text(supporting, 180),
            ),
        ],
        scenes=[
            ToneSceneExample(
                bucket_id=f"{template_id}:public_scene",
                slot="public_escalation",
                layer="fallout",
                dramatic_band="explosive",
                semantic_tag=_scene_semantic_tag(template_id, "public_escalation"),
                text=trim_text(public_scene, 260),
            ),
            ToneSceneExample(
                bucket_id=f"{template_id}:private_scene",
                slot="private_aftermath",
                layer="primary",
                dramatic_band="aftermath",
                semantic_tag=_scene_semantic_tag(template_id, "private_aftermath"),
                text=trim_text(private_scene, 260),
            ),
        ],
    )


_TONE_PACKS: dict[ConflictTemplateId, TemplateToneExamplePack] = {
    "wealth_banquet_will_flip": _tone_pack(
        "wealth_banquet_will_flip",
        hook="主桌还在装体面，真正决定顺位的那张纸已经在袖口里发热。",
        route="你不是在挑喜欢谁，你是在挑今晚先护谁留在桌上。",
        bomb="证据落桌那一秒，最稳的人先失了声。",
        cost="真相一旦掀开，赔掉的从来不只是一张脸。",
        supporting="旁边的人不劝，只在看谁先被这桌体面切出去。",
        public_scene="酒杯刚碰出声，那份改写顺位的证据被直接拍上主桌。有人还想笑，笑意却先碎了，连最会装稳的长辈都把筷子停在半空。",
        private_scene="门一关，谁都不再提体面，只开始问你今晚到底打算先护谁。你明明还坐得住，心里却已经知道，只要那张纸见光，这桌人以后见面都不会再像今天。",
    ),
    "wealth_engagement_sideswitch": _tone_pack(
        "wealth_engagement_sideswitch",
        hook="订婚宴还没开席，站错边的人已经先把退路踩空了。",
        route="你要先护住谁的主位，才配决定今晚这门婚还结不结。",
        bomb="最该敬酒的时候，倒戈的人先把场子掀开了。",
        cost="你一翻牌，赔上的就是以后所有人默认你该嫁的那条路。",
        supporting="围观的人嘴上还在祝福，眼神已经开始替你们重排关系。",
        public_scene="灯最亮的那一桌还在等敬酒，旧情和站边却先一步翻上台面。原本该替你撑场的人当众改口，整桌人都听见自己体面掉地的声音。",
        private_scene="后台没了音乐，只剩人压着嗓子问你到底跟谁是一边的。你一句话没说，门外那些祝福声却已经像在替这段婚约送葬。",
    ),
    "wealth_inheritance_evidence_drop": _tone_pack(
        "wealth_inheritance_evidence_drop",
        hook="所有人都以为胜负已定时，最危险的那份证据才真正开始发烫。",
        route="你不是选谁更可怜，是选谁该先从继承席上掉下去。",
        bomb="证据被摔出来的那一秒，顺位像玻璃一样整片裂开。",
        cost="真相见光之后，连你最想保的人也会陪着一起受审。",
        supporting="桌边的人不说话，只在等谁先被新的顺位碾过去。",
        public_scene="主桌还在按旧顺序坐着，那份证据却突然被你当众拍出来。名字、顺位、脸色一起翻了面，连原本最像结果的人也开始慌着找位置。",
        private_scene="屋里安静得能听见茶盖碰瓷，你却知道真正要命的不是证据本身，而是它会逼你亲手把某个人也送进审判里。",
    ),
    "wealth_private_heir_return": _tone_pack(
        "wealth_private_heir_return",
        hook="血统这件事没被说破前，谁都还能假装今晚只是家宴。",
        route="你得先认谁是自己人，才有资格决定秘密还能藏多久。",
        bomb="录音一放，主桌上的体面比认亲先崩。",
        cost="底牌一翻，名分、旧情和退路会一起掉下来。",
        supporting="旁边的人不救场，只在心里算谁该先被赶出这桌。",
        public_scene="家宴最讲血统体面的那一秒，那段录音被外放到全桌都听见。认亲的话还没说完，先乱的是那些最会讲规矩的人，连看戏的人都不再敢装没听见。",
        private_scene="门外还剩杯盘碰撞的声响，门里已经没有人再叫你小心。大家只在逼你承认，一旦今晚把话说破，以后谁也回不到原来的称呼里。",
    ),
    "office_board_vote_blackledger": _tone_pack(
        "office_board_vote_blackledger",
        hook="票还没落下，最不该摊到桌上的黑账已经开始找出口。",
        route="你要先保谁还坐在牌桌边，才有资格逼别人当众表态。",
        bomb="黑账见光的那一下，最像规矩本身的人也失了手。",
        cost="翻牌之后，别人记住的不是你说了真话，而是你今天站了哪边。",
        supporting="桌边的人不插话，只在等谁先被推出去背锅。",
        public_scene="表决还在走流程，那份黑账却被你直接翻到桌面上。原本按顺序说话的人一下全乱了，连最稳的那位都得先看谁还能保得住位置。",
        private_scene="会后走廊灯光太冷，所有人都在装平静。可你心里知道，真正回不去的不是这一票，而是谁以后会被当成先掀桌的人。",
    ),
    "office_merger_scapegoat": _tone_pack(
        "office_merger_scapegoat",
        hook="并购局最可怕的从来不是出错，而是有人比你更早决定谁该背锅。",
        route="你得先替谁挡雷，才知道最后能不能把别人推下去。",
        bomb="最该收尾的时候，锅被当众翻了面。",
        cost="你今天保下来的位置，可能会变成明天先咬你的证据。",
        supporting="牌桌边没人劝，只在看谁会成为下一个被切掉的人。",
        public_scene="并购会原本正要收口，那笔该被压住的东西却被当众翻出来。原本说好一起扛的人瞬间往后退，整桌人都在抢着把锅往别人身上塞。",
        private_scene="电梯门一关，大家连客套都懒得装，只剩谁替谁扛、谁卖谁保命的账。你这才知道，收尾从来不是结束，而是背锅顺序被正式写下来的时候。",
    ),
    "office_launch_contract_flip": _tone_pack(
        "office_launch_contract_flip",
        hook="发布会还没开始，真正会让灯光翻车的合同已经先动了。",
        route="你要先护谁别掉下台，再决定是不是现在就掀合同。",
        bomb="灯最亮的时候，合同反转把整场局一起掀翻。",
        cost="真相一亮，相信你的人和合作本身都可能一起断掉。",
        supporting="旁边的人不补台词，只在等谁先被这场翻车拖出局。",
        public_scene="倒计时刚响，合同里的反转就被你直接扯到台前。灯还亮着，笑还挂着，最先翻车的却不是合作案，而是所有人以为能稳住的那点职业体面。",
        private_scene="幕布后面全是压低声音的命令和脏话，你却已经知道问题不在于会不会翻车，而在于这次翻车以后谁会先装作从没和你站过一起。",
    ),
    "office_promotion_side_betrayal": _tone_pack(
        "office_promotion_side_betrayal",
        hook="升降还没定，最危险的不是竞争，是旧同盟先决定要不要卖你。",
        route="你得先站到谁那边，才配决定秘密是不是现在就翻。",
        bomb="投票前的表态一落，最先倒戈的居然是自己人。",
        cost="今天这次站边会被以后所有升职局反复记账。",
        supporting="旁边的人不救你，只在看谁先公开切开同盟。",
        public_scene="升职表决还没开始，那句当众表态已经先把旧同盟撕开了。秘密被说破的一瞬间，不是对手先动，而是你以为会替你撑住的人先把手抽了回去。",
        private_scene="办公室门一关，空气里只剩谁还算自己人这一个问题。你越想稳住，越清楚今天站错的一边，会在以后每一次投票里追着你还债。",
    ),
    "entertainment_awards_scandal": _tone_pack(
        "entertainment_awards_scandal",
        hook="红毯还在闪，后台真正会炸的那一下已经在找镜头。",
        route="你要先保谁留在镜头里，再决定先撕谁的伪装。",
        bomb="所有镜头都对准的时候，最会控场的人也当场翻车。",
        cost="真相一见光，掉下去的不止是热搜，还有你想保的关系。",
        supporting="后台没人真来救场，大家都在等这一下之后该先切谁。",
        public_scene="颁奖礼后台还在维持最漂亮的秩序，那份偷拍视频却被你直接推上台面。镜头一下追过来，最会笑着接话的人先断了拍，连旁边等着上场的人都开始偷看谁会先被切出去。",
        private_scene="化妆镜前灯还是亮的，谁都还顶着最好看的那张脸。可真正让人发冷的是你知道，一旦这事滚出去，外面记住的不会是谁冤，而是谁先不值得保。",
    ),
    "entertainment_livestream_hotsearch_flip": _tone_pack(
        "entertainment_livestream_hotsearch_flip",
        hook="公屏还在刷热闹，真正会把版本掀翻的那一下已经卡在喉咙口。",
        route="你得先保谁留在镜头里，才决定热搜要先炸到谁头上。",
        bomb="最该控节奏的那一秒，秘密被硬顶上公屏，直播间当场失控。",
        cost="一旦翻牌，赔掉的不只是体面，还有以后谁还愿意替你保版本。",
        supporting="场边的人嘴上喊稳住，心里却已经在盘算这波热搜最后该先切谁。",
        public_scene="直播节奏刚被推到最顺的时候，那段最不该见光的东西被你顶上公屏。弹幕、镜头、热搜词条像同时失控，连最会做直播的人都只能眼睁睁看着版本被抢走。",
        private_scene="关掉收声麦之后，后台没人真问你还好不好，大家只在抢一个问题：这波热搜以后，谁先切割，谁还能保住自己的版本。",
    ),
    "entertainment_variety_blackmail_flip": _tone_pack(
        "entertainment_variety_blackmail_flip",
        hook="录制还没结束，最狠的那一段已经不在节目里，而在谁手里握着的黑料里。",
        route="你得先护谁别先翻车，再决定这份黑料要先撕给谁看。",
        bomb="灯还亮着的时候，最会演无事发生的人先破了功。",
        cost="真相一亮，节目外那层关系和节目里的版本会一起散。",
        supporting="围观的人嘴上还在接梗，心里已经在算这波录制完谁会先被切掉。",
        public_scene="录制现场最热闹的时候，那份黑料被你顺手送上台面。笑声还没散，最会演没事的人先破了相，场边那些看热闹的人立刻开始替后面的切割找借口。",
        private_scene="收工灯一灭，真正难听的话才开始说出来。你知道节目里那点效果都不算什么，真正会让人翻不了身的是谁把节目外那层关系也一起卖掉。",
    ),
    "campus_homecoming_recording": _tone_pack(
        "campus_homecoming_recording",
        hook="校庆晚会还没出岔子，熟人圈已经在等谁先把旧录音放出来。",
        route="你得先护谁别被台下吞掉，再决定现在是不是要当众站边。",
        bomb="录音一外放，最会装没事的人先在全场眼神里失态。",
        cost="真相一见光，赔掉的不只是脸面，还有名额和以后整个熟人圈的说法。",
        supporting="台下和评审席没人真想劝，只在看谁先因为这一下丢掉前途。",
        public_scene="校庆最热闹的公开环节刚把气氛顶起来，那段旧录音却被你当场外放到全场都听见。台下的眼神一圈圈变掉，评审席先冷下来，最会装体面的人当着熟人圈的面失了神。",
        private_scene="后台门一关，谁都不提安慰，只开始问你这一下以后奖学金、前途和人际脸面要先赔哪一个。你明明还站着，心里却知道熟人圈以后不会再替你把这件事说轻。",
    ),
    "campus_mentor_review_sideswitch": _tone_pack(
        "campus_mentor_review_sideswitch",
        hook="评审还没给结果，真正会让名额翻盘的话已经在门外排队。",
        route="你得先护谁别被拖下去，再决定是不是现在就逼人站边。",
        bomb="录音一响，最会装冷静的人先在评审席面前破了相。",
        cost="今天这次翻牌，会让以后所有评审都带着旧印象看你。",
        supporting="评审和同学都没劝，大家只在看谁先从安全名单里掉出去。",
        public_scene="导师评审最讲规矩的公开环节上，那段录音被你直接放到每个人耳朵里。评审席先互相看了一眼，台下那圈熟人也跟着变了脸，原本最稳的人最先撑不住。",
        private_scene="走廊上安静得只剩脚步声，可真正让人发冷的是你知道，从这一刻起，别人以后看你的每一次评审，都会先想起今天谁先站错了边。",
    ),
    "campus_club_campaign_flip": _tone_pack(
        "campus_club_campaign_flip",
        hook="庆功夜还没散，真正会把站队写死的那一下已经在熟人圈里发酵。",
        route="你得先护谁别被舆论吃掉，再决定先站到谁那边。",
        bomb="最热闹的时候一外放，所有人都在同一秒换了脸色。",
        cost="一旦翻牌，掉下去的不只是脸面，还有社团位置和后面的名额。",
        supporting="围观的人嘴上还装没事，眼神已经开始在熟人圈里传谁先站边。",
        public_scene="社团庆功夜本来还热闹，那段最不该见光的录音却在你手里突然外放到全场都听见。笑声一下断掉，熟人圈的眼神跟着四散，原本还在装没事的人集体变了脸。",
        private_scene="散场以后每个人都在装忙，没人肯先提那段录音。可你知道真正难熬的不是当场那一下，而是之后每个社团群、每次评审和每张报名表都会把这件事重新翻出来。",
    ),
    "urban_supernatural_legacy_contract": _tone_pack(
        "urban_supernatural_legacy_contract",
        hook="最危险的不是怪谈本身，而是那份旧契约终于找到一个能见光的出口。",
        route="你得先信谁、护谁，才决定是不是把这份契约硬拖进现实。",
        bomb="最不该被看见的那一刻，旧债被直接拖到人群中央。",
        cost="一旦翻牌，正常生活和最后一点退路会一起被烧掉。",
        supporting="旁边的人不再讨论真假，只在看谁先被旧债挑中。",
        public_scene="人群最密的时候，那份旧契约被你硬生生拖进现实。最先乱的不是怪谈，而是所有人看见自己原本不该看见的东西之后的脸色。",
        private_scene="灯一暗，谁都不再问你信不信，只问你还敢不敢继续往前走。你知道一旦真的把契约翻开，回到正常生活这件事就只会越来越像笑话。",
    ),
}


def build_seed_fingerprint(seed: str, play_length_preset: str) -> SeedFingerprint:
    shell_id, score = _best_shell(seed)
    fit_mode: SeedFitMode
    if shell_id in PROMO_SHELLS and score >= 2:
        fit_mode = "direct_fit"
    elif shell_id in PROMO_SHELLS and score >= 1:
        fit_mode = "shell_fit"
    elif shell_id == "urban_supernatural" and score >= 1:
        fit_mode = "shell_fit"
    else:
        fit_mode = "out_of_scope"
    secret_class = _secret_class(seed, shell_id)
    return SeedFingerprint(
        public_shell_id=shell_id,
        fit_mode=fit_mode,
        arena_type=_arena_type(seed, shell_id),
        secret_class=secret_class,
        relationship_geometry=_relationship_geometry(seed, shell_id),
        cost_class=_cost_class(seed, shell_id),
        public_bomb_family=_bomb_family(secret_class, shell_id),
        play_length_preset=play_length_preset,  # type: ignore[arg-type]
        protagonist_identity_class=_protagonist_identity_class(seed, shell_id),
        tone_bias=_tone_bias(seed, shell_id),
        route_preference_bias=_route_preference_bias(seed),
        source_markers=[keyword for keyword in _SHELL_KEYWORDS[shell_id] if keyword in seed][:10],
    )


TEMPLATE_LIBRARY: tuple[HeroTemplateSpec | LightTemplateSpec, ...] = (
    HeroTemplateSpec(
        template_id="wealth_banquet_will_flip",
        shell_id="wealth_families",
        allowed_arena_types=["family_banquet", "engagement_banquet"],
        allowed_secret_classes=["will_evidence", "hidden_heir"],
        allowed_relationship_geometries=["fiance_oldlove_lawyer", "heir_oldlove_secret_keeper"],
        allowed_cost_classes=["marriage_face", "inheritance_status"],
        allowed_bomb_families=["evidence_drop"],
        route_promise_verb_set=["护谁", "站谁", "拆谁", "先卖谁"],
        target_archetype_mix=["联姻对象", "旧爱", "律师/掌局人"],
        relationship_setup_template="主角被夹在名义上的亲密对象、最不该回来的旧情和握着证据的人之间。",
        share_hook_template="一桌人全在装体面，但真正决定继承顺位的秘密已经要被抬上桌。",
        route_promise_template="你要在{arena}彻底失控前，先护住谁的体面、先站到谁那边，再决定要不要把{secret}当众翻出来。",
        bomb_moment_template="在{arena}最安静的那一秒，{secret}被直接甩上桌，最体面的那个人当场失控。",
        cost_of_truth_template="真相一旦说破，你会一起赔上{cost}，再也回不到那张桌子的安全位置。",
        tone_example_pack=_TONE_PACKS["wealth_banquet_will_flip"],
    ),
    HeroTemplateSpec(
        template_id="wealth_engagement_sideswitch",
        shell_id="wealth_families",
        allowed_arena_types=["engagement_banquet"],
        allowed_secret_classes=["will_evidence", "hidden_heir"],
        allowed_relationship_geometries=["fiance_oldlove_lawyer"],
        allowed_cost_classes=["marriage_face", "inheritance_status"],
        allowed_bomb_families=["side_switch", "evidence_drop"],
        route_promise_verb_set=["站谁", "护谁", "嫁不嫁", "拆谁"],
        target_archetype_mix=["联姻对象", "旧爱", "律师/证据人"],
        relationship_setup_template="主角明面上要完成联姻，暗地里却被旧情和证据一起逼着重新站队。",
        share_hook_template="订婚宴不是定终身，是看谁先倒戈、谁先把牌桌掀翻。",
        route_promise_template="你要在{arena}变成站队现场前，先护谁留在主位、先逼谁开口，再决定这场联姻还结不结。",
        bomb_moment_template="在{arena}最该微笑敬酒的时候，{secret}被说破，原本该站你的人先当众倒戈。",
        cost_of_truth_template="你一旦翻牌，赔上的不只是{cost}，还有今晚所有人默认你该认命的那条路。",
        tone_example_pack=_TONE_PACKS["wealth_engagement_sideswitch"],
    ),
    HeroTemplateSpec(
        template_id="wealth_inheritance_evidence_drop",
        shell_id="wealth_families",
        allowed_arena_types=["family_banquet", "will_reading"],
        allowed_secret_classes=["will_evidence", "hidden_heir"],
        allowed_relationship_geometries=["heir_oldlove_secret_keeper"],
        allowed_cost_classes=["inheritance_status"],
        allowed_bomb_families=["evidence_drop"],
        route_promise_verb_set=["站谁", "护谁", "先揭谁", "先毁谁"],
        target_archetype_mix=["继承人", "旧爱", "证据持有者"],
        relationship_setup_template="主角被继承战最核心的两股关系力量夹住，只要偏一句就会改写顺位。",
        share_hook_template="继承局最狠的不是钱，是你护住一个人，就等于亲手把另一个人踢出局。",
        route_promise_template="你要在{arena}宣布站队前，先护住谁的顺位、先逼谁承认旧账，再决定要不要把{secret}扔到所有人面前。",
        bomb_moment_template="在{arena}所有人都以为胜负已定的时候，{secret}被当众摔出来，继承顺位一秒翻盘。",
        cost_of_truth_template="真相说破以后，你会同时失去{cost}，连最想保住的人也会被拖进审判里。",
        tone_example_pack=_TONE_PACKS["wealth_inheritance_evidence_drop"],
    ),
    HeroTemplateSpec(
        template_id="wealth_private_heir_return",
        shell_id="wealth_families",
        allowed_arena_types=["family_banquet", "will_reading"],
        allowed_secret_classes=["hidden_heir", "will_evidence"],
        allowed_relationship_geometries=["heir_oldlove_secret_keeper"],
        allowed_cost_classes=["inheritance_status", "marriage_face"],
        allowed_bomb_families=["side_switch", "evidence_drop"],
        route_promise_verb_set=["护谁", "认不认", "站谁", "先卖谁"],
        target_archetype_mix=["私生身份回潮者", "旧爱", "掌局人"],
        relationship_setup_template="主角被突然回潮的身世真相和还没死透的旧情一起拉回那张豪门桌子。",
        share_hook_template="最不该出现的人回来了，所有人都在逼主角重新选边。",
        route_promise_template="你要在{arena}认亲翻桌前，先护谁留在局里、先认谁才算自己人，再决定要不要让{secret}继续藏着。",
        bomb_moment_template="在{arena}最讲血统体面的那一刻，那段录音被当众公开放出，{secret}被直接说破，最想维持体面的那群人瞬间全场失态。",
        cost_of_truth_template="一旦翻开底牌，你会把{cost}一起赔进去，之后没人还能假装这局没变过。",
        tone_example_pack=_TONE_PACKS["wealth_private_heir_return"],
    ),
    HeroTemplateSpec(
        template_id="office_board_vote_blackledger",
        shell_id="office_power",
        allowed_arena_types=["board_vote"],
        allowed_secret_classes=["black_ledger"],
        allowed_relationship_geometries=["boss_rival_legal"],
        allowed_cost_classes=["career_position", "career_reputation"],
        allowed_bomb_families=["vote_reveal"],
        route_promise_verb_set=["护谁", "逼谁", "站谁", "先卖谁"],
        target_archetype_mix=["上位者", "对手", "法务/兜底者"],
        relationship_setup_template="主角被上位者、竞争对手和最懂规则的人一起拖进董事会前夜的站队局。",
        share_hook_template="不是谁更会开会，而是谁敢先把能让人下台的东西翻出来。",
        route_promise_template="你要在{arena}落票前，先护谁留在牌桌上、先逼谁当众表态，再决定要不要把{secret}交出来。",
        bomb_moment_template="在{arena}最讲规矩的一秒，{secret}被直接摔到桌上，最稳的人也被逼得当众失态。",
        cost_of_truth_template="你一旦说破，就会一起赔上{cost}，以后再没人把你当成还能回头的那种人。",
        tone_example_pack=_TONE_PACKS["office_board_vote_blackledger"],
    ),
    HeroTemplateSpec(
        template_id="office_merger_scapegoat",
        shell_id="office_power",
        allowed_arena_types=["merger_close"],
        allowed_secret_classes=["black_ledger"],
        allowed_relationship_geometries=["power_circle_oldally"],
        allowed_cost_classes=["career_position", "career_reputation"],
        allowed_bomb_families=["vote_reveal"],
        route_promise_verb_set=["扛雷", "救谁", "卖谁", "站谁"],
        target_archetype_mix=["掌权者", "旧同盟", "危险合作方"],
        relationship_setup_template="并购收口前，主角手里的脏证据足够救一个人，也足够直接送一个人出局。",
        share_hook_template="这局最狠的不是黑账，是所有人都默认最后要有人背锅。",
        route_promise_template="你要在{arena}收口前，先替谁扛雷、先救谁留在局里，再决定最后把谁推出去背锅。",
        bomb_moment_template="在{arena}本该收尾的那一刻，{secret}被当众翻开，所有人立刻开始抢着甩锅。",
        cost_of_truth_template="一旦翻牌，你会把{cost}一起压上去，之后这家公司里没人会再把你当安全牌。",
        tone_example_pack=_TONE_PACKS["office_merger_scapegoat"],
    ),
    HeroTemplateSpec(
        template_id="office_launch_contract_flip",
        shell_id="office_power",
        allowed_arena_types=["launch_event"],
        allowed_secret_classes=["contract_flip", "black_ledger"],
        allowed_relationship_geometries=["power_circle_oldally"],
        allowed_cost_classes=["career_reputation", "career_position"],
        allowed_bomb_families=["launch_crash"],
        route_promise_verb_set=["护谁", "先毁谁", "先救谁", "站谁"],
        target_archetype_mix=["掌权者", "合作方", "旧同盟"],
        relationship_setup_template="发布会前，主角被掌权者、危险合作方和旧同盟一起逼到只能先保一个。",
        share_hook_template="台上还在讲愿景，台下已经有人准备让整场发布会当众翻车。",
        route_promise_template="你要在{arena}正式开始前，先护谁别被拖下台、先毁谁的计划，再决定要不要把{secret}掀给所有人看。",
        bomb_moment_template="在{arena}灯最亮的时候，{secret}被突然翻出来，整场发布会当场翻车。",
        cost_of_truth_template="真相一旦见光，你会连{cost}一起赔进去，连最想保住的合作也会断掉。",
        tone_example_pack=_TONE_PACKS["office_launch_contract_flip"],
    ),
    HeroTemplateSpec(
        template_id="office_promotion_side_betrayal",
        shell_id="office_power",
        allowed_arena_types=["promotion_review", "board_vote"],
        allowed_secret_classes=["black_ledger", "contract_flip"],
        allowed_relationship_geometries=["power_circle_oldally"],
        allowed_cost_classes=["career_position"],
        allowed_bomb_families=["side_switch", "vote_reveal"],
        route_promise_verb_set=["站谁", "护谁", "先卖谁", "先逼谁"],
        target_archetype_mix=["上位者", "旧同盟", "对家/合作方"],
        relationship_setup_template="升职局里最危险的不是对家，而是那个你以为还会护你的旧同盟。",
        share_hook_template="表面是升职，实质是每个人都在挑谁先被踢出局。",
        route_promise_template="你要在{arena}定升降前，先站到谁那边、先护谁别被卖掉，再决定是不是要先把{secret}翻出来。",
        bomb_moment_template="在{arena}正式投票前的当众表态时刻，{secret}被直接说破，旧同盟第一个公开倒戈，把你推成全场最先失态的人。",
        cost_of_truth_template="一旦翻牌，你会把{cost}一起搭进去，以后所有升职局都会记住你今天站了哪边。",
        tone_example_pack=_TONE_PACKS["office_promotion_side_betrayal"],
    ),
    LightTemplateSpec(
        template_id="entertainment_awards_scandal",
        shell_id="entertainment_scandal",
        allowed_arena_types=["awards_backstage"],
        allowed_secret_classes=["scandal_video"],
        allowed_relationship_geometries=["idol_manager_ex"],
        allowed_cost_classes=["public_reputation"],
        allowed_bomb_families=["hotsearch_flip"],
        route_promise_verb_set=["护谁", "保谁", "先撕谁", "先爆谁"],
        target_archetype_mix=["顶流", "经纪人", "旧绯闻对象"],
        relationship_setup_template="镜头内外，主角被顶流、经纪体系和旧绯闻一起拖进公开翻车边缘。",
        share_hook_template="一旦热搜失控，最会演的人也会先露出真脸。",
        route_promise_template="你要在{arena}变成热搜前，先护谁留在镜头里、先保谁不背锅，再决定先把谁的伪装撕开。",
        bomb_moment_template="在{arena}所有镜头都对准的时候，{secret}被推上台面，最会控场的人也当场翻车。",
        cost_of_truth_template="一旦真相见光，你会一起赔上{cost}，连最想保住的关系都要陪着掉下去。",
        tone_example_pack=_TONE_PACKS["entertainment_awards_scandal"],
    ),
    LightTemplateSpec(
        template_id="entertainment_livestream_hotsearch_flip",
        shell_id="entertainment_scandal",
        allowed_arena_types=["livestream_room"],
        allowed_secret_classes=["scandal_video"],
        allowed_relationship_geometries=["idol_manager_ex"],
        allowed_cost_classes=["public_reputation"],
        allowed_bomb_families=["hotsearch_flip"],
        route_promise_verb_set=["保谁", "护谁", "先爆谁", "先卖谁"],
        target_archetype_mix=["顶流", "经纪人", "旧绯闻对象"],
        relationship_setup_template="直播镜头一开，主角就被顶流、经纪人和旧绯闻一起逼到只能先保一个。",
        share_hook_template="最狠的不是热搜本身，是所有人都知道镜头不会给你第二次解释机会。",
        route_promise_template="你要在{arena}彻底炸上热搜前，先保谁留在镜头里、先护谁不被卖掉，再决定先把{secret}爆给谁看。",
        bomb_moment_template="在{arena}最该控节奏的那一秒，{secret}被硬生生顶上公屏，最会做直播的人也当场失控。",
        cost_of_truth_template="真相一旦见光，你会把{cost}一起赔进去，连镜头前那点体面都保不住。",
        tone_example_pack=_TONE_PACKS["entertainment_livestream_hotsearch_flip"],
    ),
    LightTemplateSpec(
        template_id="entertainment_variety_blackmail_flip",
        shell_id="entertainment_scandal",
        allowed_arena_types=["variety_set"],
        allowed_secret_classes=["scandal_video"],
        allowed_relationship_geometries=["idol_manager_ex"],
        allowed_cost_classes=["public_reputation"],
        allowed_bomb_families=["hotsearch_flip"],
        route_promise_verb_set=["护谁", "保谁", "先撕谁", "先爆谁"],
        target_archetype_mix=["顶流", "经纪人", "黑料持有人"],
        relationship_setup_template="综艺录制夜里，主角被顶流、经纪体系和黑料持有人一起拖进镜头内外的双线修罗场。",
        share_hook_template="最危险的不是节目效果，是有人准备用黑料逼你在镜头前先失态。",
        route_promise_template="你要在{arena}录到最狠的一段前，先护谁别被当靶子、先保谁不先翻车，再决定先把{secret}撕给谁看。",
        bomb_moment_template="在{arena}灯还亮着的时候，{secret}被人顺手送上台面，最会演无事发生的人也只能当场破功。",
        cost_of_truth_template="真相一旦见光，你会连{cost}一起赔进去，连节目外那层关系也会跟着断。",
        tone_example_pack=_TONE_PACKS["entertainment_variety_blackmail_flip"],
    ),
    LightTemplateSpec(
        template_id="campus_homecoming_recording",
        shell_id="campus_romance",
        allowed_arena_types=["homecoming_stage"],
        allowed_secret_classes=["old_recording"],
        allowed_relationship_geometries=["scholarship_ex_recording"],
        allowed_cost_classes=["scholarship_future"],
        allowed_bomb_families=["recording_drop"],
        route_promise_verb_set=["护谁", "站谁", "先揭谁", "先逼谁"],
        target_archetype_mix=["前任", "竞争者", "录音持有人"],
        relationship_setup_template="主角被前任、竞争者和那份录音一起逼到必须公开站队。",
        share_hook_template="每个人都在装没事，但那份录音只要响一秒，整场面子都会碎。",
        route_promise_template="你要在{arena}翻车前，先护谁别被舆论吞掉、先站到谁那边，再决定要不要把{secret}直接放出来。",
        bomb_moment_template="在{arena}最热闹的公开环节，录音被外放到全场都听见，所有人瞬间盯住台上的人，最会装体面的人当众失态，连奖学金和前途都一起开始失控。",
        cost_of_truth_template="真相一旦见光，你会一起赔上{cost}，连最想保住的未来名额都得重来。",
        tone_example_pack=_TONE_PACKS["campus_homecoming_recording"],
    ),
    LightTemplateSpec(
        template_id="campus_mentor_review_sideswitch",
        shell_id="campus_romance",
        allowed_arena_types=["mentor_review"],
        allowed_secret_classes=["old_recording"],
        allowed_relationship_geometries=["scholarship_ex_recording"],
        allowed_cost_classes=["scholarship_future"],
        allowed_bomb_families=["recording_drop"],
        route_promise_verb_set=["护谁", "站谁", "先逼谁", "先卖谁"],
        target_archetype_mix=["前任", "竞争者", "评审风向持有人"],
        relationship_setup_template="导师评审周里，主角被前任、竞争者和最懂风向的人一起逼到必须站边。",
        share_hook_template="最狠的不是评审标准，是所有人都知道那份录音一响，名额就会直接换手。",
        route_promise_template="你要在{arena}正式定名额前，先护谁不被拖下去、先站到谁那边，再决定先逼谁认下{secret}。",
        bomb_moment_template="在{arena}最讲规矩的公开环节，{secret}被直接外放出来，所有人一起盯住你们，最会装冷静的人先当众失态。",
        cost_of_truth_template="真相一旦见光，你会把{cost}一起赔进去，连最想守住的名额都不再稳。",
        tone_example_pack=_TONE_PACKS["campus_mentor_review_sideswitch"],
    ),
    LightTemplateSpec(
        template_id="campus_club_campaign_flip",
        shell_id="campus_romance",
        allowed_arena_types=["club_event"],
        allowed_secret_classes=["old_recording"],
        allowed_relationship_geometries=["scholarship_ex_recording"],
        allowed_cost_classes=["scholarship_future"],
        allowed_bomb_families=["recording_drop"],
        route_promise_verb_set=["护谁", "站谁", "先揭谁", "先卖谁"],
        target_archetype_mix=["竞争者", "录音持有人", "站队组织者"],
        relationship_setup_template="社团庆功夜里，主角被竞争者、录音持有人和最会带风向的人一起推向公开站队边缘。",
        share_hook_template="这局最危险的不是竞选结果，而是谁先把那份录音放给所有人听。",
        route_promise_template="你要在{arena}彻底翻车前，先护谁别被舆论吃掉、先站到谁那边，再决定先把{secret}揭给谁看。",
        bomb_moment_template="在{arena}最热闹的时候，{secret}被突然外放到全场都听见，原本还在装没事的人立刻一起变了脸。",
        cost_of_truth_template="真相一旦见光，你会连{cost}一起赔进去，之后谁都不会再把你当成还能中立的人。",
        tone_example_pack=_TONE_PACKS["campus_club_campaign_flip"],
    ),
    LightTemplateSpec(
        template_id="urban_supernatural_legacy_contract",
        shell_id="urban_supernatural",
        allowed_arena_types=["night_clubfront"],
        allowed_secret_classes=["legacy_contract_secret"],
        allowed_relationship_geometries=["legacy_danger_ally"],
        allowed_cost_classes=["legacy_normal_life"],
        allowed_bomb_families=["legacy_contract_exposure"],
        route_promise_verb_set=["护谁", "信谁", "先揭谁", "先卖谁"],
        target_archetype_mix=["危险知情者", "旧债对象", "夜色盟友"],
        relationship_setup_template="主角被危险知情者、旧债对象和一份不能公开的契约一起拖进夜色里。",
        share_hook_template="这局不是为了宣发主线，而是保留一条内部可用的危险关系戏。",
        route_promise_template="你要在{arena}彻底失控前，先信谁、先护谁，再决定要不要把{secret}拖进现实。",
        bomb_moment_template="在{arena}人群最密的时候，{secret}被硬生生拖进现实，所有人都看见了不该看的东西。",
        cost_of_truth_template="一旦翻牌，你会把{cost}一起烧掉，之后再也回不到正常生活那条线上。",
        tone_example_pack=_TONE_PACKS["urban_supernatural_legacy_contract"],
    ),
)


def _score_template(fingerprint: SeedFingerprint, template: HeroTemplateSpec | LightTemplateSpec) -> int:
    score = 0
    if template.shell_id == fingerprint.public_shell_id:
        score += 5
    if fingerprint.arena_type in template.allowed_arena_types:
        score += 4
    if fingerprint.secret_class in template.allowed_secret_classes:
        score += 4
    if fingerprint.relationship_geometry in template.allowed_relationship_geometries:
        score += 4
    if fingerprint.cost_class in template.allowed_cost_classes:
        score += 3
    if fingerprint.public_bomb_family in template.allowed_bomb_families:
        score += 3
    if fingerprint.route_preference_bias == "side" and any(token in template.route_promise_verb_set for token in ("站谁", "扛雷", "表态")):
        score += 1
    if fingerprint.route_preference_bias == "burst" and any(token in template.route_promise_verb_set for token in ("先揭谁", "先撕谁", "先爆谁")):
        score += 1
    return score


_TEMPLATE_HINT_WEIGHTS: dict[ConflictTemplateId, tuple[tuple[str, int], ...]] = {
    "wealth_banquet_will_flip": (("婚约", 3), ("家宴", 2), ("联姻", 1)),
    "wealth_engagement_sideswitch": (("婚约", 3), ("联姻", 2), ("遗嘱", 2)),
    "wealth_inheritance_evidence_drop": (("继承", 3), ("遗嘱", 1)),
    "wealth_private_heir_return": (("私生", 3), ("继承人", 2), ("遗嘱", 1)),
    "office_board_vote_blackledger": (("董事会", 3), ("法务", 3), ("黑账", 2)),
    "office_merger_scapegoat": (("并购", 2), ("上司", 1)),
    "office_launch_contract_flip": (("发布会", 3), ("黑账", 1)),
    "office_promotion_side_betrayal": (("升职", 3), ("空降", 2), ("董事会", 1)),
    "entertainment_awards_scandal": (("颁奖礼", 3), ("热搜", 1), ("经纪人", 1)),
    "entertainment_livestream_hotsearch_flip": (("直播", 3), ("热搜", 2)),
    "entertainment_variety_blackmail_flip": (("综艺", 3), ("黑料", 2), ("顶流", 1)),
    "campus_homecoming_recording": (("校庆", 3), ("录音", 2), ("前任", 1)),
    "campus_mentor_review_sideswitch": (("导师", 3), ("评审", 3), ("奖学金", 2)),
    "campus_club_campaign_flip": (("社团", 3), ("站队", 2)),
    "urban_supernatural_legacy_contract": (("契约", 3), ("异能", 2), ("怪谈", 1)),
}


def _route_bias_hit(fingerprint: SeedFingerprint, template: HeroTemplateSpec | LightTemplateSpec) -> int:
    if fingerprint.route_preference_bias == "side" and any(token in template.route_promise_verb_set for token in ("站谁", "扛雷", "表态")):
        return 1
    if fingerprint.route_preference_bias == "burst" and any(token in template.route_promise_verb_set for token in ("先揭谁", "先撕谁", "先爆谁")):
        return 1
    return 0


def _template_hint_affinity(fingerprint: SeedFingerprint, template: HeroTemplateSpec | LightTemplateSpec) -> int:
    weights = _TEMPLATE_HINT_WEIGHTS.get(template.template_id, ())
    if not weights or not fingerprint.source_markers:
        return 0
    marker_values = tuple(str(marker) for marker in fingerprint.source_markers)
    return sum(weight for token, weight in weights if any(token in marker for marker in marker_values))


def _template_hint_hits(fingerprint: SeedFingerprint, template: HeroTemplateSpec | LightTemplateSpec) -> list[str]:
    weights = _TEMPLATE_HINT_WEIGHTS.get(template.template_id, ())
    if not weights or not fingerprint.source_markers:
        return []
    marker_values = tuple(str(marker) for marker in fingerprint.source_markers)
    return [token for token, _weight in weights if any(token in marker for marker in marker_values)]


def _axis_hit_priority(fingerprint: SeedFingerprint, template: HeroTemplateSpec | LightTemplateSpec) -> tuple[int, int, int, int, int, int]:
    return (
        int(fingerprint.secret_class in template.allowed_secret_classes),
        int(fingerprint.relationship_geometry in template.allowed_relationship_geometries),
        int(fingerprint.arena_type in template.allowed_arena_types),
        int(fingerprint.public_bomb_family in template.allowed_bomb_families),
        int(fingerprint.cost_class in template.allowed_cost_classes),
        _route_bias_hit(fingerprint, template),
    )


def _template_specificity(template: HeroTemplateSpec | LightTemplateSpec) -> int:
    # Fewer allowed dimensions means a more specific template and should win ties.
    total = (
        len(template.allowed_arena_types)
        + len(template.allowed_secret_classes)
        + len(template.allowed_relationship_geometries)
        + len(template.allowed_cost_classes)
        + len(template.allowed_bomb_families)
    )
    return max(0, 40 - total)


def _axis_hit_labels(fingerprint: SeedFingerprint, template: HeroTemplateSpec | LightTemplateSpec) -> list[str]:
    labels: list[str] = []
    if fingerprint.secret_class in template.allowed_secret_classes:
        labels.append("secret_class")
    if fingerprint.relationship_geometry in template.allowed_relationship_geometries:
        labels.append("relationship_geometry")
    if fingerprint.arena_type in template.allowed_arena_types:
        labels.append("arena_type")
    if fingerprint.public_bomb_family in template.allowed_bomb_families:
        labels.append("public_bomb_family")
    if fingerprint.cost_class in template.allowed_cost_classes:
        labels.append("cost_class")
    if _route_bias_hit(fingerprint, template):
        labels.append("route_preference_bias")
    return labels


def _template_rule_priority(
    fingerprint: SeedFingerprint,
    template: HeroTemplateSpec | LightTemplateSpec,
) -> tuple[int, list[str]]:
    rule_hits: list[str] = []
    priority = 0
    markers = tuple(str(marker) for marker in fingerprint.source_markers)
    has_private_heir_signal = any(
        token in marker
        for marker in markers
        for token in ("私生", "继承人")
    )
    # Wealth flagship private-heir seeds should not collapse to generic inheritance evidence templates.
    if (
        fingerprint.public_shell_id == "wealth_families"
        and fingerprint.secret_class == "hidden_heir"
        and has_private_heir_signal
        and fingerprint.arena_type in {"family_banquet", "will_reading"}
        and fingerprint.play_length_preset in {"15_20", "20_25", "30_45"}
        and template.template_id == "wealth_private_heir_return"
    ):
        priority += 8
        rule_hits.append("wealth_hidden_heir_priority")
    if (
        fingerprint.public_shell_id == "office_power"
        and fingerprint.arena_type == "board_vote"
        and fingerprint.secret_class == "black_ledger"
        and any("董事会" in marker for marker in markers)
        and template.template_id == "office_board_vote_blackledger"
    ):
        priority += 7
        rule_hits.append("office_board_vote_blackledger_priority")
    if (
        fingerprint.public_shell_id == "office_power"
        and fingerprint.arena_type == "merger_close"
        and fingerprint.relationship_geometry == "power_circle_oldally"
        and any("并购" in marker for marker in markers)
        and template.template_id == "office_merger_scapegoat"
    ):
        priority += 7
        rule_hits.append("office_merger_scapegoat_priority")
    if (
        fingerprint.public_shell_id == "campus_romance"
        and fingerprint.arena_type == "homecoming_stage"
        and any("校庆" in marker for marker in markers)
        and template.template_id == "campus_homecoming_recording"
    ):
        priority += 6
        rule_hits.append("campus_homecoming_priority")
    return priority, rule_hits


def _template_decision_scorecard(
    fingerprint: SeedFingerprint,
    template: HeroTemplateSpec | LightTemplateSpec,
) -> dict[str, Any]:
    rule_priority, rule_hits = _template_rule_priority(fingerprint, template)
    base_score = _score_template(fingerprint, template)
    hint_affinity = _template_hint_affinity(fingerprint, template)
    axis_priority = _axis_hit_priority(fingerprint, template)
    specificity = _template_specificity(template)
    return {
        "template_id": template.template_id,
        "rule_priority": rule_priority,
        "base_score": base_score,
        "hint_affinity": hint_affinity,
        "axis_priority": axis_priority,
        "specificity": specificity,
        "rule_hits": rule_hits,
        "axis_hits": _axis_hit_labels(fingerprint, template),
        "hint_hits": _template_hint_hits(fingerprint, template),
    }


def _scorecard_key(scorecard: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(scorecard["rule_priority"]),
        int(scorecard["base_score"]),
        int(scorecard["hint_affinity"]),
        tuple(int(item) for item in scorecard["axis_priority"]),
        int(scorecard["specificity"]),
        str(scorecard["template_id"]),
    )


def match_story_template_with_trace(
    fingerprint: SeedFingerprint,
) -> tuple[HeroTemplateSpec | LightTemplateSpec, dict[str, Any]]:
    candidates = [template for template in TEMPLATE_LIBRARY if template.shell_id == fingerprint.public_shell_id]
    if not candidates:
        fallback = next(template for template in TEMPLATE_LIBRARY if template.template_id == "urban_supernatural_legacy_contract")
        return fallback, {
            "selected_template_id": fallback.template_id,
            "decision_source": "template_router_deterministic",
            "decision_rule_hits": ["fallback_shell_default"],
            "decision_axis_hits": [],
            "decision_hint_hits": [],
            "candidate_scores": [],
        }
    scored = [_template_decision_scorecard(fingerprint, template) for template in candidates]
    selected_score = max(scored, key=_scorecard_key)
    selected_template = next(
        template for template in candidates if template.template_id == selected_score["template_id"]
    )
    sorted_scores = sorted(scored, key=_scorecard_key, reverse=True)
    return selected_template, {
        "selected_template_id": selected_template.template_id,
        "decision_source": "template_router_deterministic",
        "decision_rule_hits": list(selected_score["rule_hits"])[:16],
        "decision_axis_hits": list(selected_score["axis_hits"])[:16],
        "decision_hint_hits": list(selected_score["hint_hits"])[:16],
        "candidate_scores": [
            {
                "template_id": item["template_id"],
                "rule_priority": item["rule_priority"],
                "base_score": item["base_score"],
                "hint_affinity": item["hint_affinity"],
                "axis_priority": list(item["axis_priority"]),
                "specificity": item["specificity"],
            }
            for item in sorted_scores[:5]
        ],
    }


def match_story_template(fingerprint: SeedFingerprint) -> HeroTemplateSpec | LightTemplateSpec:
    selected, _trace = match_story_template_with_trace(fingerprint)
    return selected


def get_template_spec(template_id: ConflictTemplateId) -> HeroTemplateSpec | LightTemplateSpec:
    return next(template for template in TEMPLATE_LIBRARY if template.template_id == template_id)


def is_hero_template(template_id: ConflictTemplateId) -> bool:
    return template_id in HERO_TEMPLATE_IDS


def seed_fingerprint_summary(fingerprint: SeedFingerprint) -> dict[str, str]:
    return {
        "fit_mode": fingerprint.fit_mode,
        "public_shell_id": fingerprint.public_shell_id,
        "arena_type": fingerprint.arena_type,
        "secret_class": fingerprint.secret_class,
        "relationship_geometry": fingerprint.relationship_geometry,
        "cost_class": fingerprint.cost_class,
        "public_bomb_family": fingerprint.public_bomb_family,
        "protagonist_identity_class": fingerprint.protagonist_identity_class,
        "tone_bias": fingerprint.tone_bias,
        "route_preference_bias": fingerprint.route_preference_bias,
    }


_ARENA_TEXT = {
    "family_banquet": "家宴主桌",
    "engagement_banquet": "订婚宴主桌",
    "will_reading": "遗嘱宣读现场",
    "board_vote": "董事会现场",
    "merger_close": "并购收口会",
    "launch_event": "发布会主舞台",
    "promotion_review": "升职评审会",
    "awards_backstage": "颁奖礼后台",
    "livestream_room": "直播镜头前",
    "variety_set": "综艺录制现场",
    "homecoming_stage": "校庆晚会",
    "mentor_review": "导师评审周",
    "club_event": "社团庆功夜",
    "night_clubfront": "深夜会所外场",
}
_SECRET_TEXT = {
    "will_evidence": "足以改写顺位的遗嘱证据",
    "hidden_heir": "会把名分彻底掀翻的私生身份真相",
    "black_ledger": "足以让人当场下台的并购黑账",
    "contract_flip": "能让整场发布会翻车的合同反转",
    "scandal_video": "会让热搜和关系一起翻车的偷拍视频",
    "old_recording": "会把脸面和未来一起撕开的旧录音",
    "legacy_contract_secret": "会把旧债和现在一起拖进现实的契约真相",
}
_COST_TEXT = {
    "marriage_face": "婚约、名分和整桌人的体面",
    "inheritance_status": "继承顺位、家族位置和最后那点体面",
    "career_position": "位置、升职机会和牌桌上的发言权",
    "career_reputation": "前途、风评和以后还能不能翻身的机会",
    "public_reputation": "名声、热搜和事业退路",
    "scholarship_future": "奖学金、前途和校园里那点脸面",
    "legacy_normal_life": "正常生活、自由和最后一点退路",
}


def render_template_text(template: HeroTemplateSpec | LightTemplateSpec, fingerprint: SeedFingerprint) -> dict[str, str]:
    arena = _ARENA_TEXT[fingerprint.arena_type]
    secret = _SECRET_TEXT[fingerprint.secret_class]
    cost = _COST_TEXT[fingerprint.cost_class]
    return {
        "arena": arena,
        "secret": secret,
        "cost": cost,
        "relationship_setup": trim_text(template.relationship_setup_template, 220),
        "share_hook": trim_text(template.share_hook_template, 180),
        "route_promise": trim_text(template.route_promise_template.format(arena=arena, secret=secret, cost=cost), 220),
        "bomb_moment": trim_text(template.bomb_moment_template.format(arena=arena, secret=secret, cost=cost), 220),
        "cost_of_truth": trim_text(template.cost_of_truth_template.format(arena=arena, secret=secret, cost=cost), 220),
    }
