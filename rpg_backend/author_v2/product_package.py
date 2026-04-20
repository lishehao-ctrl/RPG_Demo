from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rpg_backend.author_v2.contracts import (
    AcceptedBlueprint,
    CompiledPlayPlan,
    UrbanAuthorBundle,
    UrbanPreviewBlueprint,
)


class RelationshipDramaV2Package(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_version: Literal["relationship_drama_v2"] = "relationship_drama_v2"
    preview_blueprint: UrbanPreviewBlueprint
    accepted_blueprint: AcceptedBlueprint
    urban_bundle: UrbanAuthorBundle
    compiled_play_plan: CompiledPlayPlan
    quality_trace: list[dict[str, object]] = Field(default_factory=list)
    llm_call_trace: list[dict[str, object]] = Field(default_factory=list)
