from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.contracts import RelationshipMatrix, WorldConfiguration
from rpg_backend.author_v3.gateway import (
    AuthorV3GatewayError,
    AuthorV3LLMGateway,
    get_author_v3_llm_gateway,
)
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


logger = logging.getLogger(__name__)

# Errors that signal "LLM produced unusable output"; we swallow these per-stage and
# fall back to deterministic so the author job still completes.
_STAGE_FALLBACK_EXCEPTIONS = (AuthorV3GatewayError, ValidationError, ValueError, KeyError, TypeError)


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
    config: WorldConfiguration | None = None
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
            if str(exc) in _WORLDLY_DESIRE_VALIDATION_ERRORS and gateway is not None and world_forge_attempt < 1:
                world_forge_validation_feedback = str(exc)
                continue
            # Any other LLM-side failure: fall back to deterministic so job still completes.
            if gateway is not None:
                logger.warning(
                    "[author_v3.workflow] forge_world LLM stage failed (%s); falling back to deterministic.",
                    exc,
                )
                config = forge_world(seed_text, gateway=None)
                break
            raise
        except _STAGE_FALLBACK_EXCEPTIONS as exc:
            if gateway is None:
                raise
            logger.warning(
                "[author_v3.workflow] forge_world LLM stage failed (%s); falling back to deterministic.",
                exc,
            )
            config = forge_world(seed_text, gateway=None)
            break
    assert config is not None  # appease type checkers
    matrix = build_relationship_matrix(config)
    try:
        web = weave_secrets(config, matrix, gateway=gateway, max_rounds=max_rounds, threshold=threshold)
    except _STAGE_FALLBACK_EXCEPTIONS as exc:
        if gateway is None:
            raise
        logger.warning(
            "[author_v3.workflow] weave_secrets LLM stage failed (%s); falling back to deterministic.",
            exc,
        )
        web = weave_secrets(config, matrix, gateway=None, max_rounds=max_rounds, threshold=threshold)
    try:
        pool = compile_storylet_pool(config, web, matrix, gateway=gateway)
    except _STAGE_FALLBACK_EXCEPTIONS as exc:
        if gateway is None:
            raise
        logger.warning(
            "[author_v3.workflow] compile_storylet_pool LLM stage failed (%s); falling back to deterministic.",
            exc,
        )
        pool = compile_storylet_pool(config, web, matrix, gateway=None)
    mapped_segments = map_storylets_to_segments(pool, arc_template_id, config, web, matrix)
    try:
        quality_report = evaluate_quality(config, web, pool, matrix, gateway=gateway)
    except _STAGE_FALLBACK_EXCEPTIONS as exc:
        if gateway is None:
            raise
        logger.warning(
            "[author_v3.workflow] evaluate_quality LLM stage failed (%s); falling back to deterministic.",
            exc,
        )
        quality_report = evaluate_quality(config, web, pool, matrix, gateway=None)
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
