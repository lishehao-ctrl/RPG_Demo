from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author_v2.contracts import SecretClass
from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.gateway import AuthorV3LLMGateway


class OrganicSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    holders: list[str] = Field(min_length=1, max_length=7)
    knowers: list[str] = Field(default_factory=list, max_length=7)
    discovery_conditions: list[str] = Field(min_length=1, max_length=5)
    exposure_consequence_chains: list[str] = Field(min_length=1, max_length=5)
    lethality_score: float = Field(ge=0.0, le=1.0)
    chain_targets: list[str] = Field(default_factory=list, max_length=3)
    legacy_secret_class: SecretClass | None = None


class HookRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holder_id: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=64)
    source_secret_id: str = Field(min_length=1, max_length=64)
    leverage_type: str = Field(min_length=1, max_length=60)


class SecretChain(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger_secret_id: str = Field(min_length=1, max_length=64)
    unlocks_secret_id: str = Field(min_length=1, max_length=64)
    narrative_logic: str = Field(min_length=1, max_length=200)


class TensionWeb(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secrets: list[OrganicSecret] = Field(min_length=2, max_length=15)
    hooks: list[HookRecord] = Field(default_factory=list, max_length=30)
    chains: list[SecretChain] = Field(default_factory=list, max_length=10)
    narrative_potential_score: float = Field(ge=0.0, le=1.0)


_LEGACY_KEYWORDS: list[tuple[tuple[str, ...], SecretClass]] = [
    (("遗嘱", "证据"), "will_evidence"),
    (("私生", "继承人", "身份", "血缘"), "hidden_heir"),
    (("黑账", "财务", "账目", "资金", "审计"), "black_ledger"),
    (("合同", "并购", "收购", "合约"), "contract_flip"),
    (("视频", "录像", "直播", "偷拍"), "scandal_video"),
    (("录音", "档案", "旧案"), "old_recording"),
    (("契约", "灵媒", "异能"), "legacy_contract_secret"),
]


def map_to_legacy_secret_class(secret: OrganicSecret) -> SecretClass:
    text = f"{secret.title} {secret.description}"
    for keywords, cls in _LEGACY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return cls
    return "black_ledger"


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def score_narrative_potential(
    web: TensionWeb,
    config: WorldConfiguration,
    matrix: RelationshipMatrix,
) -> float:
    n_chars = len(config.characters)

    secret_density = _clamp01(len(web.secrets) / (n_chars * 1.5)) if n_chars else 0.0

    char_map = {c.character_id: c for c in config.characters}
    trust_lookup: dict[tuple[str, str], float] = {}
    for e in matrix.edges:
        trust_lookup[(e.character_a_id, e.character_b_id)] = e.stance_a_to_b.trust_level
        trust_lookup[(e.character_b_id, e.character_a_id)] = e.stance_b_to_a.trust_level
    low_trust_hooks = 0
    total_hooks = len(web.hooks)
    for h in web.hooks:
        t = trust_lookup.get((h.holder_id, h.target_id), 0.5)
        if t < 0.5:
            low_trust_hooks += 1
    relationship_asymmetry = (low_trust_hooks / total_hooks) if total_hooks else 0.0

    desire_conflict_count = 0
    for s in web.secrets:
        holder_desires = {char_map[hid].worldly_desire for hid in s.holders if hid in char_map}
        knower_desires = {char_map[kid].worldly_desire for kid in s.knowers if kid in char_map}
        if holder_desires and knower_desires and holder_desires != knower_desires:
            desire_conflict_count += 1
    desire_conflict = _clamp01(desire_conflict_count / len(web.secrets)) if web.secrets else 0.0

    chain_graph: dict[str, list[str]] = defaultdict(list)
    for ch in web.chains:
        chain_graph[ch.trigger_secret_id].append(ch.unlocks_secret_id)
    max_depth = 0
    for start in chain_graph:
        visited: set[str] = set()
        stack: list[tuple[str, int]] = [(start, 1)]
        while stack:
            node, depth = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            if depth > max_depth:
                max_depth = depth
            for nxt in chain_graph.get(node, []):
                if nxt not in visited:
                    stack.append((nxt, depth + 1))
    chain_depth = _clamp01(max_depth / 3)

    breaking_points = {c.breaking_point for c in config.characters}
    covered = 0
    for bp in breaking_points:
        for s in web.secrets:
            if any(bp[:6] in cons for cons in s.exposure_consequence_chains):
                covered += 1
                break
    bp_coverage = (covered / len(breaking_points)) if breaking_points else 0.0

    return round(
        (secret_density + relationship_asymmetry + desire_conflict + chain_depth + bp_coverage) / 5.0,
        4,
    )


_DETERMINISTIC_SECRETS: list[OrganicSecret] = [
    OrganicSecret(
        secret_id="sec_financial_fraud",
        title="财务造假记录",
        description="陈伟明创业早期通过伪造财务数据获取融资，相关文件被王思雨在整理旧账时发现",
        holders=["chen_weiming"],
        knowers=["wang_siyu"],
        discovery_conditions=["审计深入调查早期融资记录", "王思雨在压力下选择揭露"],
        exposure_consequence_chains=["陈伟明被董事会罢免", "公司股价崩盘", "私生子身份曝光的连锁反应"],
        lethality_score=0.9,
        chain_targets=["sec_grey_transactions"],
        legacy_secret_class="black_ledger",
    ),
    OrganicSecret(
        secret_id="sec_patent_theft",
        title="专利盗窃协议",
        description="陈伟明利用职务之便将张浩的核心技术专利转移到自己名下，原始转让协议仍存档",
        holders=["chen_weiming"],
        knowers=["zhang_hao"],
        discovery_conditions=["张浩找到专利转让协议原件", "第三方技术审查揭露专利归属"],
        exposure_consequence_chains=["陈伟明面临法律诉讼", "张浩拿回技术控制权", "发现CEO利用他的技术牟利的证据"],
        lethality_score=0.85,
        chain_targets=["sec_financial_fraud"],
        legacy_secret_class="will_evidence",
    ),
    OrganicSecret(
        secret_id="sec_fake_degree",
        title="学历造假",
        description="林雨欣的MBA学位是伪造的，她通过关系网获得了入职资格",
        holders=["lin_yuxin"],
        knowers=[],
        discovery_conditions=["背景调查升级", "竞争对手挖掘其履历"],
        exposure_consequence_chains=["林雨欣被开除", "与CEO的秘密交易曝光", "被发现学历造假引发信任危机"],
        lethality_score=0.7,
        chain_targets=[],
        legacy_secret_class="hidden_heir",
    ),
    OrganicSecret(
        secret_id="sec_grey_transactions",
        title="灰色交易记录",
        description="王思雨协助陈伟明处理多笔关联交易，涉及资金转移和利益输送",
        holders=["wang_siyu", "chen_weiming"],
        knowers=["liu_jianfeng"],
        discovery_conditions=["外部审计发现异常", "刘建锋利用审计线索施压"],
        exposure_consequence_chains=["王思雨被迫在忠诚和自保间选择", "审计暴露关联交易", "两人同时被追责"],
        lethality_score=0.8,
        chain_targets=["sec_financial_fraud"],
        legacy_secret_class="black_ledger",
    ),
    OrganicSecret(
        secret_id="sec_market_manipulation",
        title="市场操纵录音",
        description="刘建锋早年操纵市场的电话录音被对手秘密保存，成为悬在他头上的定时炸弹",
        holders=["liu_jianfeng"],
        knowers=[],
        discovery_conditions=["对手在关键谈判中亮出录音", "录音被第三方泄露"],
        exposure_consequence_chains=["刘建锋投资失败导致基金崩盘", "对手掌握了他操纵市场的录音被公开", "收购计划彻底失败"],
        lethality_score=0.75,
        chain_targets=["sec_acquisition_insider"],
        legacy_secret_class="old_recording",
    ),
    OrganicSecret(
        secret_id="sec_acquisition_insider",
        title="收购内幕邮件",
        description="刘建锋与林雨欣之间关于收购后权力分配的秘密邮件往来",
        holders=["liu_jianfeng", "lin_yuxin"],
        knowers=[],
        discovery_conditions=["邮件服务器被入侵", "内部人员举报"],
        exposure_consequence_chains=["林雨欣被视为内鬼", "收购计划曝光", "曾为上位出卖前任的旧事被翻出"],
        lethality_score=0.65,
        chain_targets=[],
        legacy_secret_class="contract_flip",
    ),
]

_DETERMINISTIC_HOOKS: list[HookRecord] = [
    HookRecord(holder_id="wang_siyu", target_id="chen_weiming", source_secret_id="sec_financial_fraud", leverage_type="blackmail"),
    HookRecord(holder_id="chen_weiming", target_id="wang_siyu", source_secret_id="sec_grey_transactions", leverage_type="mutual_destruction"),
    HookRecord(holder_id="zhang_hao", target_id="chen_weiming", source_secret_id="sec_patent_theft", leverage_type="evidence"),
    HookRecord(holder_id="liu_jianfeng", target_id="wang_siyu", source_secret_id="sec_grey_transactions", leverage_type="pressure"),
    HookRecord(holder_id="liu_jianfeng", target_id="lin_yuxin", source_secret_id="sec_acquisition_insider", leverage_type="complicity"),
    HookRecord(holder_id="lin_yuxin", target_id="liu_jianfeng", source_secret_id="sec_acquisition_insider", leverage_type="complicity"),
]

_DETERMINISTIC_CHAINS: list[SecretChain] = [
    SecretChain(
        trigger_secret_id="sec_patent_theft",
        unlocks_secret_id="sec_financial_fraud",
        narrative_logic="调查专利盗窃时发现早期财务造假的线索",
    ),
    SecretChain(
        trigger_secret_id="sec_financial_fraud",
        unlocks_secret_id="sec_grey_transactions",
        narrative_logic="财务造假曝光后审计深入发现灰色交易",
    ),
    SecretChain(
        trigger_secret_id="sec_market_manipulation",
        unlocks_secret_id="sec_acquisition_insider",
        narrative_logic="操纵录音曝光后刘建锋的收购内幕邮件也被翻出",
    ),
]


class TensionWeaverError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_WEAVE_SYSTEM = """你是一个叙事张力编织器。根据世界配置和关系网，生成一组有机秘密、钩子和秘密链。

返回JSON格式：
{
  "secrets": [
    {
      "secret_id": "唯一标识符，snake_case",
      "title": "秘密标题",
      "description": "秘密详细描述",
      "holders": ["持有者character_id列表"],
      "knowers": ["知情者character_id列表"],
      "discovery_conditions": ["发现条件列表"],
      "exposure_consequence_chains": ["暴露后果链列表"],
      "lethality_score": 0.0到1.0,
      "chain_targets": ["可以解锁的其他secret_id"]
    }
  ],
  "hooks": [
    {
      "holder_id": "握有把柄的character_id",
      "target_id": "被拿捏的character_id",
      "source_secret_id": "把柄来源的secret_id",
      "leverage_type": "把柄类型(blackmail/guilt/debt/complicity/evidence/pressure)"
    }
  ],
  "chains": [
    {
      "trigger_secret_id": "触发秘密的id",
      "unlocks_secret_id": "被解锁秘密的id",
      "narrative_logic": "为什么触发会导致解锁"
    }
  ]
}

要求：
1. 每个角色至少出现在一个秘密中
2. 秘密之间要有链式关系
3. 钩子要基于秘密产生
4. 暴露后果要与角色的fear/breaking_point呼应"""

_STRENGTHEN_SYSTEM = """你是一个叙事张力增强器。给定现有的秘密网络和最弱维度，补充或增强秘密/钩子/链来提升该维度。

返回与上面相同格式的完整JSON（包含原有的和新增的内容）。"""


def _parse_secrets_from_llm(raw: dict[str, Any], char_ids: set[str]) -> list[OrganicSecret]:
    secrets_raw = raw.get("secrets", [])
    if not isinstance(secrets_raw, list) or len(secrets_raw) < 2:
        raise TensionWeaverError("llm_bad_secrets", f"expected ≥2 secrets, got {len(secrets_raw) if isinstance(secrets_raw, list) else 0}")
    secrets: list[OrganicSecret] = []
    seen_ids: set[str] = set()
    for s in secrets_raw[:15]:
        sid = str(s.get("secret_id", f"sec_{len(secrets)}"))[:64]
        if sid in seen_ids:
            sid = f"{sid}_{len(secrets)}"
        seen_ids.add(sid)
        holders = [str(h) for h in s.get("holders", []) if str(h) in char_ids][:7]
        if not holders:
            continue
        knowers = [str(k) for k in s.get("knowers", []) if str(k) in char_ids][:7]
        discovery = [str(d)[:200] for d in s.get("discovery_conditions", ["未知条件"])][:5]
        if not discovery:
            discovery = ["未知条件"]
        consequences = [str(c)[:200] for c in s.get("exposure_consequence_chains", ["未知后果"])][:5]
        if not consequences:
            consequences = ["未知后果"]
        chain_targets = [str(t)[:64] for t in s.get("chain_targets", [])][:3]
        lethality = max(0.0, min(1.0, float(s.get("lethality_score", 0.5))))
        sec = OrganicSecret(
            secret_id=sid,
            title=str(s.get("title", "未知秘密"))[:120],
            description=str(s.get("description", "未知描述"))[:300],
            holders=holders,
            knowers=knowers,
            discovery_conditions=discovery,
            exposure_consequence_chains=consequences,
            lethality_score=lethality,
            chain_targets=chain_targets,
            legacy_secret_class=None,
        )
        sec.legacy_secret_class = map_to_legacy_secret_class(sec)
        secrets.append(sec)
    return secrets


def _parse_hooks_from_llm(raw: dict[str, Any], char_ids: set[str], secret_ids: set[str]) -> list[HookRecord]:
    hooks_raw = raw.get("hooks", [])
    if not isinstance(hooks_raw, list):
        return []
    hooks: list[HookRecord] = []
    for h in hooks_raw[:30]:
        holder = str(h.get("holder_id", ""))
        target = str(h.get("target_id", ""))
        source = str(h.get("source_secret_id", ""))
        if holder not in char_ids or target not in char_ids or source not in secret_ids:
            continue
        if holder == target:
            continue
        hooks.append(HookRecord(
            holder_id=holder,
            target_id=target,
            source_secret_id=source,
            leverage_type=str(h.get("leverage_type", "pressure"))[:60],
        ))
    return hooks


def _parse_chains_from_llm(raw: dict[str, Any], secret_ids: set[str]) -> list[SecretChain]:
    chains_raw = raw.get("chains", [])
    if not isinstance(chains_raw, list):
        return []
    chains: list[SecretChain] = []
    for c in chains_raw[:10]:
        trigger = str(c.get("trigger_secret_id", ""))
        unlocks = str(c.get("unlocks_secret_id", ""))
        if trigger not in secret_ids or unlocks not in secret_ids or trigger == unlocks:
            continue
        chains.append(SecretChain(
            trigger_secret_id=trigger,
            unlocks_secret_id=unlocks,
            narrative_logic=str(c.get("narrative_logic", "因果关联"))[:200],
        ))
    return chains


def _weakest_dimension(
    web: TensionWeb, config: WorldConfiguration, matrix: RelationshipMatrix
) -> str:
    n_chars = len(config.characters)
    char_map = {c.character_id: c for c in config.characters}

    secret_density = _clamp01(len(web.secrets) / (n_chars * 1.5)) if n_chars else 0.0

    trust_lookup: dict[tuple[str, str], float] = {}
    for e in matrix.edges:
        trust_lookup[(e.character_a_id, e.character_b_id)] = e.stance_a_to_b.trust_level
        trust_lookup[(e.character_b_id, e.character_a_id)] = e.stance_b_to_a.trust_level
    low_trust = sum(1 for h in web.hooks if trust_lookup.get((h.holder_id, h.target_id), 0.5) < 0.5)
    relationship_asymmetry = (low_trust / len(web.hooks)) if web.hooks else 0.0

    dc = 0
    for s in web.secrets:
        hd = {char_map[hid].worldly_desire for hid in s.holders if hid in char_map}
        kd = {char_map[kid].worldly_desire for kid in s.knowers if kid in char_map}
        if hd and kd and hd != kd:
            dc += 1
    desire_conflict = _clamp01(dc / len(web.secrets)) if web.secrets else 0.0

    chain_graph: dict[str, list[str]] = defaultdict(list)
    for ch in web.chains:
        chain_graph[ch.trigger_secret_id].append(ch.unlocks_secret_id)
    max_depth = 0
    for start in chain_graph:
        visited: set[str] = set()
        stack: list[tuple[str, int]] = [(start, 1)]
        while stack:
            node, depth = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            max_depth = max(max_depth, depth)
            for nxt in chain_graph.get(node, []):
                if nxt not in visited:
                    stack.append((nxt, depth + 1))
    chain_depth = _clamp01(max_depth / 3)

    breaking_points = {c.breaking_point for c in config.characters}
    covered = sum(
        1 for bp in breaking_points
        if any(bp[:6] in cons for s in web.secrets for cons in s.exposure_consequence_chains)
    )
    bp_coverage = (covered / len(breaking_points)) if breaking_points else 0.0

    dims = {
        "secret_density": secret_density,
        "relationship_asymmetry": relationship_asymmetry,
        "desire_conflict": desire_conflict,
        "chain_depth": chain_depth,
        "breaking_point_coverage": bp_coverage,
    }
    return min(dims, key=lambda k: dims[k])


def _weave_deterministic(config: WorldConfiguration, matrix: RelationshipMatrix) -> TensionWeb:
    secrets = list(_DETERMINISTIC_SECRETS)
    hooks = list(_DETERMINISTIC_HOOKS)
    chains = list(_DETERMINISTIC_CHAINS)

    web = TensionWeb(
        secrets=secrets,
        hooks=hooks,
        chains=chains,
        narrative_potential_score=0.0,
    )
    score = score_narrative_potential(web, config, matrix)
    web = web.model_copy(update={"narrative_potential_score": score})
    return web


def _weave_live(
    config: WorldConfiguration,
    matrix: RelationshipMatrix,
    gateway: AuthorV3LLMGateway,
    max_rounds: int,
    threshold: float,
) -> TensionWeb:
    char_ids = {c.character_id for c in config.characters}
    char_summaries = [
        {
            "character_id": c.character_id,
            "display_name": c.display_name,
            "public_identity": c.public_identity,
            "hidden_need": c.hidden_need,
            "worldly_desire": c.worldly_desire,
            "fear": c.fear,
            "shame_trigger": c.shame_trigger,
            "breaking_point": c.breaking_point,
        }
        for c in config.characters
    ]
    edge_summaries = [
        {
            "character_a": e.character_a_id,
            "character_b": e.character_b_id,
            "hidden_truth": e.hidden_truth,
            "tension_score": e.tension_score,
            "hooks": e.hooks,
        }
        for e in matrix.edges
    ]

    result = gateway.invoke_json(
        system_prompt=_WEAVE_SYSTEM,
        user_payload={
            "characters": char_summaries,
            "relationships": edge_summaries,
            "protagonist_id": config.protagonist_id,
        },
        max_output_tokens=gateway.max_output_tokens_tension_weaver,
        operation_name="author_v3_weave_secrets",
    )

    secrets = _parse_secrets_from_llm(result.parsed, char_ids)
    secret_ids = {s.secret_id for s in secrets}
    hooks = _parse_hooks_from_llm(result.parsed, char_ids, secret_ids)
    chains = _parse_chains_from_llm(result.parsed, secret_ids)

    for s in secrets:
        if s.legacy_secret_class is None:
            s.legacy_secret_class = map_to_legacy_secret_class(s)

    web = TensionWeb(secrets=secrets, hooks=hooks, chains=chains, narrative_potential_score=0.0)
    score = score_narrative_potential(web, config, matrix)
    web = web.model_copy(update={"narrative_potential_score": score})

    rounds_done = 0
    while score < threshold and rounds_done < max_rounds:
        weakest = _weakest_dimension(web, config, matrix)
        strengthen_result = gateway.invoke_json(
            system_prompt=_STRENGTHEN_SYSTEM,
            user_payload={
                "current_web": web.model_dump(),
                "characters": char_summaries,
                "weakest_dimension": weakest,
                "current_score": score,
                "target_score": threshold,
            },
            max_output_tokens=gateway.max_output_tokens_tension_weaver,
            operation_name="author_v3_strengthen_tension",
        )
        new_secrets = _parse_secrets_from_llm(strengthen_result.parsed, char_ids)
        new_secret_ids = {s.secret_id for s in new_secrets}
        new_hooks = _parse_hooks_from_llm(strengthen_result.parsed, char_ids, new_secret_ids)
        new_chains = _parse_chains_from_llm(strengthen_result.parsed, new_secret_ids)
        for s in new_secrets:
            if s.legacy_secret_class is None:
                s.legacy_secret_class = map_to_legacy_secret_class(s)
        web = TensionWeb(secrets=new_secrets, hooks=new_hooks, chains=new_chains, narrative_potential_score=0.0)
        score = score_narrative_potential(web, config, matrix)
        web = web.model_copy(update={"narrative_potential_score": score})
        rounds_done += 1

    return web


def weave_secrets(
    config: WorldConfiguration,
    matrix: RelationshipMatrix,
    *,
    gateway: AuthorV3LLMGateway | None = None,
    max_rounds: int = 2,
    threshold: float = 0.6,
) -> TensionWeb:
    if gateway is None:
        return _weave_deterministic(config, matrix)
    return _weave_live(config, matrix, gateway, max_rounds, threshold)
