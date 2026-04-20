from __future__ import annotations

from typing import Any

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.gateway import AuthorV3LLMGateway, get_author_v3_llm_gateway
from rpg_backend.author_v3.plan_bridge import bridge_to_plan
from rpg_backend.author_v3.quality_evaluator import QualityReport, evaluate_quality
from rpg_backend.author_v3.relationship_matrix import build_relationship_matrix
from rpg_backend.author_v3.storylet_compiler import (
    MappedSegment,
    StoryletPool,
    compile_storylet_pool,
    map_storylets_to_segments,
)
from rpg_backend.author_v3.tension_weaver import TensionWeb, weave_secrets
from rpg_backend.author_v3.world_forge import _WORLDLY_DESIRE_VALIDATION_ERRORS, forge_world
from rpg_backend.config import Settings, get_settings


class AuthorV3PipelineError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def run_author_v3_pipeline(
    seed_text: str,
    *,
    run_mode: str = "deterministic",
    settings: Settings | None = None,
    arc_template_id: str = "flagship_6",
) -> dict[str, Any]:
    resolved_settings = settings or get_settings()
    gateway: AuthorV3LLMGateway | None = None
    if run_mode != "deterministic":
        gateway = get_author_v3_llm_gateway(run_mode, resolved_settings)

    max_rounds = resolved_settings.author_v3_max_llm_rounds
    threshold = resolved_settings.author_v3_tension_score_threshold

    world_forge_validation_feedback: str | None = None
    for world_forge_attempt in range(2):
        try:
            config = forge_world(
                seed_text,
                gateway=gateway,
                validation_feedback=world_forge_validation_feedback,
                validation_retry=world_forge_attempt,
            )
            break
        except ValueError as exc:
            if (
                gateway is None
                or world_forge_attempt >= 1
                or str(exc) not in _WORLDLY_DESIRE_VALIDATION_ERRORS
            ):
                raise
            world_forge_validation_feedback = str(exc)
    matrix = build_relationship_matrix(config)
    web = weave_secrets(config, matrix, gateway=gateway, max_rounds=max_rounds, threshold=threshold)
    pool = compile_storylet_pool(config, web, matrix, gateway=gateway)
    mapped_segments = map_storylets_to_segments(pool, arc_template_id, config, web, matrix)
    quality_report = evaluate_quality(config, web, pool, matrix, gateway=gateway)
    plan = bridge_to_plan(
        config, matrix, web, pool, mapped_segments, quality_report,
        arc_template_id=arc_template_id,
    )

    return {
        "plan": plan,
        "quality_report": quality_report,
        "world_config": config,
        "tension_web": web,
        "storylet_pool": pool,
        "relationship_matrix": matrix,
        "mapped_segments": mapped_segments,
    }
