from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author.contracts import StoryShellId
from rpg_backend.author_v2.contracts import ConflictTemplateId, ExperienceBandId, PlayLengthPresetId


class UrbanGoldCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    seed: str = Field(min_length=1, max_length=4000)
    expected_shell: StoryShellId
    expected_band: ExperienceBandId
    expected_play_length_preset: PlayLengthPresetId | None = None
    expected_template_id: ConflictTemplateId | None = None
    min_cast: int = Field(ge=3, le=7)
    max_cast: int = Field(ge=3, le=7)


REAL_PLAYER_FEEL_HINTS: tuple[str, ...] = (
    "玩家常见会先试探一句再改口，输入会口语化、含糊化，剧情要能接住并给出可感知代价。",
    "玩家经常会先稳场再反手，要求中段出现一次延迟爆点，避免全程平推。",
    "玩家会临时换目标或犹豫站队，这局需要把“换手代价”和“拒绝后升级”写得更可见。",
    "玩家常用短句和半句情绪表达，仍要保持推进，不要把回合变成空转对白。",
    "玩家会在普通回合保守，在关键回合突然激进，要求支持节奏反差和后果外溢。",
)


def _append_player_reality_hint(seed: str, *, hint: str) -> str:
    normalized = str(seed).strip()
    if normalized and normalized[-1] not in {"。", "！", "？"}:
        normalized = f"{normalized}。"
    return f"{normalized}{hint}"


def _build_realistic_variant(
    base_case: UrbanGoldCase,
    *,
    variant_suffix: str,
    hint: str,
) -> UrbanGoldCase:
    return UrbanGoldCase(
        case_id=f"{base_case.case_id}_{variant_suffix}",
        seed=_append_player_reality_hint(base_case.seed, hint=hint),
        expected_shell=base_case.expected_shell,
        expected_band=base_case.expected_band,
        expected_play_length_preset=base_case.expected_play_length_preset,
        expected_template_id=base_case.expected_template_id,
        min_cast=base_case.min_cast,
        max_cast=base_case.max_cast,
    )


def _select_cases_by_id(
    cases: list[UrbanGoldCase],
    case_ids: tuple[str, ...],
) -> list[UrbanGoldCase]:
    by_id = {case.case_id: case for case in cases}
    selected: list[UrbanGoldCase] = []
    for case_id in case_ids:
        case = by_id.get(case_id)
        if case is not None:
            selected.append(case)
    return selected


def _ensure_unique_case_ids(cases: list[UrbanGoldCase]) -> list[UrbanGoldCase]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            duplicates.add(case.case_id)
        seen.add(case.case_id)
    if duplicates:
        joined = ",".join(sorted(duplicates))
        raise ValueError(f"duplicate case ids in gold set: {joined}")
    return cases


def _build_realistic_variants(
    base_cases: list[UrbanGoldCase],
    *,
    variant_case_ids: tuple[str, ...] | None = None,
    extra_count: int | None = None,
    variant_prefix: str,
) -> list[UrbanGoldCase]:
    if variant_case_ids is not None:
        sources = _select_cases_by_id(base_cases, variant_case_ids)
    else:
        total = max(0, int(extra_count or 0))
        sources = list(base_cases[:total])
    variants: list[UrbanGoldCase] = []
    for index, base_case in enumerate(sources, start=1):
        hint = REAL_PLAYER_FEEL_HINTS[(index - 1) % len(REAL_PLAYER_FEEL_HINTS)]
        variants.append(
            _build_realistic_variant(
                base_case,
                variant_suffix=f"{variant_prefix}_{index:02d}",
                hint=hint,
            )
        )
    return variants


LONG_ARC_SHORT_SEED_KEYWORDS: tuple[str, ...] = (
    "5到8分钟",
    "5-8分钟",
    "8到15分钟",
    "8-15分钟",
    "短局",
)

LONG_ARC_REQUIRED_SHELLS: tuple[StoryShellId, ...] = (
    "wealth_families",
    "office_power",
    "entertainment_scandal",
    "campus_romance",
    "urban_supernatural",
)


def _validate_long_arc_gold_set(
    *,
    set_name: str,
    cases: list[UrbanGoldCase],
    expected_band_distribution: dict[ExperienceBandId, int] | None = None,
    expected_preset_distribution: dict[PlayLengthPresetId, int] | None = None,
    required_shells: tuple[StoryShellId, ...] = LONG_ARC_REQUIRED_SHELLS,
) -> list[UrbanGoldCase]:
    validated = _ensure_unique_case_ids(list(cases))
    if expected_band_distribution is not None:
        band_counter: Counter[ExperienceBandId] = Counter(case.expected_band for case in validated)
        normalized_band_distribution: dict[ExperienceBandId, int] = {
            "5_8": int(band_counter.get("5_8", 0)),
            "8_15": int(band_counter.get("8_15", 0)),
            "15_25": int(band_counter.get("15_25", 0)),
        }
        expected_normalized: dict[ExperienceBandId, int] = {
            "5_8": int(expected_band_distribution.get("5_8", 0)),
            "8_15": int(expected_band_distribution.get("8_15", 0)),
            "15_25": int(expected_band_distribution.get("15_25", 0)),
        }
        if normalized_band_distribution != expected_normalized:
            raise ValueError(
                f"{set_name} band distribution mismatch: expected={expected_normalized}, got={normalized_band_distribution}"
            )
    if expected_preset_distribution is not None:
        missing_preset_ids = [case.case_id for case in validated if not case.expected_play_length_preset]
        if missing_preset_ids:
            raise ValueError(f"{set_name} missing expected_play_length_preset: {','.join(missing_preset_ids)}")
        preset_counter = Counter(str(case.expected_play_length_preset) for case in validated)
        normalized_preset_distribution = {
            "15_20": int(preset_counter.get("15_20", 0)),
            "20_25": int(preset_counter.get("20_25", 0)),
            "30_45": int(preset_counter.get("30_45", 0)),
        }
        expected_preset_normalized = {
            "15_20": int(expected_preset_distribution.get("15_20", 0)),
            "20_25": int(expected_preset_distribution.get("20_25", 0)),
            "30_45": int(expected_preset_distribution.get("30_45", 0)),
        }
        if normalized_preset_distribution != expected_preset_normalized:
            raise ValueError(
                f"{set_name} preset distribution mismatch: expected={expected_preset_normalized}, got={normalized_preset_distribution}"
            )
    shell_set = {case.expected_shell for case in validated}
    missing_shells = [shell for shell in required_shells if shell not in shell_set]
    if missing_shells:
        raise ValueError(f"{set_name} missing required shells: {','.join(missing_shells)}")
    for case in validated:
        compact_seed = str(case.seed).replace(" ", "")
        for keyword in LONG_ARC_SHORT_SEED_KEYWORDS:
            if keyword in compact_seed:
                raise ValueError(f"{set_name} contains short-arc seed keyword `{keyword}` in case `{case.case_id}`")
    return validated


def mini_gold_set() -> list[UrbanGoldCase]:
    return [
        UrbanGoldCase(
            case_id="wealth_short_wedding",
            seed="豪门订婚宴上，最体面的未婚夫、突然回来的旧爱和握着遗嘱录音的律师同时逼她站队。做成一个5分钟短局，重点要有当众失控的爆点。",
            expected_shell="wealth_families",
            expected_band="5_8",
            expected_template_id="wealth_engagement_sideswitch",
            min_cast=3,
            max_cast=4,
        ),
        UrbanGoldCase(
            case_id="entertainment_short_livestream",
            seed="顶流直播夜，女主发现偷拍视频会让隐恋和代言一起翻车。要短、狠、能上热搜，5到8分钟。",
            expected_shell="entertainment_scandal",
            expected_band="5_8",
            expected_template_id="entertainment_livestream_hotsearch_flip",
            min_cast=3,
            max_cast=4,
        ),
        UrbanGoldCase(
            case_id="office_standard_boardroom",
            seed="董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。想要一个8到15分钟的职场修罗场。",
            expected_shell="office_power",
            expected_band="8_15",
            expected_template_id="office_board_vote_blackledger",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="campus_standard_homecoming",
            seed="校庆晚会前，奖学金竞争、旧录音和前任回归一起把女主推向风口。要有校园站队和公开翻车感，8到15分钟。",
            expected_shell="campus_romance",
            expected_band="8_15",
            expected_template_id="campus_homecoming_recording",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="supernatural_standard_night",
            seed="都市夜色里，她白天上班，夜里被异能契约和危险知情者拖进旧债。要有当众失控和关系反噬，8到15分钟。",
            expected_shell="urban_supernatural",
            expected_band="8_15",
            expected_template_id="urban_supernatural_legacy_contract",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="entertainment_standard_awards",
            seed="颁奖礼后台，顶流男主、铁血经纪人和突然回来的旧绯闻对象把女主逼进直播翻车边缘。标准局，8到15分钟。",
            expected_shell="entertainment_scandal",
            expected_band="8_15",
            expected_template_id="entertainment_awards_scandal",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="wealth_flagship_succession",
            seed="豪门继承夜，家宴、私生录音、联姻和旧爱同时回潮。我要一个20到25分钟、6到7人的旗舰局，重关系、重爆点、重站队。",
            expected_shell="wealth_families",
            expected_band="15_25",
            expected_template_id="wealth_private_heir_return",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="office_flagship_merger",
            seed="并购战收官前，总裁、秘书、律师、对家和旧同盟在董事会与夜宴之间互相拿捏。做成15到25分钟的旗舰职场关系戏，最好有7人局。",
            expected_shell="office_power",
            expected_band="15_25",
            expected_template_id="office_promotion_side_betrayal",
            min_cast=6,
            max_cast=7,
        ),
    ]


def mini_gold_realistic_6() -> list[UrbanGoldCase]:
    cases = [
        UrbanGoldCase(
            case_id="wealth_flagship_succession",
            seed="继承委员会跨夜听证与家宴并行推进，联姻席位、私生证据和旧爱回潮反复换手，目标做成30到45分钟的超级旗舰局。",
            expected_shell="wealth_families",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="wealth_private_heir_return",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="office_flagship_merger",
            seed="并购终局拆成多会场长链路推进，总裁、法务、董事与旧同盟轮流逼她让步，每次拒绝都触发更高层级公开后果，目标30到45分钟。",
            expected_shell="office_power",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="office_merger_scapegoat",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="entertainment_flagship_awards",
            seed="颁奖礼周从彩排到庆功夜连锁发酵，热搜、隐恋、代言与黑料互相咬合，主角需要跨多个镜头场景反手回收，目标30到45分钟超级旗舰局。",
            expected_shell="entertainment_scandal",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="entertainment_awards_scandal",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="campus_mid_homecoming",
            seed="校庆主舞台前多方排位战交替发酵，奖学金风向和旧录音持续拉扯，目标做成20到25分钟中量局。",
            expected_shell="campus_romance",
            expected_band="15_25",
            expected_play_length_preset="20_25",
            expected_template_id="campus_homecoming_recording",
            min_cast=4,
            max_cast=6,
        ),
        UrbanGoldCase(
            case_id="supernatural_mid_night",
            seed="夜巡任务进入关键中段，契约代价与关系旧债同步抬升，要求跨场景完成可见后果交换，目标20到25分钟中量局。",
            expected_shell="urban_supernatural",
            expected_band="15_25",
            expected_play_length_preset="20_25",
            expected_template_id="urban_supernatural_legacy_contract",
            min_cast=4,
            max_cast=6,
        ),
        UrbanGoldCase(
            case_id="wealth_light_sideswitch",
            seed="豪门订婚宴前夜的排位战里，未婚夫、旧爱和律师轮流加压，目标做成15到20分钟轻量长局并确保代价落地。",
            expected_shell="wealth_families",
            expected_band="15_25",
            expected_play_length_preset="15_20",
            expected_template_id="wealth_engagement_sideswitch",
            min_cast=4,
            max_cast=6,
        ),
    ]
    return _validate_long_arc_gold_set(
        set_name="mini_gold_realistic_6",
        cases=cases,
        expected_band_distribution={"15_25": 6, "8_15": 0, "5_8": 0},
        expected_preset_distribution={"30_45": 3, "20_25": 2, "15_20": 1},
    )


def native_cn_gold_10() -> list[UrbanGoldCase]:
    cases = list(mini_gold_set())
    cases.append(
        UrbanGoldCase(
            case_id="campus_standard_mentor_review",
            seed="导师评审周里，奖学金、学生会站队和前任回归一起点燃校园修罗场。标准局。",
            expected_shell="campus_romance",
            expected_band="8_15",
            expected_template_id="campus_mentor_review_sideswitch",
            min_cast=4,
            max_cast=5,
        )
    )
    cases.append(
        UrbanGoldCase(
            case_id="supernatural_standard_clubfront",
            seed="深夜会所外，灵媒契约、暧昧旧债和公开怪谈直播一起发酵。标准局。",
            expected_shell="urban_supernatural",
            expected_band="8_15",
            expected_template_id="urban_supernatural_legacy_contract",
            min_cast=4,
            max_cast=5,
        )
    )
    return cases


def native_cn_gold_realistic_14() -> list[UrbanGoldCase]:
    base_cases = list(native_cn_gold_10())
    variants = _build_realistic_variants(
        base_cases,
        variant_case_ids=(
            "campus_standard_mentor_review",
            "supernatural_standard_clubfront",
            "wealth_flagship_succession",
            "office_flagship_merger",
        ),
        variant_prefix="realplay",
    )
    return _ensure_unique_case_ids([*base_cases, *variants])


def v1_topic_gold_14() -> list[UrbanGoldCase]:
    return [
        UrbanGoldCase(
            case_id="wealth_topic_banquet_will_flip",
            seed="慈善晚宴主桌上，握着能改写顺位的补充条款的人、名义上的联姻对象和突然回来的旧爱一起逼她在众人面前站队。做成8到15分钟标准豪门局，要有当众掀桌感。",
            expected_shell="wealth_families",
            expected_band="8_15",
            expected_template_id="wealth_banquet_will_flip",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="wealth_topic_engagement_sideswitch",
            seed="豪门订婚宴上，最体面的未婚夫、突然回来的旧爱和握着遗嘱录音的律师同时逼她站队。做成8到15分钟标准局，重点要有当众失控的爆点。",
            expected_shell="wealth_families",
            expected_band="8_15",
            expected_template_id="wealth_engagement_sideswitch",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="wealth_topic_inheritance_evidence_drop",
            seed="豪门继承夜里，继承顺位、旧案证据和最会装体面的人同时逼她选边。做成8到15分钟标准局，要有当众翻盘的重击感。",
            expected_shell="wealth_families",
            expected_band="8_15",
            expected_template_id="wealth_inheritance_evidence_drop",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="wealth_topic_private_heir_return",
            seed="家宴宣读遗嘱前，私生身份录音、旧爱回潮和掌控席位的人一起逼她认亲站队。做成8到15分钟标准豪门局。",
            expected_shell="wealth_families",
            expected_band="8_15",
            expected_template_id="wealth_private_heir_return",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="office_topic_board_vote_blackledger",
            seed="董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。想要一个8到15分钟的职场修罗场。",
            expected_shell="office_power",
            expected_band="8_15",
            expected_template_id="office_board_vote_blackledger",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="office_topic_merger_scapegoat",
            seed="并购收口会上，掌权者、旧同盟和危险合作方同时把黑账往她身上推，所有人都默认最后必须有人背锅。做成8到15分钟标准职场局。",
            expected_shell="office_power",
            expected_band="8_15",
            expected_template_id="office_merger_scapegoat",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="office_topic_launch_contract_flip",
            seed="产品发布会开场前，掌权者、合作方和旧同盟一起把会翻盘的合同按在她手里。要8到15分钟标准局，重点是公开翻车。",
            expected_shell="office_power",
            expected_band="8_15",
            expected_template_id="office_launch_contract_flip",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="office_topic_promotion_side_betrayal",
            seed="升职评审前，旧同盟、上位者和对家一起逼她当众表态，最像盟友的人准备第一个倒戈。做成8到15分钟标准职场局。",
            expected_shell="office_power",
            expected_band="8_15",
            expected_template_id="office_promotion_side_betrayal",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="entertainment_topic_awards_scandal",
            seed="颁奖礼后台，顶流男主、铁血经纪人和突然回来的旧绯闻对象把女主逼进直播翻车边缘。标准局，8到15分钟。",
            expected_shell="entertainment_scandal",
            expected_band="8_15",
            expected_template_id="entertainment_awards_scandal",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="entertainment_topic_livestream_hotsearch_flip",
            seed="顶流直播夜，偷拍视频会让隐恋和代言一起翻车，经纪人与旧绯闻对象都在逼她先保一个。做成8到15分钟标准局。",
            expected_shell="entertainment_scandal",
            expected_band="8_15",
            expected_template_id="entertainment_livestream_hotsearch_flip",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="entertainment_topic_variety_blackmail_flip",
            seed="综艺录制夜，顶流、经纪人和掌握黑料的人一起玩舆论与真心，镜头里外都在等她先失控。做成8到15分钟标准局。",
            expected_shell="entertainment_scandal",
            expected_band="8_15",
            expected_template_id="entertainment_variety_blackmail_flip",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="campus_topic_homecoming_recording",
            seed="校庆晚会前，奖学金竞争、旧录音和前任回归一起把女主推向风口。要有校园站队和公开翻车感，8到15分钟。",
            expected_shell="campus_romance",
            expected_band="8_15",
            expected_template_id="campus_homecoming_recording",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="campus_topic_mentor_review_sideswitch",
            seed="导师评审周里，奖学金、学生会站队和前任回归一起点燃校园修罗场。标准局，8到15分钟。",
            expected_shell="campus_romance",
            expected_band="8_15",
            expected_template_id="campus_mentor_review_sideswitch",
            min_cast=4,
            max_cast=5,
        ),
        UrbanGoldCase(
            case_id="campus_topic_club_campaign_flip",
            seed="社团庆功夜，竞选风向、隐藏录音和最会装无辜的人一起把她逼到公开站队边缘。做成8到15分钟标准校园局。",
            expected_shell="campus_romance",
            expected_band="8_15",
            expected_template_id="campus_club_campaign_flip",
            min_cast=4,
            max_cast=5,
        ),
    ]


def v1_topic_gold_realistic_10() -> list[UrbanGoldCase]:
    cases = [
        UrbanGoldCase(
            case_id="wealth_topic_super_private_heir",
            seed="家宴、听证与法律函连续升级，私生证据、联姻席位和旧爱回潮反复换手，目标做成30到45分钟超级旗舰局。",
            expected_shell="wealth_families",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="wealth_private_heir_return",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="office_topic_super_board_vote",
            seed="董事会多轮表决连带夜宴对冲，黑账、授权和旧盟背刺叠加，要求通过阶段性让步换取终盘反制位，目标30到45分钟。",
            expected_shell="office_power",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="office_board_vote_blackledger",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="entertainment_topic_super_awards",
            seed="颁奖周多会场推进，镜头内外同时要价，隐恋、代言和黑料形成连段冲击，主角需逐层回收控制节奏，目标30到45分钟。",
            expected_shell="entertainment_scandal",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="entertainment_awards_scandal",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="campus_topic_super_homecoming",
            seed="校庆周跨学院推进，奖学金与录音线反复交错，主角要在多轮站队交易后才能拿到最终发言权，目标30到45分钟。",
            expected_shell="campus_romance",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="campus_homecoming_recording",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="supernatural_topic_super_contract",
            seed="夜巡线进入多阶段围猎，契约代价、旧债和目击者同时抬升，主角要在跨段推进里交换控制权，目标30到45分钟。",
            expected_shell="urban_supernatural",
            expected_band="15_25",
            expected_play_length_preset="30_45",
            expected_template_id="urban_supernatural_legacy_contract",
            min_cast=6,
            max_cast=7,
        ),
        UrbanGoldCase(
            case_id="wealth_topic_mid_sideswitch",
            seed="订婚宴前的利益博弈里，未婚夫、旧爱与律师轮番施压，主角需在中段完成一次高风险站队切换，目标20到25分钟中量局。",
            expected_shell="wealth_families",
            expected_band="15_25",
            expected_play_length_preset="20_25",
            expected_template_id="wealth_engagement_sideswitch",
            min_cast=4,
            max_cast=6,
        ),
        UrbanGoldCase(
            case_id="campus_topic_mid_club_campaign",
            seed="社团竞选进入后半程，竞选风向和隐藏证据同步发酵，主角需要经历一次误判后再回收，目标20到25分钟中量局。",
            expected_shell="campus_romance",
            expected_band="15_25",
            expected_play_length_preset="20_25",
            expected_template_id="campus_club_campaign_flip",
            min_cast=4,
            max_cast=6,
        ),
        UrbanGoldCase(
            case_id="supernatural_topic_mid_night",
            seed="夜巡中段里契约副作用与关系博弈同步抬升，主角要在有限窗口完成有效换手，目标20到25分钟中量局。",
            expected_shell="urban_supernatural",
            expected_band="15_25",
            expected_play_length_preset="20_25",
            expected_template_id="urban_supernatural_legacy_contract",
            min_cast=4,
            max_cast=6,
        ),
        UrbanGoldCase(
            case_id="office_topic_light_boardroom",
            seed="董事会前夜，上司、对手和法务同步施压，主角要在有限窗口换到有利站位，目标15到20分钟轻量长局。",
            expected_shell="office_power",
            expected_band="15_25",
            expected_play_length_preset="15_20",
            expected_template_id="office_board_vote_blackledger",
            min_cast=4,
            max_cast=6,
        ),
        UrbanGoldCase(
            case_id="entertainment_topic_light_awards",
            seed="颁奖礼前夜舆论拉锯中，公关和旧绯闻对象联手压线，主角需完成代价明确的中段反转，目标15到20分钟轻量长局。",
            expected_shell="entertainment_scandal",
            expected_band="15_25",
            expected_play_length_preset="15_20",
            expected_template_id="entertainment_awards_scandal",
            min_cast=4,
            max_cast=6,
        ),
    ]
    return _validate_long_arc_gold_set(
        set_name="v1_topic_gold_realistic_10",
        cases=cases,
        expected_band_distribution={"15_25": 10, "8_15": 0, "5_8": 0},
        expected_preset_distribution={"30_45": 5, "20_25": 3, "15_20": 2},
    )


def promo_realistic_case_set() -> list[UrbanGoldCase]:
    selected_ids = {
        "wealth_short_wedding",
        "wealth_flagship_succession",
        "office_standard_boardroom",
        "office_flagship_merger",
        "entertainment_standard_awards",
        "campus_standard_homecoming",
    }
    return [case for case in mini_gold_set() if case.case_id in selected_ids]


def burst_pressure_set() -> list[UrbanGoldCase]:
    return [
        UrbanGoldCase(case_id="wealth_short_1", seed="豪门婚礼彩排前，联姻对象、旧爱和遗嘱录音一起冲进来。做成5到8分钟短局。", expected_shell="wealth_families", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="wealth_short_2", seed="家宴开席前，私生证据和旧婚约一起翻上桌。要短、狠、当众失控，5到8分钟。", expected_shell="wealth_families", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="wealth_standard_1", seed="豪门继承人回国夜，联姻、旧爱、律师和录音把女主拖进8到15分钟的站队修罗场。", expected_shell="wealth_families", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="wealth_standard_2", seed="慈善晚宴上，未婚夫、白月光和掌握遗嘱秘密的人同时逼她选边。标准局，8到15分钟。", expected_shell="wealth_families", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="wealth_standard_3", seed="订婚宴前夜，旧案证据、名分和家族体面一起失控。要都市豪门感，8到15分钟。", expected_shell="wealth_families", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="wealth_standard_4", seed="家族信托签字前，冷面继承人、危险盟友和旧情一起把主角逼到墙角。标准局。", expected_shell="wealth_families", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="wealth_flagship_1", seed="豪门继承夜横跨家宴、酒会和深夜停车场，联姻、旧爱、私生录音和遗嘱黑幕一起炸开。做成15到25分钟旗舰局。", expected_shell="wealth_families", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="wealth_flagship_2", seed="跨城豪门联姻局里，总裁、律师、旧爱、私生子和掌控家宴风向的人轮番逼她失控。我要15到25分钟群像局。", expected_shell="wealth_families", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="entertainment_short_1", seed="直播事故前10分钟，偷拍视频和隐恋一起要上热搜。做成5到8分钟短局。", expected_shell="entertainment_scandal", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="entertainment_short_2", seed="红毯前夕，顶流、经纪人和旧绯闻对象同时逼她表态。短、狠、能传播，5到8分钟。", expected_shell="entertainment_scandal", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="entertainment_standard_1", seed="颁奖礼后台，热搜、黑料和隐恋把女主拖进镜头内外的双重修罗场。8到15分钟。", expected_shell="entertainment_scandal", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="entertainment_standard_2", seed="杀青宴上，顶流男主、铁血经纪人和偷拍视频一起把她的体面炸掉。标准局。", expected_shell="entertainment_scandal", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="entertainment_standard_3", seed="直播带货翻车前，假情侣营销和旧情复燃一起冲上热搜。要8到15分钟都市爆点。", expected_shell="entertainment_scandal", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="entertainment_standard_4", seed="综艺录制夜，顶流、经纪人与掌握黑料的人一起玩舆论和真心。标准局，8到15分钟。", expected_shell="entertainment_scandal", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="entertainment_flagship_1", seed="从颁奖礼到深夜庆功宴，隐恋、代言、黑料和旧爱回归一起把顶流关系局炸开。做成15到25分钟旗舰局。", expected_shell="entertainment_scandal", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="entertainment_flagship_2", seed="娱乐公司公关大战里，顶流、经纪人、制片人、旧绯闻对象和偷拍视频源头一起失控。我要15到25分钟群像传播局。", expected_shell="entertainment_scandal", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="office_short_1", seed="闭门董事会前，秘书发现并购黑账和上司暧昧会一起翻车。短局，5到8分钟。", expected_shell="office_power", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="office_short_2", seed="项目发布会前夜，上司、对手和黑账录音同时逼她站队。要5到8分钟。", expected_shell="office_power", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="office_standard_1", seed="董事会前夜，总裁、法务、秘书和并购黑账把女主拖进暧昧与站队修罗场。8到15分钟。", expected_shell="office_power", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="office_standard_2", seed="办公室权斗里，上位机会、旧同盟和会翻盘的合同一起失控。标准局，8到15分钟。", expected_shell="office_power", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="office_standard_3", seed="并购发布会前，掌权者、危险合作方和最懂她弱点的人一起逼她表态。8到15分钟。", expected_shell="office_power", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="office_standard_4", seed="职场夜宴里，黑账、站队和暧昧权力关系一起发酵。要都市职场修罗场，8到15分钟。", expected_shell="office_power", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="office_flagship_1", seed="从董事会到庆功晚宴，总裁、秘书、律师、旧同盟和对家一起拿捏并购黑账与真心。做成15到25分钟旗舰局。", expected_shell="office_power", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="office_flagship_2", seed="跨部门权斗收官前，冷面上司、法务、对家、旧情与站队黑账轮番逼她失控。我要15到25分钟职场群像局。", expected_shell="office_power", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="campus_short_1", seed="校庆彩排夜，旧录音和前任回归一起把她推上风口。做成5到8分钟短局。", expected_shell="campus_romance", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="campus_short_2", seed="奖学金结果公布前，学生会风向和旧爱一起失控。要短、狠、校园站队感，5到8分钟。", expected_shell="campus_romance", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="campus_standard_1", seed="校庆晚会前，白切黑竞争者、旧暧昧和旧录音把女主拖进公开翻车边缘。8到15分钟。", expected_shell="campus_romance", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="campus_standard_2", seed="导师评审周里，奖学金、学生会站队和前任回归一起点燃校园修罗场。标准局。", expected_shell="campus_romance", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="campus_standard_3", seed="社团庆功夜，隐藏录音、竞选和最会装无辜的人一起把主角推向失控。8到15分钟。", expected_shell="campus_romance", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="campus_standard_4", seed="毕业答辩前夕，旧爱、奖学金和清纯反杀式竞争一起逼她公开站队。标准局。", expected_shell="campus_romance", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="campus_flagship_1", seed="从校庆到毕业舞会，旧录音、奖学金、前任回归和学生会风向一起滚成15到25分钟旗舰校园关系戏。", expected_shell="campus_romance", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="campus_flagship_2", seed="学院竞选收官前，导师、前任、白切黑竞争者和最会站队的人一起把主角逼进群像局。我要15到25分钟。", expected_shell="campus_romance", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="supernatural_short_1", seed="夜巡前，她发现异能契约会在公开场合把旧债一起拖回来。做成5到8分钟短局。", expected_shell="urban_supernatural", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="supernatural_short_2", seed="都市怪谈直播夜，危险知情者和旧契约一起逼她失控。要5到8分钟。", expected_shell="urban_supernatural", expected_band="5_8", min_cast=3, max_cast=4),
        UrbanGoldCase(case_id="supernatural_standard_1", seed="白天上班、夜里夜巡的她，被异能契约、旧债和危险缪斯同时卷进都市关系局。8到15分钟。", expected_shell="urban_supernatural", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="supernatural_standard_2", seed="深夜会所外，灵媒契约、暧昧旧债和公开怪谈直播一起发酵。标准局。", expected_shell="urban_supernatural", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="supernatural_standard_3", seed="都市夜色里，她想摆脱命运安排的关系债，却被最危险的知情者和旧情一起逼近。8到15分钟。", expected_shell="urban_supernatural", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="supernatural_standard_4", seed="夜巡案发后，异能契约、旧爱和危险盟友一起让她在镜头前失控。标准局。", expected_shell="urban_supernatural", expected_band="8_15", min_cast=4, max_cast=5),
        UrbanGoldCase(case_id="supernatural_flagship_1", seed="从都市夜巡到会所深夜局，异能契约、前世旧债、危险知情者和公开失控一起滚成15到25分钟旗舰戏。", expected_shell="urban_supernatural", expected_band="15_25", min_cast=6, max_cast=7),
        UrbanGoldCase(case_id="supernatural_flagship_2", seed="她白天维持体面，夜里被契约、旧债、危险缪斯和目击者拉进一场都市超自然群像关系局。我要15到25分钟。", expected_shell="urban_supernatural", expected_band="15_25", min_cast=6, max_cast=7),
    ]


def burst_pressure_realistic_20() -> list[UrbanGoldCase]:
    base_cases = list(v1_topic_gold_realistic_10())
    variants_primary = _build_realistic_variants(
        base_cases,
        extra_count=len(base_cases),
        variant_prefix="realplay_a",
    )
    return _validate_long_arc_gold_set(
        set_name="burst_pressure_realistic_20",
        cases=[*base_cases, *variants_primary],
        expected_band_distribution={"15_25": 20, "8_15": 0, "5_8": 0},
        expected_preset_distribution={"30_45": 10, "20_25": 6, "15_20": 4},
    )
