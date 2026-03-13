from __future__ import annotations

from enum import StrEnum


class AuthorWorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEW_READY = "review_ready"
    FAILED = "failed"


class AuthorWorkflowNode(StrEnum):
    GENERATE_STORY_OVERVIEW = "generate_story_overview"
    PLAN_BEATS = "plan_beats"
    GENERATE_BEAT_OUTLINE = "generate_beat_outline"
    MATERIALIZE_BEAT = "materialize_beat"
    BEAT_LINT = "beat_lint"
    ASSEMBLE_STORY_PACK = "assemble_story_pack"
    NORMALIZE_STORY_PACK = "normalize_story_pack"
    FINAL_LINT = "final_lint"
    REVIEW_READY = "review_ready"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_ROOT = "workflow"


class AuthorWorkflowEventType(StrEnum):
    NODE_STARTED = "node_started"
    NODE_RETRY = "node_retry"
    NODE_COMPLETED = "node_completed"
    RUN_COMPLETED = "run_completed"
    RUN_EXCEPTION = "run_exception"


class AuthorWorkflowArtifactType(StrEnum):
    RAW_BRIEF = "raw_brief"
    OVERVIEW = "overview"
    STORY_OVERVIEW_VALIDATION = "story_overview_validation"
    BEAT_BLUEPRINTS = "beat_blueprints"
    BEAT_PLAN_VALIDATION = "beat_plan_validation"
    BEAT_OVERVIEW_CONTEXT = "beat_overview_context"
    CURRENT_BEAT_OUTLINE = "current_beat_outline"
    CURRENT_BEAT_DRAFT = "current_beat_draft"
    ACCEPTED_BEAT_DRAFT = "accepted_beat_draft"
    BEAT_MATERIALIZATION = "beat_materialization"
    BEAT_LINT = "beat_lint"
    PREFIX_SUMMARY = "prefix_summary"
    AUTHOR_MEMORY = "author_memory"
    STORY_PACK = "story_pack"
    STORY_PACK_NORMALIZATION = "story_pack_normalization"
    FINAL_LINT = "final_lint"
    WORKFLOW_ERROR = "workflow_error"


class AuthorWorkflowErrorCode(StrEnum):
    AUTHOR_NODE_TIMEOUT = "author_node_timeout"
    AUTHOR_WORKFLOW_FAILED = "author_workflow_failed"
    AUTHOR_WORKFLOW_EXCEPTION = "author_workflow_exception"
    PROMPT_COMPILE_FAILED = "prompt_compile_failed"


AUTHOR_WORKFLOW_STATUS_ALL = frozenset(AuthorWorkflowStatus)
AUTHOR_WORKFLOW_STATUS_TERMINAL = frozenset(
    {
        AuthorWorkflowStatus.REVIEW_READY,
        AuthorWorkflowStatus.FAILED,
    }
)
AUTHOR_WORKFLOW_STATUS_ACTIVE = frozenset(
    {
        AuthorWorkflowStatus.PENDING,
        AuthorWorkflowStatus.RUNNING,
    }
)

AUTHOR_WORKFLOW_NODE_ALL: tuple[AuthorWorkflowNode, ...] = tuple(AuthorWorkflowNode)
AUTHOR_WORKFLOW_GRAPH_NODE_ALL: tuple[AuthorWorkflowNode, ...] = tuple(
    node for node in AuthorWorkflowNode if node != AuthorWorkflowNode.WORKFLOW_ROOT
)
AUTHOR_WORKFLOW_NODE_TERMINAL = frozenset(
    {
        AuthorWorkflowNode.REVIEW_READY,
        AuthorWorkflowNode.WORKFLOW_FAILED,
    }
)

AUTHOR_WORKFLOW_EVENT_TYPE_ALL = frozenset(AuthorWorkflowEventType)
AUTHOR_WORKFLOW_ARTIFACT_TYPE_ALL = frozenset(AuthorWorkflowArtifactType)
AUTHOR_WORKFLOW_ERROR_CODE_ALL = frozenset(AuthorWorkflowErrorCode)
