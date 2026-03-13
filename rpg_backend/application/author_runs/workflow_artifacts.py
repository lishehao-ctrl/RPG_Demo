from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from rpg_backend.application.author_runs.workflow_vocabulary import AuthorWorkflowArtifactType
from rpg_backend.generator.author_workflow_models import model_to_json_payload


@dataclass(frozen=True)
class PersistedArtifact:
    artifact_type: str
    artifact_key: str
    payload: dict[str, Any]


def artifact_payload_from_state(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): artifact_payload_from_state(item) for key, item in value.items()}
    if isinstance(value, list):
        return {"items": [model_to_json_payload(item) if hasattr(item, "model_dump") else item for item in value]}
    return {"value": value}


def build_persisted_artifacts_for_update(update: dict[str, Any]) -> list[PersistedArtifact]:
    artifacts: list[PersistedArtifact] = []
    if "overview" in update:
        artifacts.append(PersistedArtifact(AuthorWorkflowArtifactType.OVERVIEW, "", artifact_payload_from_state(update["overview"])))
    if "overview_errors" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.STORY_OVERVIEW_VALIDATION,
                "",
                {"errors": list(update["overview_errors"])},
            )
        )
    if "beat_blueprints" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.BEAT_BLUEPRINTS,
                "",
                artifact_payload_from_state(update["beat_blueprints"]),
            )
        )
    if "beat_plan_errors" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.BEAT_PLAN_VALIDATION,
                "",
                {"errors": list(update["beat_plan_errors"])},
            )
        )
    if "beat_overview_context" in update and update["beat_overview_context"] is not None:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.BEAT_OVERVIEW_CONTEXT,
                str(update.get("current_beat_index", "")),
                artifact_payload_from_state(update["beat_overview_context"]),
            )
        )
    if "current_beat_draft" in update and update["current_beat_draft"] is not None:
        beat = update["current_beat_draft"]
        beat_id = beat.beat_id if hasattr(beat, "beat_id") else str(update.get("current_beat_index", ""))
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.CURRENT_BEAT_DRAFT,
                beat_id,
                artifact_payload_from_state(beat),
            )
        )
    if "beat_drafts" in update:
        for beat in update["beat_drafts"]:
            artifacts.append(
                PersistedArtifact(
                    AuthorWorkflowArtifactType.ACCEPTED_BEAT_DRAFT,
                    beat.beat_id,
                    artifact_payload_from_state(beat),
                )
            )
    if "beat_lint_errors" in update or "beat_lint_warnings" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.BEAT_LINT,
                str(update.get("current_beat_index", "")),
                {
                    "errors": list(update.get("beat_lint_errors") or []),
                    "warnings": list(update.get("beat_lint_warnings") or []),
                },
            )
        )
    if "prefix_summary" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.PREFIX_SUMMARY,
                str(update.get("current_beat_index", "")),
                artifact_payload_from_state(update["prefix_summary"]),
            )
        )
    if "author_memory" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.AUTHOR_MEMORY,
                str(update.get("current_beat_index", "")),
                artifact_payload_from_state(update["author_memory"]),
            )
        )
    if "story_pack" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.STORY_PACK,
                "",
                artifact_payload_from_state(update["story_pack"]),
            )
        )
    if "story_pack_normalization_errors" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.STORY_PACK_NORMALIZATION,
                "",
                {"errors": list(update.get("story_pack_normalization_errors") or [])},
            )
        )
    if "final_lint_errors" in update or "final_lint_warnings" in update:
        artifacts.append(
            PersistedArtifact(
                AuthorWorkflowArtifactType.FINAL_LINT,
                "",
                {
                    "errors": list(update.get("final_lint_errors") or []),
                    "warnings": list(update.get("final_lint_warnings") or []),
                },
            )
        )
    return artifacts
