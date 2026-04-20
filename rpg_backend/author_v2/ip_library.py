from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rpg_backend.author.contracts import StoryShellId
from rpg_backend.author.normalize import trim_text
from rpg_backend.author_v2.contracts import (
    AcceptedBlueprint,
    BoundIPCastMember,
    CastSlotPlan,
    IPCharacterProfile,
    NpcDramaProfile,
    NpcStrategicIntent,
)

_ALL_SHELLS: tuple[StoryShellId, ...] = (
    "wealth_families",
    "entertainment_scandal",
    "office_power",
    "campus_romance",
    "urban_supernatural",
)
_TARGET_GENDER_VALUES = {"male", "female"}

_SECRET_AFFINITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "financial": ("财务", "黑账", "账目", "资金", "并购", "资本", "债务"),
    "identity": ("身份", "替身", "血缘", "继承", "婚约", "私生", "户籍"),
    "old_case": ("旧案", "旧录音", "遗嘱", "证据", "录像", "档案"),
    "public_opinion": ("舆论", "热搜", "直播", "公关", "绯闻", "镜头"),
    "contract": ("合同", "契约", "条款", "背调", "签字"),
    "academic": ("评审", "名额", "竞选", "奖学金", "导师"),
}

_VOICE_REGISTER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "netizen": ("热搜", "直播", "镜头", "评论区", "公关", "路透", "站姐"),
    "elite": ("家宴", "主桌", "继承", "名分", "董事会", "并购"),
    "workplace": ("会议", "部门", "KPI", "汇报", "绩效", "项目"),
    "campus": ("校园", "社团", "评审", "寝室", "导师", "毕业"),
    "streetwise": ("夜场", "酒局", "后台", "包厢", "圈内"),
    "restrained": ("体面", "秩序", "克制", "公私", "规矩"),
}


def _profile(
    *,
    ip_character_id: str,
    display_name: str,
    gender: str,
    charisma_hook: str,
    danger_hook: str,
    speech_pattern: str,
    worldly_desire_type: str,
    taboo_triggers: tuple[str, ...],
    shareable_labels: tuple[str, ...],
    compatible_slot_functions: tuple[str, ...],
    persona_traits: tuple[str, ...],
    catchphrase_pool: tuple[str, ...],
    voice_register_tags: tuple[str, ...],
    secret_affinity_tags: tuple[str, ...],
    disallowed_with: tuple[str, ...] = (),
) -> IPCharacterProfile:
    return IPCharacterProfile(
        ip_character_id=ip_character_id,
        display_name=display_name,
        portrait_asset=f"portraits/urban/{ip_character_id}.jpg",
        charisma_hook=charisma_hook,
        danger_hook=danger_hook,
        speech_pattern=speech_pattern,
        gender=gender,  # type: ignore[arg-type]
        is_adult=True,
        worldly_desire_type=worldly_desire_type,  # type: ignore[arg-type]
        taboo_triggers=list(taboo_triggers[:6]),
        persona_traits=list(persona_traits[:8]),
        catchphrase_pool=list(catchphrase_pool[:6]),
        voice_register_tags=list(voice_register_tags[:8]),
        secret_affinity_tags=list(secret_affinity_tags[:8]),
        shareable_labels=list(shareable_labels[:6]),
        compatible_slot_functions=list(compatible_slot_functions[:6]),  # type: ignore[arg-type]
        compatible_shells=list(_ALL_SHELLS),
        disallowed_with=list(disallowed_with[:6]),
    )


def _legacy_profiles() -> list[IPCharacterProfile]:
    return [
        _profile(
            ip_character_id="lu_jue",
            display_name="陆珏",
            gender="male",
            charisma_hook="冷静、昂贵、像永远不会失控的上位者。",
            danger_hook="一旦体面受损，就会用控制欲把所有人都拖下水。",
            speech_pattern="字少，锋利，习惯把命令包进礼貌。",
            worldly_desire_type="status",
            taboo_triggers=("继承", "婚约", "失控"),
            shareable_labels=("危险未婚夫", "豪门继承人", "失控边缘"),
            compatible_slot_functions=("lead_interest", "rival_interest", "supporting_pressure"),
            persona_traits=("控制欲", "体面优先", "压迫感"),
            catchphrase_pool=("先把账算清。", "你确定要在这里翻脸？", "我不做亏本交换。"),
            voice_register_tags=("elite", "restrained", "workplace"),
            secret_affinity_tags=("identity", "contract", "financial"),
            disallowed_with=("gu_shaoting",),
        ),
        _profile(
            ip_character_id="su_qing",
            display_name="苏清",
            gender="female",
            charisma_hook="她看起来像白月光，但比所有人都更会利用沉默。",
            danger_hook="越温柔，越说明她已经决定让谁输。",
            speech_pattern="声线轻，话里总留半句让人自己补全。",
            worldly_desire_type="love",
            taboo_triggers=("旧爱", "替身", "录像"),
            shareable_labels=("旧爱回归", "白月光", "最会翻旧账的人"),
            compatible_slot_functions=("lead_interest", "hidden_ally", "wildcard"),
            persona_traits=("情绪拿捏", "反差感", "慢热钩子"),
            catchphrase_pool=("我只是想确认你站哪边。", "你真觉得那件事过去了吗？", "别急着给答案。"),
            voice_register_tags=("restrained", "streetwise", "campus"),
            secret_affinity_tags=("identity", "old_case", "public_opinion"),
        ),
        _profile(
            ip_character_id="jiang_ye",
            display_name="江烨",
            gender="male",
            charisma_hook="他有种坏到刚好的危险感，像会先护你再卖你。",
            danger_hook="一旦闻到弱点，就会把局面推向不可收拾。",
            speech_pattern="说话半真半假，喜欢把威胁伪装成玩笑。",
            worldly_desire_type="money",
            taboo_triggers=("资源", "债务", "偷拍视频"),
            shareable_labels=("危险盟友", "笑着捅刀", "资源操盘手"),
            compatible_slot_functions=("rival_interest", "supporting_pressure", "wildcard"),
            persona_traits=("资源型", "投机", "赌徒心态"),
            catchphrase_pool=("这局我可以帮你，但要加价。", "你先站边，我再亮底牌。", "别把退路烧得太快。"),
            voice_register_tags=("streetwise", "workplace", "netizen"),
            secret_affinity_tags=("financial", "public_opinion", "contract"),
        ),
        _profile(
            ip_character_id="xu_zhiyao",
            display_name="许知遥",
            gender="female",
            charisma_hook="她一开口就让所有秘密都像被归档了一样。",
            danger_hook="掌握证据的人，永远可以最后一个出手。",
            speech_pattern="条理清楚，不抬音量，但句句都有落点。",
            worldly_desire_type="control",
            taboo_triggers=("遗嘱", "合同", "证据链"),
            shareable_labels=("冷面律师", "证据女王", "最后出牌的人"),
            compatible_slot_functions=("secret_keeper", "hidden_ally", "public_witness"),
            persona_traits=("证据洁癖", "审讯感", "边界清晰"),
            catchphrase_pool=("证据不会替任何人说谎。", "你要的不是解释，是免责。", "现在翻供已经晚了。"),
            voice_register_tags=("workplace", "restrained", "elite"),
            secret_affinity_tags=("old_case", "contract", "identity"),
        ),
        _profile(
            ip_character_id="shen_moran",
            display_name="沈墨然",
            gender="male",
            charisma_hook="镜头越亮，他越像一场公开事故。",
            danger_hook="只要舆论开始发酵，他就会把私人情感也变成公共武器。",
            speech_pattern="媒体感很强，擅长把真心说得像声明。",
            worldly_desire_type="status",
            taboo_triggers=("热搜", "绯闻", "代言"),
            shareable_labels=("顶流男主", "热搜体质", "公开翻车"),
            compatible_slot_functions=("lead_interest", "public_witness", "wildcard"),
            persona_traits=("镜头饥渴", "情绪放大", "公关直觉"),
            catchphrase_pool=("镜头不会等你准备好。", "这句一出就是热搜第一。", "现在删稿也来不及。"),
            voice_register_tags=("netizen", "streetwise", "elite"),
            secret_affinity_tags=("public_opinion", "identity", "old_case"),
        ),
        _profile(
            ip_character_id="qiao_lin",
            display_name="乔琳",
            gender="female",
            charisma_hook="她像最靠谱的经纪人，也像最知道你会在哪一步崩的人。",
            danger_hook="当她开始替你处理舆论，就是她准备替你决定命运的时候。",
            speech_pattern="快、准、职业，但会在最冷静时说最狠的话。",
            worldly_desire_type="control",
            taboo_triggers=("公关", "黑料", "录音"),
            shareable_labels=("铁血经纪人", "职业强控", "黑料处理者"),
            compatible_slot_functions=("hidden_ally", "supporting_pressure", "secret_keeper"),
            persona_traits=("执行力", "风控", "控制情绪"),
            catchphrase_pool=("先控评，再谈情绪。", "你现在需要的是方案，不是解释。", "这条口径只说一次。"),
            voice_register_tags=("netizen", "campus", "restrained"),
            secret_affinity_tags=("old_case", "public_opinion", "academic"),
        ),
        _profile(
            ip_character_id="gu_shaoting",
            display_name="顾少廷",
            gender="male",
            charisma_hook="他是会被所有人自动让出位置的那种掌权者。",
            danger_hook="他最擅长把感情包装成交换条件。",
            speech_pattern="慢、稳、压迫感强，习惯让别人先表态。",
            worldly_desire_type="status",
            taboo_triggers=("并购", "董事会", "站队"),
            shareable_labels=("掌权上司", "控制系上位者", "冷面总裁"),
            compatible_slot_functions=("lead_interest", "rival_interest", "supporting_pressure"),
            persona_traits=("掌控局势", "交换逻辑", "强支配"),
            catchphrase_pool=("我要的是结果，不是过程。", "你先说立场。", "这桌子不是谁都坐得稳。"),
            voice_register_tags=("elite", "workplace", "restrained"),
            secret_affinity_tags=("financial", "contract", "identity"),
            disallowed_with=("lu_jue",),
        ),
        _profile(
            ip_character_id="lin_yuchu",
            display_name="林语初",
            gender="female",
            charisma_hook="她永远像最值得信任的人，这正是危险所在。",
            danger_hook="她会为了保住自己想要的未来，先一步把你推成坏人。",
            speech_pattern="看起来真诚，真正关键的话却从不一次说完。",
            worldly_desire_type="identity",
            taboo_triggers=("奖学金", "竞选", "导师"),
            shareable_labels=("校园白切黑", "最会装无辜的人", "清纯反杀"),
            compatible_slot_functions=("lead_interest", "rival_interest", "public_witness"),
            persona_traits=("伪无害", "算账慢热", "人设经营"),
            catchphrase_pool=("我只是想把话说清楚。", "你确定要让我当众回答吗？", "你以为我不知道吗？"),
            voice_register_tags=("campus", "restrained", "netizen"),
            secret_affinity_tags=("academic", "identity", "public_opinion"),
        ),
        _profile(
            ip_character_id="zhou_jin",
            display_name="周瑾",
            gender="male",
            charisma_hook="他看起来像救场的人，实际总在挑你最软的地方下手。",
            danger_hook="越是在公共场合，他越擅长逼人站队。",
            speech_pattern="表面轻松，实际句句试探底线。",
            worldly_desire_type="revenge",
            taboo_triggers=("旧账", "报复", "公开羞辱"),
            shareable_labels=("复仇前任", "场面搅局者", "逼你站队的人"),
            compatible_slot_functions=("rival_interest", "wildcard", "public_witness"),
            persona_traits=("旧账驱动", "挑衅", "公域作战"),
            catchphrase_pool=("你欠我的，不是一句对不起。", "今晚谁都别装体面。", "你选谁，我就打谁。"),
            voice_register_tags=("streetwise", "netizen", "elite"),
            secret_affinity_tags=("old_case", "public_opinion", "identity"),
        ),
        _profile(
            ip_character_id="ye_qi",
            display_name="叶绮",
            gender="female",
            charisma_hook="她像都市夜色本身，漂亮、神秘、随时会让人越界。",
            danger_hook="她知道每个人最想藏的东西，并且从不白白保密。",
            speech_pattern="暧昧、松弛、带一点像在做交易的温柔。",
            worldly_desire_type="freedom",
            taboo_triggers=("契约", "灵媒", "夜巡"),
            shareable_labels=("都市异能缪斯", "危险知情者", "夜色女主"),
            compatible_slot_functions=("lead_interest", "secret_keeper", "wildcard"),
            persona_traits=("神秘感", "交易直觉", "夜场生存"),
            catchphrase_pool=("想知道真相，先给筹码。", "你欠我的那句真话呢？", "夜里说的话，白天也要算数。"),
            voice_register_tags=("streetwise", "netizen", "restrained"),
            secret_affinity_tags=("old_case", "identity", "contract"),
        ),
    ]


_ARCHETYPES: tuple[dict[str, Any], ...] = (
    {
        "charisma_hook": "他/她总能在最混乱的场面里抢回叙事权。",
        "danger_hook": "一旦被逼到墙角，就会把谈判直接升级成翻桌。",
        "speech_pattern": "句子短、停顿重，像每句话都带着最后通牒。",
        "worldly_desire_type": "status",
        "taboo_triggers": ("主桌", "站队", "继承"),
        "shareable_labels": ("强势上位者", "体面博弈"),
        "compatible_slot_functions": ("lead_interest", "rival_interest", "supporting_pressure"),
        "persona_traits": ("强控制", "体面优先", "冷处理"),
        "catchphrase_pool": ("先把账算清。", "你先给立场。", "别把这局当儿戏。"),
        "voice_register_tags": ("elite", "restrained", "workplace"),
        "secret_affinity_tags": ("identity", "financial", "contract"),
    },
    {
        "charisma_hook": "他/她看似在收场，其实在提前布下一轮反制。",
        "danger_hook": "会把你最怕见光的细节拿来谈条件。",
        "speech_pattern": "职业感强，语速稳，字里行间全是算计。",
        "worldly_desire_type": "control",
        "taboo_triggers": ("口径", "封口", "黑料"),
        "shareable_labels": ("幕后操盘手", "风控专家"),
        "compatible_slot_functions": ("hidden_ally", "secret_keeper", "supporting_pressure"),
        "persona_traits": ("执行力", "风控脑", "低情绪"),
        "catchphrase_pool": ("先控风险，再谈情绪。", "这句不能外传。", "我给你留了退路。"),
        "voice_register_tags": ("workplace", "netizen", "restrained"),
        "secret_affinity_tags": ("public_opinion", "contract", "financial"),
    },
    {
        "charisma_hook": "他/她总能把危机说成机会，让人不自觉上钩。",
        "danger_hook": "笑着给台阶，下一秒就可能抽走地板。",
        "speech_pattern": "玩笑口吻里夹着威胁，半真半假最难拆。",
        "worldly_desire_type": "money",
        "taboo_triggers": ("资源", "债务", "对赌"),
        "shareable_labels": ("机会主义者", "资源掮客"),
        "compatible_slot_functions": ("rival_interest", "wildcard", "supporting_pressure"),
        "persona_traits": ("投机", "机会窗口", "高流动"),
        "catchphrase_pool": ("我只做高赔率选择。", "这局还能再加码。", "先谈交换，再谈感情。"),
        "voice_register_tags": ("streetwise", "workplace", "netizen"),
        "secret_affinity_tags": ("financial", "public_opinion", "old_case"),
    },
    {
        "charisma_hook": "他/她像证据库本身，出现就会改变话语秩序。",
        "danger_hook": "握着最后一张证据牌，随时可以定生死。",
        "speech_pattern": "逻辑闭环明显，几乎不给对方留钻空子。",
        "worldly_desire_type": "control",
        "taboo_triggers": ("证据", "遗嘱", "档案"),
        "shareable_labels": ("证据型角色", "冷面法则"),
        "compatible_slot_functions": ("secret_keeper", "public_witness", "hidden_ally"),
        "persona_traits": ("证据洁癖", "高边界", "延迟出手"),
        "catchphrase_pool": ("证据只认时间线。", "你确定要我公开这份材料？", "这句会写进记录。"),
        "voice_register_tags": ("restrained", "workplace", "elite"),
        "secret_affinity_tags": ("old_case", "contract", "identity"),
    },
    {
        "charisma_hook": "他/她能把温柔用成钩子，让人越界后才发现代价。",
        "danger_hook": "表面示弱，实则把局势一点点拉向自己的主场。",
        "speech_pattern": "声线轻、节奏慢，关键句总在最后半拍。",
        "worldly_desire_type": "love",
        "taboo_triggers": ("旧爱", "替身", "私聊记录"),
        "shareable_labels": ("温柔钩子", "慢热反杀"),
        "compatible_slot_functions": ("lead_interest", "hidden_ally", "wildcard"),
        "persona_traits": ("高共情", "慢推进", "情绪控场"),
        "catchphrase_pool": ("我只是想听你说实话。", "别急着否认。", "你其实一直知道。"),
        "voice_register_tags": ("restrained", "campus", "streetwise"),
        "secret_affinity_tags": ("identity", "old_case", "public_opinion"),
    },
    {
        "charisma_hook": "他/她擅长在公开场合制造不可逆的站队压力。",
        "danger_hook": "只要节奏被点燃，就会把私事拖进公域处刑。",
        "speech_pattern": "话术直接，善用群体视线逼迫表态。",
        "worldly_desire_type": "status",
        "taboo_triggers": ("舆论", "公开道歉", "切割"),
        "shareable_labels": ("公开施压者", "舆论操盘"),
        "compatible_slot_functions": ("public_witness", "supporting_pressure", "rival_interest"),
        "persona_traits": ("公域攻势", "逼表态", "压节奏"),
        "catchphrase_pool": ("现在就说，你站谁。", "观众已经在看了。", "这句不上热搜都难。"),
        "voice_register_tags": ("netizen", "elite", "streetwise"),
        "secret_affinity_tags": ("public_opinion", "financial", "identity"),
    },
    {
        "charisma_hook": "他/她像旧情本身，回来就让所有人重新站位。",
        "danger_hook": "最会把旧账翻成现账，逼你当场偿还。",
        "speech_pattern": "看似怀旧，实际每句都在逼近核心伤口。",
        "worldly_desire_type": "revenge",
        "taboo_triggers": ("旧账", "背叛", "录音"),
        "shareable_labels": ("旧情回流", "复仇线"),
        "compatible_slot_functions": ("wildcard", "rival_interest", "lead_interest"),
        "persona_traits": ("旧账驱动", "高记忆", "边界拉扯"),
        "catchphrase_pool": ("你欠我的还没还。", "这局我回来，不是叙旧。", "你想装没发生过？"),
        "voice_register_tags": ("streetwise", "campus", "netizen"),
        "secret_affinity_tags": ("old_case", "identity", "public_opinion"),
    },
    {
        "charisma_hook": "他/她不抢镜，却总能决定镜头最后对准谁。",
        "danger_hook": "看似中立，关键时刻会给出致命定性。",
        "speech_pattern": "留白多，结论少，但每个词都可被放大引用。",
        "worldly_desire_type": "identity",
        "taboo_triggers": ("背调", "身份错位", "证词"),
        "shareable_labels": ("沉默裁判", "定性型旁观者"),
        "compatible_slot_functions": ("public_witness", "secret_keeper", "supporting_pressure"),
        "persona_traits": ("观察者", "延迟判断", "高可信"),
        "catchphrase_pool": ("我只说我看到的。", "你们都漏看了一件事。", "这句我会记住。"),
        "voice_register_tags": ("restrained", "workplace", "elite"),
        "secret_affinity_tags": ("identity", "old_case", "contract"),
    },
    {
        "charisma_hook": "他/她会先替你挡刀，再问你愿不愿意还债。",
        "danger_hook": "付出从不免费，情感和筹码永远绑在一起。",
        "speech_pattern": "护短语气里带条件，温和但不含糊。",
        "worldly_desire_type": "love",
        "taboo_triggers": ("承诺", "背锅", "切割"),
        "shareable_labels": ("危险盟友", "护短交易"),
        "compatible_slot_functions": ("hidden_ally", "lead_interest", "supporting_pressure"),
        "persona_traits": ("护短", "交换逻辑", "韧性"),
        "catchphrase_pool": ("我可以替你扛，但你别后退。", "这份人情你记账。", "我不会白护你。"),
        "voice_register_tags": ("workplace", "streetwise", "restrained"),
        "secret_affinity_tags": ("contract", "financial", "public_opinion"),
    },
    {
        "charisma_hook": "他/她像不确定性本身，永远带着下一轮反转。",
        "danger_hook": "最擅长在关键节点改写所有人的收益预期。",
        "speech_pattern": "节奏跳跃，常用反问和断句打断对方逻辑。",
        "worldly_desire_type": "freedom",
        "taboo_triggers": ("失控", "越界", "匿名爆料"),
        "shareable_labels": ("反转引擎", "失控变量"),
        "compatible_slot_functions": ("wildcard", "rival_interest", "public_witness"),
        "persona_traits": ("反转驱动", "冒险", "非线性"),
        "catchphrase_pool": ("按你这条线会输得更快。", "你确定要我按规矩来？", "再拖一拍就晚了。"),
        "voice_register_tags": ("netizen", "streetwise", "campus"),
        "secret_affinity_tags": ("public_opinion", "old_case", "identity"),
    },
)

_FEMALE_SEEDS: tuple[tuple[str, str], ...] = (
    ("f_qin_yi", "秦一宁"),
    ("f_song_wan", "宋晚澄"),
    ("f_he_yan", "何妍初"),
    ("f_yuan_xi", "袁溪禾"),
    ("f_qiao_nuo", "乔诺言"),
    ("f_wen_qi", "温绮安"),
    ("f_liang_shu", "梁书晚"),
    ("f_gao_lan", "高岚意"),
    ("f_xie_meng", "谢梦栀"),
    ("f_shao_yu", "邵予棠"),
    ("f_jiang_man", "蒋曼宁"),
    ("f_yu_qing", "郁清妍"),
    ("f_ruan_ge", "阮歌遥"),
    ("f_meng_li", "孟里安"),
    ("f_bai_ning", "白宁夏"),
    ("f_tang_ci", "唐辞月"),
    ("f_cheng_ruo", "程若梨"),
    ("f_han_jing", "韩景书"),
    ("f_xu_mo", "许墨微"),
    ("f_ye_zhou", "叶舟宁"),
    ("f_su_yi", "苏以澜"),
    ("f_lin_qiao", "林乔意"),
    ("f_zhou_ru", "周如歌"),
    ("f_lu_an", "陆安宁"),
    ("f_shen_luo", "沈落棠"),
)

_MALE_SEEDS: tuple[tuple[str, str], ...] = (
    ("m_qin_zhou", "秦舟野"),
    ("m_song_he", "宋鹤川"),
    ("m_he_jing", "何景砚"),
    ("m_yuan_chi", "袁迟屿"),
    ("m_qiao_yan", "乔砚沉"),
    ("m_wen_yu", "温屿承"),
    ("m_liang_mo", "梁墨川"),
    ("m_gao_chen", "高臣越"),
    ("m_xie_shen", "谢深澜"),
    ("m_shao_lin", "邵临川"),
    ("m_jiang_ye", "蒋夜行"),
    ("m_yu_hao", "郁昊礼"),
    ("m_ruan_cheng", "阮承砚"),
    ("m_meng_ye", "孟野舟"),
    ("m_bai_jue", "白决明"),
    ("m_tang_shuo", "唐朔言"),
    ("m_cheng_xi", "程西岚"),
    ("m_han_yu", "韩予川"),
    ("m_xu_jin", "许晋泽"),
    ("m_ye_luo", "叶洛沉"),
    ("m_su_shao", "苏绍珩"),
    ("m_lin_yue", "林越衡"),
    ("m_zhou_qi", "周祁深"),
    ("m_lu_chi", "陆迟安"),
    ("m_shen_bo", "沈泊言"),
)


def _synthetic_profiles() -> list[IPCharacterProfile]:
    output: list[IPCharacterProfile] = []
    for index, (profile_id, name) in enumerate(_FEMALE_SEEDS, start=1):
        archetype = _ARCHETYPES[(index - 1) % len(_ARCHETYPES)]
        disallowed_with: tuple[str, ...] = ()
        if index in {10, 20}:
            disallowed_with = ("su_qing",)
        output.append(
            _profile(
                ip_character_id=profile_id,
                display_name=name,
                gender="female",
                charisma_hook=trim_text(f"{name}{archetype['charisma_hook']}", 180),
                danger_hook=trim_text(f"{name}{archetype['danger_hook']}", 180),
                speech_pattern=archetype["speech_pattern"],
                worldly_desire_type=archetype["worldly_desire_type"],
                taboo_triggers=tuple(archetype["taboo_triggers"]),
                shareable_labels=tuple(archetype["shareable_labels"]),
                compatible_slot_functions=tuple(archetype["compatible_slot_functions"]),
                persona_traits=tuple(archetype["persona_traits"]),
                catchphrase_pool=tuple(archetype["catchphrase_pool"]),
                voice_register_tags=tuple(archetype["voice_register_tags"]),
                secret_affinity_tags=tuple(archetype["secret_affinity_tags"]),
                disallowed_with=disallowed_with,
            )
        )
    for index, (profile_id, name) in enumerate(_MALE_SEEDS, start=1):
        archetype = _ARCHETYPES[(index + 2) % len(_ARCHETYPES)]
        disallowed_with: tuple[str, ...] = ()
        if index in {8, 18}:
            disallowed_with = ("gu_shaoting",)
        output.append(
            _profile(
                ip_character_id=profile_id,
                display_name=name,
                gender="male",
                charisma_hook=trim_text(f"{name}{archetype['charisma_hook']}", 180),
                danger_hook=trim_text(f"{name}{archetype['danger_hook']}", 180),
                speech_pattern=archetype["speech_pattern"],
                worldly_desire_type=archetype["worldly_desire_type"],
                taboo_triggers=tuple(archetype["taboo_triggers"]),
                shareable_labels=tuple(archetype["shareable_labels"]),
                compatible_slot_functions=tuple(archetype["compatible_slot_functions"]),
                persona_traits=tuple(archetype["persona_traits"]),
                catchphrase_pool=tuple(archetype["catchphrase_pool"]),
                voice_register_tags=tuple(archetype["voice_register_tags"]),
                secret_affinity_tags=tuple(archetype["secret_affinity_tags"]),
                disallowed_with=disallowed_with,
            )
        )
    return output


URBAN_IP_LIBRARY: tuple[IPCharacterProfile, ...] = tuple([*_legacy_profiles(), *_synthetic_profiles()])


def profile_by_id() -> dict[str, IPCharacterProfile]:
    return {profile.ip_character_id: profile for profile in URBAN_IP_LIBRARY}


def shell_compatible_profiles(_shell_id: StoryShellId) -> list[IPCharacterProfile]:
    # Phase-1: shell no longer participates in prefilter/ranking.
    return list(URBAN_IP_LIBRARY)


@dataclass(frozen=True)
class SlotCandidate:
    profile: IPCharacterProfile
    score: float
    score_breakdown: dict[str, float]


def _role_slot_fit(profile: IPCharacterProfile, slot: CastSlotPlan) -> float:
    if slot.slot_function not in set(profile.compatible_slot_functions):
        return 0.0
    rank = list(profile.compatible_slot_functions).index(slot.slot_function)
    base = max(0.0, 3.4 - rank * 0.9)
    if slot.route_eligible and slot.slot_function in {"lead_interest", "rival_interest", "wildcard"}:
        base += 0.5
    return base


def _secret_type_fit(profile: IPCharacterProfile, blueprint: AcceptedBlueprint, slot: CastSlotPlan) -> float:
    text = f"{blueprint.taboo_secret} {blueprint.relationship_setup} {slot.secret_pressure}"
    score = 0.0
    for tag in profile.secret_affinity_tags:
        keywords = _SECRET_AFFINITY_KEYWORDS.get(tag, ())
        if any(keyword in text for keyword in keywords):
            score += 1.0
    if score <= 0.0:
        score += sum(0.4 for trigger in profile.taboo_triggers if trigger in text)
    return min(score, 3.0)


def _voice_register_fit(profile: IPCharacterProfile, blueprint: AcceptedBlueprint) -> float:
    text = f"{blueprint.social_arena} {blueprint.share_hook} {blueprint.hook}"
    score = 0.0
    for tag in profile.voice_register_tags:
        keywords = _VOICE_REGISTER_KEYWORDS.get(tag, ())
        if any(keyword in text for keyword in keywords):
            score += 0.8
    return min(score, 2.4)


def _duplicate_penalty(profile: IPCharacterProfile, selected: list[IPCharacterProfile]) -> float:
    if not selected:
        return 0.0
    profile_traits = set(profile.persona_traits)
    penalty = 0.0
    for picked in selected:
        shared_traits = len(profile_traits.intersection(set(picked.persona_traits)))
        penalty += float(shared_traits) * 0.55
        if profile.worldly_desire_type == picked.worldly_desire_type:
            penalty += 0.4
        shared_voice_tags = len(set(profile.voice_register_tags).intersection(set(picked.voice_register_tags)))
        penalty += float(shared_voice_tags) * 0.2
    return min(penalty, 2.4)


def _disallowed_hit(profile: IPCharacterProfile, selected: list[IPCharacterProfile]) -> bool:
    if not selected:
        return False
    if any(profile.ip_character_id in set(picked.disallowed_with) for picked in selected):
        return True
    if any(picked.ip_character_id in set(profile.disallowed_with) for picked in selected):
        return True
    return False


def _hard_filter_profiles(
    slot: CastSlotPlan,
    blueprint: AcceptedBlueprint,
    *,
    selected: list[IPCharacterProfile],
    selected_ids: set[str],
) -> list[IPCharacterProfile]:
    target_gender = blueprint.target_gender_pref
    output: list[IPCharacterProfile] = []
    for profile in URBAN_IP_LIBRARY:
        if profile.ip_character_id in selected_ids:
            continue
        if not profile.is_adult:
            continue
        if target_gender in _TARGET_GENDER_VALUES and profile.gender != target_gender:
            continue
        if slot.slot_function not in set(profile.compatible_slot_functions):
            continue
        if _disallowed_hit(profile, selected):
            continue
        output.append(profile)
    return output


def _rank_profiles_for_slot(
    slot: CastSlotPlan,
    blueprint: AcceptedBlueprint,
    *,
    selected: list[IPCharacterProfile],
    selected_ids: set[str],
    limit: int = 8,
) -> list[SlotCandidate]:
    filtered = _hard_filter_profiles(slot, blueprint, selected=selected, selected_ids=selected_ids)
    ranked: list[SlotCandidate] = []
    for profile in filtered:
        role_slot_fit = _role_slot_fit(profile, slot)
        secret_type_fit = _secret_type_fit(profile, blueprint, slot)
        voice_register_fit = _voice_register_fit(profile, blueprint)
        duplicate_penalty = _duplicate_penalty(profile, selected)
        score = round(role_slot_fit + secret_type_fit + voice_register_fit - duplicate_penalty, 4)
        ranked.append(
            SlotCandidate(
                profile=profile,
                score=score,
                score_breakdown={
                    "role_slot_fit": role_slot_fit,
                    "secret_type_fit": secret_type_fit,
                    "voice_register_fit": voice_register_fit,
                    "duplicate_penalty": duplicate_penalty,
                },
            )
        )
    ranked.sort(
        key=lambda item: (
            -item.score,
            -item.score_breakdown["role_slot_fit"],
            item.profile.ip_character_id,
        )
    )
    return ranked[: max(1, limit)]


def build_slot_candidate_pool(
    cast_slots: list[CastSlotPlan],
    blueprint: AcceptedBlueprint,
    *,
    top_k: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    selected: list[IPCharacterProfile] = []
    selected_ids: set[str] = set()
    output: dict[str, list[dict[str, Any]]] = {}
    for slot in cast_slots:
        ranked = _rank_profiles_for_slot(
            slot,
            blueprint,
            selected=selected,
            selected_ids=selected_ids,
            limit=top_k,
        )
        output[slot.slot_id] = [
            {
                "candidate_index": index,
                "ip_character_id": candidate.profile.ip_character_id,
                "display_name": candidate.profile.display_name,
                "gender": candidate.profile.gender,
                "charisma_hook": candidate.profile.charisma_hook,
                "speech_pattern": candidate.profile.speech_pattern,
                "persona_traits": candidate.profile.persona_traits[:4],
                "catchphrase_pool": candidate.profile.catchphrase_pool[:3],
                "voice_register_tags": candidate.profile.voice_register_tags[:4],
                "secret_affinity_tags": candidate.profile.secret_affinity_tags[:4],
                "score": candidate.score,
                "score_breakdown": {
                    key: round(value, 3) for key, value in candidate.score_breakdown.items()
                },
            }
            for index, candidate in enumerate(ranked)
        ]
        if ranked:
            selected.append(ranked[0].profile)
            selected_ids.add(ranked[0].profile.ip_character_id)
    return output


def shortlist_profiles_for_slot(
    slot: CastSlotPlan,
    blueprint: AcceptedBlueprint,
    *,
    limit: int = 3,
) -> list[IPCharacterProfile]:
    ranked = _rank_profiles_for_slot(
        slot,
        blueprint,
        selected=[],
        selected_ids=set(),
        limit=max(1, limit),
    )
    return [item.profile for item in ranked]


def _selection_reason_from_score(candidate: SlotCandidate, *, source: str) -> str:
    detail = candidate.score_breakdown
    return trim_text(
        (
            f"{source}: role={detail['role_slot_fit']:.2f}, secret={detail['secret_type_fit']:.2f}, "
            f"voice={detail['voice_register_fit']:.2f}, dup_penalty={detail['duplicate_penalty']:.2f}, "
            f"total={candidate.score:.2f}"
        ),
        220,
    )


def _relationship_to_protagonist(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    def _secret_core() -> str:
        text = blueprint.taboo_secret
        for keyword in ("偷拍视频", "旧录音", "遗嘱录音", "黑账", "评审资料", "合同", "证据"):
            if keyword in text:
                return keyword
        return trim_text(text, 32)

    relation_by_slot = {
        "lead_interest": "是那个最容易让主角在最难看的场面里先伸手站过去的人。",
        "rival_interest": f"是会在{blueprint.social_arena}上逼主角站错边的人。",
        "hidden_ally": "表面替主角收场，实际最清楚她哪一步会露怯。",
        "public_witness": "掌握场面风向，能决定主角今晚是体面还是翻车。",
        "secret_keeper": f"知道那份{_secret_core()}真正源头的人。",
        "supporting_pressure": "负责把选择逼成没有退路的那个人。",
        "wildcard": "是不该回到这场局里、却最容易让旧账重燃的人。",
    }
    return trim_text(relation_by_slot[slot.slot_function], 180)


def _archetype_label(slot: CastSlotPlan) -> str:
    return {
        "lead_interest": "primary_temptation",
        "rival_interest": "public_rival",
        "hidden_ally": "dangerous_confidant",
        "public_witness": "social_weather_vane",
        "secret_keeper": "evidence_keeper",
        "supporting_pressure": "pressure_enforcer",
        "wildcard": "old_flame_wildcard",
    }[slot.slot_function]


def _status_need(blueprint: AcceptedBlueprint) -> str:
    return {
        "wealth_families": "保住名分、婚约和家族位置",
        "entertainment_scandal": "保住镜头、热搜位置和商业价值",
        "office_power": "保住位置、前途和牌桌上的发言权",
        "campus_romance": "保住名声、前途和竞争资格",
        "urban_supernatural": "保住体面生活和不被夜色吞掉的退路",
    }[blueprint.story_shell_id]


def _fear(blueprint: AcceptedBlueprint) -> str:
    return {
        "wealth_families": "最怕在众目睽睽下失去体面和继承筹码。",
        "entertainment_scandal": "最怕在镜头前被坐实谎话，连事业一起塌掉。",
        "office_power": "最怕被当众踢出局，从此只剩背锅价值。",
        "campus_romance": "最怕名声和前途一起翻车，被所有人重新定义。",
        "urban_supernatural": "最怕秘密被拖进现实，正常生活再也回不来。",
    }[blueprint.story_shell_id]


def _shame_trigger(blueprint: AcceptedBlueprint, slot: CastSlotPlan) -> str:
    if slot.slot_function in {"lead_interest", "rival_interest"}:
        return f"在{blueprint.social_arena}被当众逼问真实立场。"
    if slot.slot_function == "secret_keeper":
        return f"{blueprint.taboo_secret}被证明和自己直接有关。"
    return f"在{blueprint.social_arena}上失去体面控制权。"


def _breaking_point(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    return {
        "lead_interest": f"当主角在{blueprint.social_arena}上不再选他时，他会先失控。",
        "rival_interest": "当众被抢走位置或立场时，会直接翻脸。",
        "hidden_ally": "当自己替人兜底反而被怀疑时，会立刻反手。",
        "public_witness": "当场面风向不再由自己控制时，会公开补刀。",
        "secret_keeper": "当证据链不再握在自己手里时，会提前出手。",
        "supporting_pressure": "当逼人站队失败时，会把场面往更难收的方向推。",
        "wildcard": "当旧情被证明毫无分量时，会把旧账一起掀翻。",
    }[slot.slot_function]


def _loyalty_bias(slot: CastSlotPlan) -> str:
    return {
        "lead_interest": "protagonist",
        "rival_interest": "self",
        "hidden_ally": "testing",
        "public_witness": "institution",
        "secret_keeper": "self",
        "supporting_pressure": "institution",
        "wildcard": "chaos",
    }.get(slot.slot_function, "self")


def _history_tags(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> list[str]:
    tags = [slot.slot_function]
    if slot.slot_function in {"lead_interest", "wildcard"}:
        tags.append("old_love")
    if slot.slot_function == "hidden_ally":
        tags.append("saved_me_once")
    if blueprint.story_shell_id == "office_power":
        tags.append("public_rival")
    return tags[:8]


def _line_they_wont_cross(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    return {
        "lead_interest": "不会允许自己在公开场合像被挑剩下的人。",
        "rival_interest": "不会接受自己在所有人面前输给主角。",
        "hidden_ally": "不会白白替任何人扛锅。",
        "public_witness": "不会把场面彻底交给别人控制。",
        "secret_keeper": "不会把最后一张证据牌提前交出去。",
        "supporting_pressure": "不会让这场站队变成没有代价的游戏。",
        "wildcard": "不会再无声无息地退场。",
    }[slot.slot_function]


def _build_drama_profile(
    *,
    blueprint: AcceptedBlueprint,
    slot: CastSlotPlan,
    chosen: IPCharacterProfile,
) -> NpcDramaProfile:
    return NpcDramaProfile(
        character_id=chosen.ip_character_id,
        public_role=slot.public_role_hint,
        archetype_label=_archetype_label(slot),
        charisma_hook=chosen.charisma_hook,
        danger_hook=slot.danger_hook,
        speech_pattern=chosen.speech_pattern,
        public_mask=slot.public_mask,
        private_need=trim_text(_relationship_to_protagonist(slot, blueprint), 180),
        status_need=_status_need(blueprint),
        fear=_fear(blueprint),
        shame_trigger=_shame_trigger(blueprint, slot),
        breaking_point=trim_text(_breaking_point(slot, blueprint), 180),
        loyalty_bias=_loyalty_bias(slot),  # type: ignore[arg-type]
        secret_owner_ids=[slot.slot_id, "taboo_secret"][:6],
        history_tags=_history_tags(slot, blueprint),
        line_they_wont_cross=_line_they_wont_cross(slot, blueprint),
    )


def _primary_stake(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    if blueprint.story_shell_id == "wealth_families":
        return "relationship" if slot.route_eligible else "lineage"
    if blueprint.story_shell_id == "office_power":
        return "relationship" if slot.route_eligible else "position"
    if blueprint.story_shell_id == "entertainment_scandal":
        if slot.slot_function in {"public_witness", "supporting_pressure", "secret_keeper"}:
            return "narrative_control"
        return "relationship" if slot.route_eligible else "reputation"
    if blueprint.story_shell_id == "campus_romance":
        return "relationship" if slot.route_eligible else "eligibility"
    return "normal_life"


def _loss_trigger(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    if blueprint.story_shell_id == "entertainment_scandal":
        if slot.slot_function in {"public_witness", "supporting_pressure", "secret_keeper"}:
            return "version_loss"
        return "public_humiliation"
    if blueprint.story_shell_id == "campus_romance":
        return "route_rejection" if slot.route_eligible else "peer_rejection"
    if blueprint.story_shell_id == "wealth_families":
        return "seat_shift" if not slot.route_eligible else "route_rejection"
    if blueprint.story_shell_id == "office_power":
        return "seat_shift"
    return "debt_reopened"


def _public_survival_mode(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    if blueprint.story_shell_id == "entertainment_scandal":
        if slot.slot_function in {"public_witness", "secret_keeper"}:
            return "claim_narrative"
        if slot.slot_function in {"rival_interest", "supporting_pressure"}:
            return "cut_off"
        return "self_preserve" if not slot.route_eligible else "hold_face"
    if blueprint.story_shell_id == "campus_romance":
        if slot.slot_function in {"rival_interest", "supporting_pressure"}:
            return "align_early"
        return "hold_face" if slot.route_eligible else "self_preserve"
    if blueprint.story_shell_id == "office_power":
        if slot.slot_function in {"rival_interest", "supporting_pressure", "public_witness"}:
            return "cut_off"
        return "hold_face"
    if blueprint.story_shell_id == "wealth_families":
        return "align_early" if slot.route_eligible else "hold_face"
    return "self_preserve"


def _debt_memory_bias(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    if slot.slot_function in {"rival_interest", "wildcard"}:
        return "late_payback"
    if slot.slot_function in {"public_witness", "supporting_pressure"}:
        return "scorekeeping"
    if any(token in slot.danger_hook for token in ("翻脸", "掀", "逼", "倒戈")):
        return "flip_now"
    if blueprint.story_shell_id == "entertainment_scandal":
        return "short_term"
    return "scorekeeping"


def _preferred_latent_kind(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    if blueprint.story_shell_id == "entertainment_scandal":
        if slot.slot_function == "secret_keeper":
            return "secret_pressure"
        if slot.slot_function in {"public_witness", "supporting_pressure"}:
            return "public_wave"
        if slot.slot_function == "rival_interest":
            return "npc_action"
        return "relationship_debt"
    if blueprint.story_shell_id == "campus_romance":
        if slot.slot_function in {"rival_interest", "supporting_pressure"}:
            return "npc_action"
        if slot.slot_function == "public_witness":
            return "public_wave"
        return "relationship_debt"
    if blueprint.story_shell_id == "office_power":
        if slot.slot_function in {"rival_interest", "supporting_pressure"}:
            return "npc_action"
        if slot.slot_function == "secret_keeper":
            return "secret_pressure"
        return "relationship_debt"
    if blueprint.story_shell_id == "wealth_families":
        if slot.slot_function == "secret_keeper":
            return "secret_pressure"
        if slot.slot_function in {"public_witness", "supporting_pressure"}:
            return "public_wave"
        return "relationship_debt"
    return "relationship_debt"


def _sensitive_latent_kind(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    loss = _loss_trigger(slot, blueprint)
    if slot.slot_function == "secret_keeper":
        return "secret_pressure"
    if loss in {"public_humiliation", "version_loss"}:
        return "public_wave"
    if loss in {"debt_reopened", "route_rejection", "peer_rejection"}:
        return "relationship_debt"
    if loss == "seat_shift":
        return "npc_action" if blueprint.story_shell_id == "office_power" else "relationship_debt"
    return "relationship_debt"


def _delay_preference(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    bias = _debt_memory_bias(slot, blueprint)
    return "patient_burn" if bias in {"scorekeeping", "late_payback"} else "quick_snap"


def _regression_payoff(slot: CastSlotPlan, blueprint: AcceptedBlueprint) -> str:
    primary_stake = _primary_stake(slot, blueprint)
    if primary_stake in {"relationship"}:
        return "social_isolation"
    if primary_stake in {"position", "eligibility", "lineage"}:
        return "status_loss"
    if primary_stake == "narrative_control":
        return "secret_leak"
    if primary_stake in {"reputation", "normal_life"}:
        return "public_shame"
    return "public_shame"


def _initial_strategic_intent(slot: CastSlotPlan, blueprint: AcceptedBlueprint, chosen: IPCharacterProfile) -> NpcStrategicIntent:
    return NpcStrategicIntent(
        character_id=chosen.ip_character_id,
        primary_stake=_primary_stake(slot, blueprint),  # type: ignore[arg-type]
        loss_trigger=_loss_trigger(slot, blueprint),  # type: ignore[arg-type]
        opportunism_target_ids=[],
        public_survival_mode=_public_survival_mode(slot, blueprint),  # type: ignore[arg-type]
        debt_memory_bias=_debt_memory_bias(slot, blueprint),  # type: ignore[arg-type]
        preferred_latent_kind=_preferred_latent_kind(slot, blueprint),  # type: ignore[arg-type]
        sensitive_latent_kind=_sensitive_latent_kind(slot, blueprint),  # type: ignore[arg-type]
        delay_preference=_delay_preference(slot, blueprint),  # type: ignore[arg-type]
        regression_payoff=_regression_payoff(slot, blueprint),  # type: ignore[arg-type]
        protect_target_ids=[],
        sacrifice_target_ids=[],
    )


def _finalize_strategic_intents(bound: list[BoundIPCastMember], _blueprint: AcceptedBlueprint) -> list[BoundIPCastMember]:
    route_ids = [member.character_id for member in bound if member.is_route_target][:4]
    non_route_ids = [member.character_id for member in bound if not member.is_route_target][:4]

    def _protect_ids(member: BoundIPCastMember) -> list[str]:
        if member.is_route_target:
            return [member.character_id]
        if member.drama_profile.loyalty_bias == "protagonist":
            return route_ids[:1]
        if member.drama_profile.loyalty_bias in {"family", "institution"}:
            institutional = [
                item.character_id
                for item in bound
                if item.slot_function in {"public_witness", "supporting_pressure", "secret_keeper"}
                and item.character_id != member.character_id
            ]
            return institutional[:1] or route_ids[:1]
        if member.drama_profile.loyalty_bias == "testing":
            return route_ids[:1]
        return []

    def _opportunism_ids(member: BoundIPCastMember) -> list[str]:
        if member.is_route_target:
            return [item for item in non_route_ids if item != member.character_id][:2]
        if member.drama_profile.loyalty_bias in {"self", "chaos"}:
            return [item for item in route_ids if item != member.character_id][:2]
        return [item for item in non_route_ids if item != member.character_id][:2]

    def _sacrifice_ids(member: BoundIPCastMember) -> list[str]:
        if member.drama_profile.loyalty_bias in {"self", "chaos"}:
            return [item for item in route_ids if item != member.character_id][:2]
        if member.slot_function in {"rival_interest", "public_witness", "supporting_pressure"}:
            return [item for item in route_ids if item != member.character_id][:2]
        return [item for item in non_route_ids if item != member.character_id][:2]

    finalized: list[BoundIPCastMember] = []
    for member in bound:
        intent = member.strategic_intent.model_copy(
            update={
                "opportunism_target_ids": _opportunism_ids(member)[:3],
                "protect_target_ids": _protect_ids(member)[:3],
                "sacrifice_target_ids": _sacrifice_ids(member)[:3],
            }
        )
        finalized.append(member.model_copy(update={"strategic_intent": intent}))
    return finalized


def bind_slots_to_ip_cast(
    cast_slots: list[CastSlotPlan],
    blueprint: AcceptedBlueprint,
    *,
    preferred_selection_by_slot: dict[str, str] | None = None,
    preferred_reasons_by_slot: dict[str, str] | None = None,
    top_k: int = 8,
) -> list[BoundIPCastMember]:
    selected: list[IPCharacterProfile] = []
    selected_ids: set[str] = set()
    bound: list[BoundIPCastMember] = []
    route_target_budget = blueprint.route_target_count
    preferred_selection = preferred_selection_by_slot or {}
    preferred_reasons = preferred_reasons_by_slot or {}

    for slot in cast_slots:
        ranked = _rank_profiles_for_slot(
            slot,
            blueprint,
            selected=selected,
            selected_ids=selected_ids,
            limit=max(1, top_k),
        )
        if not ranked:
            raise RuntimeError(f"unable to bind slot={slot.slot_id}: no profile passed hard prefilters")

        selected_candidate = None
        preferred_id = preferred_selection.get(slot.slot_id)
        preferred_reason = trim_text(preferred_reasons.get(slot.slot_id, ""), 200)
        if preferred_id:
            for candidate in ranked:
                if candidate.profile.ip_character_id == preferred_id:
                    selected_candidate = candidate
                    break
        if selected_candidate is None:
            selected_candidate = ranked[0]
            fallback_suffix = "llm_fallback" if preferred_id else "deterministic"
            preferred_reason = _selection_reason_from_score(selected_candidate, source=fallback_suffix)
        elif not preferred_reason:
            preferred_reason = _selection_reason_from_score(selected_candidate, source="llm")

        chosen = selected_candidate.profile
        selected.append(chosen)
        selected_ids.add(chosen.ip_character_id)
        is_route_target = slot.route_eligible and route_target_budget > 0
        if is_route_target:
            route_target_budget -= 1
        bound.append(
            BoundIPCastMember(
                character_id=chosen.ip_character_id,
                display_name=chosen.display_name,
                slot_id=slot.slot_id,
                slot_function=slot.slot_function,
                portrait_asset=chosen.portrait_asset,
                charisma_hook=chosen.charisma_hook,
                danger_hook=slot.danger_hook,
                speech_pattern=chosen.speech_pattern,
                gender=chosen.gender,
                public_role=slot.public_role_hint,
                public_mask=slot.public_mask,
                secret_pressure=slot.secret_pressure,
                relationship_to_protagonist=_relationship_to_protagonist(slot, blueprint),
                shareable_labels=chosen.shareable_labels,
                route_eligible=slot.route_eligible,
                is_route_target=is_route_target,
                selection_reason=preferred_reason,
                drama_profile=_build_drama_profile(
                    blueprint=blueprint,
                    slot=slot,
                    chosen=chosen,
                ),
                strategic_intent=_initial_strategic_intent(slot, blueprint, chosen),
            )
        )
    return _finalize_strategic_intents(bound, blueprint)


def bind_slots_to_ip_cast_with_candidate_pool(
    cast_slots: list[CastSlotPlan],
    blueprint: AcceptedBlueprint,
    *,
    slot_candidate_pool: dict[str, list[dict[str, Any]]],
    preferred_selection_by_slot: dict[str, str] | None = None,
    preferred_reasons_by_slot: dict[str, str] | None = None,
) -> list[BoundIPCastMember]:
    selected: list[IPCharacterProfile] = []
    selected_ids: set[str] = set()
    bound: list[BoundIPCastMember] = []
    route_target_budget = blueprint.route_target_count
    preferred_selection = preferred_selection_by_slot or {}
    preferred_reasons = preferred_reasons_by_slot or {}
    profiles = profile_by_id()

    def _candidate_reason(row: dict[str, Any], *, source: str) -> str:
        score = float(row.get("score") or 0.0)
        breakdown = row.get("score_breakdown")
        if isinstance(breakdown, dict):
            role_fit = float(breakdown.get("role_slot_fit") or 0.0)
            secret_fit = float(breakdown.get("secret_type_fit") or 0.0)
            voice_fit = float(breakdown.get("voice_register_fit") or 0.0)
            dup_penalty = float(breakdown.get("duplicate_penalty") or 0.0)
            return trim_text(
                (
                    f"{source}: role={role_fit:.2f}, secret={secret_fit:.2f}, "
                    f"voice={voice_fit:.2f}, dup_penalty={dup_penalty:.2f}, total={score:.2f}"
                ),
                220,
            )
        return trim_text(f"{source}: total={score:.2f}", 220)

    for slot in cast_slots:
        candidates = [row for row in list(slot_candidate_pool.get(slot.slot_id) or []) if isinstance(row, dict)]
        if not candidates:
            raise RuntimeError(f"unable to bind slot={slot.slot_id}: candidate pool empty")

        preferred_id = str(preferred_selection.get(slot.slot_id) or "").strip()
        preferred_reason = trim_text(str(preferred_reasons.get(slot.slot_id) or ""), 220)
        chosen_row: dict[str, Any] | None = None
        preferred_visible = False
        preferred_viable = False

        for row in candidates:
            row_id = str(row.get("ip_character_id") or "").strip()
            profile = profiles.get(row_id)
            if profile is None:
                continue
            viable = (
                profile.ip_character_id not in selected_ids
                and profile.is_adult
                and slot.slot_function in set(profile.compatible_slot_functions)
                and not (
                    blueprint.target_gender_pref in _TARGET_GENDER_VALUES
                    and profile.gender != blueprint.target_gender_pref
                )
                and not _disallowed_hit(profile, selected)
            )
            if preferred_id and row_id == preferred_id:
                preferred_visible = True
                preferred_viable = viable
            if chosen_row is None and viable:
                chosen_row = row
            if preferred_id and row_id == preferred_id and viable:
                chosen_row = row
                break

        if chosen_row is None:
            raise RuntimeError(f"unable to bind slot={slot.slot_id}: no viable candidate in frozen pool")

        chosen_id = str(chosen_row.get("ip_character_id") or "").strip()
        chosen = profiles.get(chosen_id)
        if chosen is None:
            raise RuntimeError(f"unable to bind slot={slot.slot_id}: candidate profile missing")

        if preferred_reason and preferred_id and chosen_id == preferred_id:
            selection_reason = preferred_reason
        elif preferred_id and chosen_id != preferred_id:
            source = "llm_fallback_not_in_pool" if not preferred_visible else "llm_fallback_not_viable"
            selection_reason = _candidate_reason(chosen_row, source=source)
        elif preferred_id and chosen_id == preferred_id and not preferred_reason:
            selection_reason = _candidate_reason(chosen_row, source="llm")
        else:
            fallback_source = "llm_fallback_not_viable" if preferred_visible and not preferred_viable else "deterministic"
            selection_reason = _candidate_reason(chosen_row, source=fallback_source)

        selected.append(chosen)
        selected_ids.add(chosen.ip_character_id)
        is_route_target = slot.route_eligible and route_target_budget > 0
        if is_route_target:
            route_target_budget -= 1
        bound.append(
            BoundIPCastMember(
                character_id=chosen.ip_character_id,
                display_name=chosen.display_name,
                slot_id=slot.slot_id,
                slot_function=slot.slot_function,
                portrait_asset=chosen.portrait_asset,
                charisma_hook=chosen.charisma_hook,
                danger_hook=slot.danger_hook,
                speech_pattern=chosen.speech_pattern,
                gender=chosen.gender,
                public_role=slot.public_role_hint,
                public_mask=slot.public_mask,
                secret_pressure=slot.secret_pressure,
                relationship_to_protagonist=_relationship_to_protagonist(slot, blueprint),
                shareable_labels=chosen.shareable_labels,
                route_eligible=slot.route_eligible,
                is_route_target=is_route_target,
                selection_reason=selection_reason,
                drama_profile=_build_drama_profile(
                    blueprint=blueprint,
                    slot=slot,
                    chosen=chosen,
                ),
                strategic_intent=_initial_strategic_intent(slot, blueprint, chosen),
            )
        )
    return _finalize_strategic_intents(bound, blueprint)
