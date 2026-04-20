from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from random import Random
from typing import Callable


@dataclass(frozen=True)
class GeneratedStorySeed:
    bucket_id: str
    slug: str
    seed: str
    generated_at: str


@dataclass(frozen=True)
class _SeedBucketTemplate:
    bucket_id: str
    slug: str
    seed_en: Callable[[Random], str]
    seed_zh: Callable[[Random], str]


def _timestamp(now: datetime | None = None) -> str:
    resolved = now or datetime.now(timezone.utc)
    return resolved.isoformat()


def _seed_legitimacy_warning_en(rng: Random) -> str:
    return (
        f"When a {rng.choice(['lunar', 'storm', 'river', 'watchtower'])} warning is buried to protect "
        f"a {rng.choice(['council vote', 'succession bargain', 'emergency mandate'])}, "
        f"a {rng.choice(['royal archivist', 'civic envoy', 'records magistrate'])} must prove the threat is real "
        f"before {rng.choice(['courtiers rewrite the public story', 'the capital locks itself into denial', 'the city accepts a false calm as law'])}."
    )


def _seed_legitimacy_warning_zh(rng: Random) -> str:
    return (
        f"当{rng.choice(['月潮预警', '风暴预警', '河道预警', '瞭望塔警报'])}被压下以保住"
        f"{rng.choice(['议会投票', '继承交易', '紧急授权'])}时，"
        f"{rng.choice(['档案官', '监察特使', '记录裁定官'])}必须在"
        f"{rng.choice(['权贵改写舆论之前', '首都集体否认之前', '全城把假平静当成法律之前'])}证明威胁真实存在。"
    )


def _seed_ration_infrastructure_en(rng: Random) -> str:
    return (
        f"After {rng.choice(['forged ration counts', 'tampered bridge ledgers', 'hidden reserve tallies'])} split "
        f"{rng.choice(['the upper wards and the river docks', 'the bridge crews and the market districts', 'the flood board and the grain stewards'])}, "
        f"a {rng.choice(['bridge engineer', 'public works marshal', 'levee comptroller'])} must keep the "
        f"{rng.choice(['flood defense coalition', 'cross-river relief pact', 'emergency works charter'])} intact before "
        f"{rng.choice(['the crossing fails under panic', 'scarcity turns maintenance into factional leverage', 'the city blames the wrong ward for the collapse'])}."
    )


def _seed_ration_infrastructure_zh(rng: Random) -> str:
    return (
        f"{rng.choice(['配给统计造假', '桥梁台账被篡改', '储备清单被隐匿'])}撕裂了"
        f"{rng.choice(['上城区与河港', '桥务组与市场区', '防洪委员会与粮务处'])}后，"
        f"{rng.choice(['桥梁工程师', '公共工程总管', '堤防审计官'])}必须在"
        f"{rng.choice(['人群恐慌冲垮通道之前', '短缺被各派当作筹码之前', '城市错怪无辜街区之前'])}"
        f"稳住{rng.choice(['防洪联盟', '跨河救援协定', '紧急工程章程'])}。"
    )


def _seed_blackout_panic_en(rng: Random) -> str:
    return (
        f"During a {rng.choice(['blackout referendum', 'rolling power crisis', 'night-curfew recall vote'])}, "
        f"a {rng.choice(['city ombudsman', 'ward mediator', 'public audit officer'])} must stop "
        f"{rng.choice(['forged supply reports', 'staged shortage bulletins', 'panic-rich rumor ledgers'])} from "
        f"breaking apart {rng.choice(['the neighborhood councils', 'the ward coalition', 'the emergency compact'])} before "
        f"{rng.choice(['street patrols turn rumor into authority', 'the districts seize the grid room by force', 'panic becomes the only public language left'])}."
    )


def _seed_blackout_panic_zh(rng: Random) -> str:
    return (
        f"在{rng.choice(['停电公投', '轮转限电危机', '夜间宵禁追认投票'])}期间，"
        f"{rng.choice(['城市监察官', '街区调停员', '公共审计专员'])}必须阻止"
        f"{rng.choice(['伪造补给报告', '刻意放大的短缺通告', '煽动性谣言账本'])}瓦解"
        f"{rng.choice(['社区理事会', '街区联盟', '应急协约'])}，"
        f"否则{rng.choice(['街头巡逻将以谣言为法', '各区会武力争抢电网控制室', '恐慌会成为唯一公共语言'])}。"
    )


def _seed_harbor_quarantine_en(rng: Random) -> str:
    return (
        f"In a port city under quarantine, a {rng.choice(['harbor inspector', 'dock auditor', 'quarantine liaison'])} must keep "
        f"{rng.choice(['the harbor compact', 'the dock coalition', 'the relief corridor'])} alive after "
        f"{rng.choice(['missing manifests', 'staged scarcity reports', 'quietly redirected medical crates'])} threaten to hand "
        f"{rng.choice(['private trade brokers', 'emergency wardens', 'supply syndicates'])} the right to rule by exception."
    )


def _seed_harbor_quarantine_zh(rng: Random) -> str:
    return (
        f"在封港隔离的海港城市，{rng.choice(['港务稽查官', '码头审计员', '隔离联络官'])}必须在"
        f"{rng.choice(['提单失踪', '短缺报告被操纵', '医疗物资被悄悄调包'])}之后守住"
        f"{rng.choice(['港口协定', '码头联盟', '救援走廊'])}，"
        f"否则{rng.choice(['私贸掮客', '应急督办', '供应链同盟'])}将借例外状态接管规则。"
    )


def _seed_archive_vote_record_en(rng: Random) -> str:
    return (
        f"When {rng.choice(['vote ledgers', 'emergency transcripts', 'sealed chain-of-custody records'])} are altered during "
        f"{rng.choice(['an emergency council vote', 'a succession settlement', 'a public legitimacy hearing'])}, "
        f"a {rng.choice(['city archivist', 'records advocate', 'civic witness clerk'])} must restore one binding public record before "
        f"{rng.choice(['rumor hardens into law', 'the council governs from a forged mandate', 'every faction claims a different city truth'])}."
    )


def _seed_archive_vote_record_zh(rng: Random) -> str:
    return (
        f"当{rng.choice(['投票账册', '紧急会议纪要', '封存交接链记录'])}在"
        f"{rng.choice(['应急议会表决', '继承和解谈判', '公信力听证'])}中被改写，"
        f"{rng.choice(['城市档案官', '记录倡议人', '见证书记员'])}必须在"
        f"{rng.choice(['谣言固化为法律之前', '议会拿伪授权执政之前', '各派各说各话之前'])}恢复一份可公证的真记录。"
    )


def _seed_charter_oath_breach_en(rng: Random) -> str:
    return (
        f"After a sworn charter clause is breached to shield "
        f"{rng.choice(['a succession favorite', 'a media patron', 'a boardroom alliance'])}, "
        f"a {rng.choice(['compliance counsel', 'investigative clerk', 'board secretary'])} must force public acknowledgement before "
        f"{rng.choice(['the oath itself becomes ceremonial', 'every rival starts writing private rules', 'the breach is normalized as strategy'])}."
    )


def _seed_charter_oath_breach_zh(rng: Random) -> str:
    return (
        f"当誓约章程被故意违背以保护"
        f"{rng.choice(['继承热门人选', '媒体金主', '董事会结盟方'])}时，"
        f"{rng.choice(['合规顾问', '调查书记', '董事会秘书'])}必须在"
        f"{rng.choice(['誓约沦为空壳之前', '各派开始私设规则之前', '违约被包装成常态策略之前'])}逼出公开承认。"
    )


def _seed_checkpoint_corridor_access_en(rng: Random) -> str:
    return (
        f"When checkpoint corridor access is quietly rerouted toward "
        f"{rng.choice(['a celebrity convoy', 'a private family escort', 'a sponsor delegation'])}, "
        f"a {rng.choice(['corridor marshal', 'night supervisor', 'access controller'])} must reopen fair passage before "
        f"{rng.choice(['crowd anger hardens into blockade', 'security factions split the route by force', 'the corridor becomes a paid privilege lane'])}."
    )


def _seed_checkpoint_corridor_access_zh(rng: Random) -> str:
    return (
        f"当检查通道被悄悄改线给"
        f"{rng.choice(['明星车队', '豪门私家护送', '赞助商代表团'])}时，"
        f"{rng.choice(['通道总控官', '夜班主管', '门禁调度员'])}必须在"
        f"{rng.choice(['人群愤怒升级为封堵之前', '安保派系武力分线之前', '通道彻底变成付费特权道之前'])}恢复公平通行。"
    )


def _seed_customs_clearance_standoff_en(rng: Random) -> str:
    return (
        f"In a customs clearance standoff, sealed cargo tied to "
        f"{rng.choice(['an idol label', 'a family office', 'a venture media fund'])} cannot pass without signatures, "
        f"and a {rng.choice(['clearance officer', 'trade liaison', 'port legal aide'])} must break the deadlock before "
        f"{rng.choice(['broadcast leaks trigger a panic selloff', 'both camps weaponize delays as extortion', 'the hold order becomes a political hostage tool'])}."
    )


def _seed_customs_clearance_standoff_zh(rng: Random) -> str:
    return (
        f"在清关对峙中，涉及"
        f"{rng.choice(['偶像厂牌', '家族办公室', '传媒基金'])}的封存货柜因签字僵局无法放行，"
        f"{rng.choice(['清关专员', '贸易联络官', '港口法务助理'])}必须在"
        f"{rng.choice(['爆料引发抛售恐慌之前', '双方把延迟当勒索筹码之前', '扣押令变成人质工具之前'])}打破僵局。"
    )


def _seed_shelter_capacity_surge_en(rng: Random) -> str:
    return (
        f"When shelter capacity suddenly surges after "
        f"{rng.choice(['a celebrity scandal spillover', 'a district eviction sweep', 'a sponsorship collapse'])}, "
        f"a {rng.choice(['relief coordinator', 'facility auditor', 'placement lead'])} must triage access without losing legitimacy before "
        f"{rng.choice(['private donors demand exclusive quotas', 'queue riots erase trust in allocation', 'placement records are traded for influence'])}."
    )


def _seed_shelter_capacity_surge_zh(rng: Random) -> str:
    return (
        f"当{rng.choice(['明星丑闻外溢', '片区清退行动', '赞助资金断裂'])}导致收容容量骤增时，"
        f"{rng.choice(['安置协调员', '设施审计员', '分配负责人'])}必须在"
        f"{rng.choice(['金主要求专属名额之前', '排队冲突摧毁分配公信之前', '安置记录被拿去交换利益之前'])}完成可信分流。"
    )


def _seed_testimony_release_timing_en(rng: Random) -> str:
    return (
        f"A testimony release timing dispute erupts when statements implicating "
        f"{rng.choice(['a leading heir', 'a breakout actor', 'a coalition sponsor'])} are ready, "
        f"and a {rng.choice(['records editor', 'legal scheduler', 'hearing moderator'])} must choose the release window before "
        f"{rng.choice(['the leak narrative defines guilt first', 'witnesses are intimidated into silence', 'the hearing loses all procedural credibility'])}."
    )


def _seed_testimony_release_timing_zh(rng: Random) -> str:
    return (
        f"当牵涉"
        f"{rng.choice(['继承热门人选', '当红艺人', '联盟金主'])}的证词准备完毕，发布时点之争爆发，"
        f"{rng.choice(['记录编辑', '法务排期官', '听证主持人'])}必须在"
        f"{rng.choice(['泄露叙事先行定罪之前', '证人被威逼噤声之前', '听证彻底失去程序公信之前'])}决定公开窗口。"
    )


_SEED_BUCKETS: tuple[_SeedBucketTemplate, ...] = (
    _SeedBucketTemplate("legitimacy_warning", "legitimacy_warning", _seed_legitimacy_warning_en, _seed_legitimacy_warning_zh),
    _SeedBucketTemplate("ration_infrastructure", "ration_infrastructure", _seed_ration_infrastructure_en, _seed_ration_infrastructure_zh),
    _SeedBucketTemplate("blackout_panic", "blackout_panic", _seed_blackout_panic_en, _seed_blackout_panic_zh),
    _SeedBucketTemplate("harbor_quarantine", "harbor_quarantine", _seed_harbor_quarantine_en, _seed_harbor_quarantine_zh),
    _SeedBucketTemplate("archive_vote_record", "archive_vote_record", _seed_archive_vote_record_en, _seed_archive_vote_record_zh),
    _SeedBucketTemplate("charter_oath_breach", "charter_oath_breach", _seed_charter_oath_breach_en, _seed_charter_oath_breach_zh),
    _SeedBucketTemplate("checkpoint_corridor_access", "checkpoint_corridor_access", _seed_checkpoint_corridor_access_en, _seed_checkpoint_corridor_access_zh),
    _SeedBucketTemplate("customs_clearance_standoff", "customs_clearance_standoff", _seed_customs_clearance_standoff_en, _seed_customs_clearance_standoff_zh),
    _SeedBucketTemplate("shelter_capacity_surge", "shelter_capacity_surge", _seed_shelter_capacity_surge_en, _seed_shelter_capacity_surge_zh),
    _SeedBucketTemplate("testimony_release_timing", "testimony_release_timing", _seed_testimony_release_timing_en, _seed_testimony_release_timing_zh),
)


def build_story_seed_batch(
    *,
    rng: Random | None = None,
    now: datetime | None = None,
    story_count: int = 5,
    language: str = "en",
) -> list[GeneratedStorySeed]:
    resolved_rng = rng or Random()
    generated_at = _timestamp(now)
    is_chinese = language.casefold().startswith("zh")
    templates = [
        GeneratedStorySeed(
            bucket_id=bucket.bucket_id,
            slug=bucket.slug,
            seed=(bucket.seed_zh if is_chinese else bucket.seed_en)(resolved_rng),
            generated_at=generated_at,
        )
        for bucket in _SEED_BUCKETS
    ]
    normalized_count = max(1, min(int(story_count), len(templates)))
    if normalized_count >= len(templates):
        return templates
    selected = resolved_rng.sample(templates, k=normalized_count)
    return sorted(selected, key=lambda item: item.bucket_id)
