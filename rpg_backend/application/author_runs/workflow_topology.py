from __future__ import annotations

from rpg_backend.application.author_runs.workflow_vocabulary import AuthorWorkflowNode


WORKFLOW_CONDITIONAL_ROUTES: dict[str, set[str]] = {
    AuthorWorkflowNode.GENERATE_STORY_OVERVIEW: {
        AuthorWorkflowNode.GENERATE_STORY_OVERVIEW,
        AuthorWorkflowNode.PLAN_BEATS,
        AuthorWorkflowNode.WORKFLOW_FAILED,
    },
    AuthorWorkflowNode.PLAN_BEATS: {
        AuthorWorkflowNode.PLAN_BEATS,
        AuthorWorkflowNode.GENERATE_BEAT_OUTLINE,
        AuthorWorkflowNode.WORKFLOW_FAILED,
    },
    AuthorWorkflowNode.MATERIALIZE_BEAT: {
        AuthorWorkflowNode.GENERATE_BEAT_OUTLINE,
        AuthorWorkflowNode.BEAT_LINT,
        AuthorWorkflowNode.WORKFLOW_FAILED,
    },
    AuthorWorkflowNode.BEAT_LINT: {
        AuthorWorkflowNode.GENERATE_BEAT_OUTLINE,
        AuthorWorkflowNode.ASSEMBLE_STORY_PACK,
        AuthorWorkflowNode.WORKFLOW_FAILED,
    },
    AuthorWorkflowNode.FINAL_LINT: {
        AuthorWorkflowNode.REVIEW_READY,
        AuthorWorkflowNode.WORKFLOW_FAILED,
    },
}


WORKFLOW_LINEAR_EDGES: tuple[tuple[str, str], ...] = (
    (AuthorWorkflowNode.GENERATE_BEAT_OUTLINE, AuthorWorkflowNode.MATERIALIZE_BEAT),
    (AuthorWorkflowNode.ASSEMBLE_STORY_PACK, AuthorWorkflowNode.NORMALIZE_STORY_PACK),
    (AuthorWorkflowNode.NORMALIZE_STORY_PACK, AuthorWorkflowNode.FINAL_LINT),
)
