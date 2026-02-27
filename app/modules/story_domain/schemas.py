from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.modules.story_domain.default_endings import DEFAULT_ENDINGS
from app.modules.story_domain.default_fallbacks import DEFAULT_FALLBACKS

FallbackReasonCode = Literal["NO_MATCH", "LOW_CONF", "INPUT_POLICY", "OFF_TOPIC"]
EndingOutcome = Literal["fail", "neutral", "success"]
EndingCamp = Literal["player", "enemy", "world"]
TierLabel = Literal["Hostile", "Wary", "Neutral", "Warm", "Close"]
RangeTargetType = Literal["player", "npc"]
ReactionSource = Literal["choice", "fallback", "any"]

_PLAYER_METRICS = {"energy", "money", "knowledge", "affection"}
_NPC_METRICS = {"affection", "trust"}
_DEFAULT_THRESHOLDS = [-60, -20, 20, 60]


class RangeEffectV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: RangeTargetType
    metric: str
    center: int
    intensity: int = Field(ge=0)
    target_id: str | None = None

    @model_validator(mode="after")
    def validate_target_and_metric(self):
        metric = str(self.metric or "").strip()
        self.metric = metric

        if self.target_type == "player":
            if self.target_id is not None and str(self.target_id).strip():
                raise ValueError("range_effect player target must not set target_id")
            if metric not in _PLAYER_METRICS:
                raise ValueError(f"unsupported player metric: {metric}")
            self.target_id = None
            return self

        target_id = str(self.target_id or "").strip()
        if not target_id:
            raise ValueError("range_effect npc target requires target_id")
        if metric not in _NPC_METRICS:
            raise ValueError(f"unsupported npc metric: {metric}")
        self.target_id = target_id
        return self


class ChoiceGateRuleV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(min_length=1)
    min_affection_tier: TierLabel | None = None
    min_trust_tier: TierLabel | None = None

    @model_validator(mode="after")
    def validate_minimum(self):
        if self.min_affection_tier is None and self.min_trust_tier is None:
            raise ValueError("gate_rule must define at least one minimum tier")
        return self


class GlobalFallbackV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fallback_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    target_node_id: str | None = None
    range_effects: list[RangeEffectV2] = Field(min_length=1)
    reason_code: FallbackReasonCode | None = None
    mainline_nudge: str | None = None
    prompt_profile_id: str | None = "fallback_default_v1"
    ending_id: str | None = None
    reactive_npc_ids: list[str] = Field(default_factory=list)


class EndingDefV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    outcome: EndingOutcome
    camp: EndingCamp = "world"
    epilogue: str = Field(min_length=1)
    prompt_profile_id: str | None = "ending_default_v2"


class FallbackPolicyV20(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_default_fallbacks: bool = True
    fallback_overrides: list[GlobalFallbackV2] = Field(default_factory=list)
    forced_fallback_ending_id: str | None = "ending_forced_fail"
    forced_fallback_threshold: int = Field(default=3, ge=1)


class EndingPolicyV20(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_default_endings: bool = True
    ending_overrides: list[EndingDefV1] = Field(default_factory=list)


class NpcDefV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    initial_affection: int = 0
    initial_trust: int = 0
    affection_thresholds: list[int] = Field(default_factory=lambda: list(_DEFAULT_THRESHOLDS))
    trust_thresholds: list[int] = Field(default_factory=lambda: list(_DEFAULT_THRESHOLDS))

    @model_validator(mode="after")
    def validate_thresholds(self):
        self.affection_thresholds = _validate_thresholds(self.affection_thresholds, "affection_thresholds")
        self.trust_thresholds = _validate_thresholds(self.trust_thresholds, "trust_thresholds")
        return self


class ChoiceV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choice_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    intent_tags: list[str] = Field(default_factory=list)
    next_node_id: str = Field(min_length=1)
    range_effects: list[RangeEffectV2] = Field(min_length=1)
    gate_rules: list[ChoiceGateRuleV2] = Field(default_factory=list)
    ending_id: str | None = None
    reactive_npc_ids: list[str] = Field(default_factory=list)


class NpcReactionRuleV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: TierLabel
    source: ReactionSource = "any"
    effects: list[RangeEffectV2] = Field(min_length=1)
    narrative_hint: str | None = None


class NpcReactionPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(min_length=1)
    rules: list[NpcReactionRuleV2] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_rule_keys(self):
        seen: set[tuple[str, str]] = set()
        for item in self.rules:
            key = (str(item.tier), str(item.source))
            if key in seen:
                raise ValueError(f"duplicate npc reaction rule key for npc_id={self.npc_id}: {key}")
            seen.add(key)
        return self


class SceneNodeV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    scene_brief: str = Field(min_length=1)
    node_fallback_id: str | None = None
    choices: list[ChoiceV2] = Field(min_length=1)


class StoryPackV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"]
    story_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    start_node_id: str = Field(min_length=1)

    npc_defs: list[NpcDefV2] = Field(default_factory=list)
    npc_reaction_policies: list[NpcReactionPolicyV2] = Field(default_factory=list)
    global_fallbacks: list[GlobalFallbackV2] = Field(default_factory=list)
    nodes: list[SceneNodeV2] = Field(min_length=1)

    fallback_policy: FallbackPolicyV20 = Field(default_factory=FallbackPolicyV20)
    ending_defs: list[EndingDefV1] = Field(default_factory=list)
    ending_policy: EndingPolicyV20 = Field(default_factory=EndingPolicyV20)

    @model_validator(mode="after")
    def validate_connectivity_and_constraints(self):
        node_ids = [n.node_id for n in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("duplicate node_id in nodes")

        node_set = set(node_ids)
        if self.start_node_id not in node_set:
            raise ValueError("start_node_id must exist in nodes")

        npc_ids = [n.npc_id for n in self.npc_defs]
        if len(set(npc_ids)) != len(npc_ids):
            raise ValueError("duplicate npc_id in npc_defs")
        npc_set = set(npc_ids)

        for node in self.nodes:
            choice_ids = [c.choice_id for c in node.choices]
            if len(set(choice_ids)) != len(choice_ids):
                raise ValueError(f"duplicate choice_id in node {node.node_id}")
            for choice in node.choices:
                if choice.next_node_id not in node_set:
                    raise ValueError(f"choice.next_node_id not found: {choice.next_node_id}")
                for effect in choice.range_effects:
                    if effect.target_type == "npc" and str(effect.target_id) not in npc_set:
                        raise ValueError(f"choice npc target_id not found: {effect.target_id}")
                for gate in choice.gate_rules:
                    if gate.npc_id not in npc_set:
                        raise ValueError(f"choice gate npc_id not found: {gate.npc_id}")
                for npc_id in choice.reactive_npc_ids:
                    if str(npc_id) not in npc_set:
                        raise ValueError(f"choice reactive_npc_id not found: {npc_id}")

        effective_fallbacks, effective_endings = resolve_effective_fallbacks_endings(self)
        if not effective_fallbacks:
            raise ValueError("effective fallback set cannot be empty")

        fallback_ids = {item.fallback_id for item in effective_fallbacks}
        reason_set: set[str] = set()
        for fallback in effective_fallbacks:
            if fallback.target_node_id and fallback.target_node_id not in node_set:
                raise ValueError(f"fallback target_node_id not found: {fallback.target_node_id}")
            if fallback.mainline_nudge is not None and not str(fallback.mainline_nudge).strip():
                raise ValueError(f"fallback {fallback.fallback_id} mainline_nudge cannot be blank")
            if fallback.reason_code:
                if fallback.reason_code in reason_set:
                    raise ValueError(f"duplicate fallback reason_code in effective fallbacks: {fallback.reason_code}")
                reason_set.add(fallback.reason_code)
            for effect in fallback.range_effects:
                if effect.target_type == "npc" and str(effect.target_id) not in npc_set:
                    raise ValueError(f"fallback npc target_id not found: {effect.target_id}")
            for npc_id in fallback.reactive_npc_ids:
                if str(npc_id) not in npc_set:
                    raise ValueError(f"fallback reactive_npc_id not found: {npc_id}")

        for node in self.nodes:
            if node.node_fallback_id is not None and node.node_fallback_id not in fallback_ids:
                raise ValueError(f"node_fallback_id not found in effective fallbacks: {node.node_fallback_id}")

        ending_ids = {item.ending_id for item in effective_endings}
        for node in self.nodes:
            for choice in node.choices:
                if choice.ending_id is not None and choice.ending_id not in ending_ids:
                    raise ValueError(f"choice ending_id not found in effective endings: {choice.ending_id}")
        for fallback in effective_fallbacks:
            if fallback.ending_id is not None and fallback.ending_id not in ending_ids:
                raise ValueError(f"fallback ending_id not found in effective endings: {fallback.ending_id}")

        reaction_policy_npcs: set[str] = set()
        for policy in self.npc_reaction_policies:
            if policy.npc_id not in npc_set:
                raise ValueError(f"npc_reaction_policy npc_id not found: {policy.npc_id}")
            if policy.npc_id in reaction_policy_npcs:
                raise ValueError(f"duplicate npc_reaction_policy npc_id: {policy.npc_id}")
            reaction_policy_npcs.add(policy.npc_id)
            for rule in policy.rules:
                for effect in rule.effects:
                    if effect.target_type == "npc" and str(effect.target_id) not in npc_set:
                        raise ValueError(f"npc_reaction effect target_id not found: {effect.target_id}")

        forced_ending_id = self.fallback_policy.forced_fallback_ending_id
        if forced_ending_id is not None and forced_ending_id not in ending_ids:
            raise ValueError("forced_fallback_ending_id must exist in effective ending set")

        return self


def _validate_thresholds(values: list[int], field_name: str) -> list[int]:
    normalized = [int(v) for v in values]
    if len(normalized) != 4:
        raise ValueError(f"{field_name} must contain exactly 4 integers")
    if normalized != sorted(normalized):
        raise ValueError(f"{field_name} must be sorted ascending")
    if len(set(normalized)) != 4:
        raise ValueError(f"{field_name} must contain unique values")
    if normalized[0] < -100 or normalized[-1] > 100:
        raise ValueError(f"{field_name} values must stay within [-100,100]")
    return normalized


def resolve_effective_fallbacks_endings(pack: StoryPackV2) -> tuple[list[GlobalFallbackV2], list[EndingDefV1]]:
    fallback_by_id: dict[str, GlobalFallbackV2] = {}
    if pack.fallback_policy.include_default_fallbacks:
        for raw in DEFAULT_FALLBACKS:
            item = GlobalFallbackV2.model_validate(raw)
            fallback_by_id[item.fallback_id] = item

    for item in pack.global_fallbacks:
        fallback_by_id[item.fallback_id] = item

    for item in pack.fallback_policy.fallback_overrides:
        fallback_by_id[item.fallback_id] = item

    ending_by_id: dict[str, EndingDefV1] = {}
    if pack.ending_policy.include_default_endings:
        for raw in DEFAULT_ENDINGS:
            item = EndingDefV1.model_validate(raw)
            ending_by_id[item.ending_id] = item

    for item in pack.ending_defs:
        ending_by_id[item.ending_id] = item

    for item in pack.ending_policy.ending_overrides:
        ending_by_id[item.ending_id] = item

    return list(fallback_by_id.values()), list(ending_by_id.values())


# Compatibility aliases for older imports in the codebase/tests.
StoryPackV1 = StoryPackV2
GlobalFallbackV1 = GlobalFallbackV2
FallbackPolicyV11 = FallbackPolicyV20
EndingPolicyV11 = EndingPolicyV20
ChoiceV1 = ChoiceV2
SceneNodeV1 = SceneNodeV2


class StoryValidateRequest(BaseModel):
    pack: dict


class StoryValidateResponse(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


AuditSeverity = Literal["error", "warning"]


class StoryAuditIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: AuditSeverity
    path: str
    message: str
    suggestion: str | None = None


class StoryAuditRequest(BaseModel):
    pack: dict


class StoryAuditResponse(BaseModel):
    ok: bool
    errors: list[StoryAuditIssue] = Field(default_factory=list)
    warnings: list[StoryAuditIssue] = Field(default_factory=list)


class StoryCreateRequest(BaseModel):
    story_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    pack: dict
    owner_user_id: str | None = None


class StoryCreateResponse(BaseModel):
    story_id: str
    version: int
    status: str


class StoryPublishRequest(BaseModel):
    version: int = Field(ge=1)


class StoryPublishResponse(BaseModel):
    story_id: str
    version: int
    status: str
    warnings: list[StoryAuditIssue] = Field(default_factory=list)


class StoryPublishedResponse(BaseModel):
    story_id: str
    version: int
    pack: dict


class StoryCatalogItem(BaseModel):
    story_id: str
    title: str
    published_version: int
    updated_at: datetime

    @field_serializer("updated_at")
    def serialize_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class StoryCatalogResponse(BaseModel):
    stories: list[StoryCatalogItem] = Field(default_factory=list)


StoryVersionStatus = Literal["draft", "published", "archived"]


class StoryVersionSummary(BaseModel):
    story_id: str
    version: int
    status: StoryVersionStatus
    checksum: str
    created_by: str
    created_at: datetime
    published_at: datetime | None = None

    @field_serializer("created_at", "published_at")
    def serialize_utc_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class StoryVersionDetail(StoryVersionSummary):
    title: str
    pack: dict


class StoryVersionListResponse(BaseModel):
    story_id: str
    versions: list[StoryVersionSummary] = Field(default_factory=list)


class StoryDraftCreateRequest(BaseModel):
    title: str | None = None


class StoryDraftUpdateRequest(BaseModel):
    title: str | None = None
    pack: dict
