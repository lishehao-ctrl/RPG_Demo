from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rpg_backend.application.author_runs.workflow_nodes import build_workflow_nodes
from rpg_backend.application.author_runs.workflow_retry import (
    AuthorRunEventRecorder,
    AuthorRunNodeStartRecorder,
    tracked_node,
)
from rpg_backend.application.author_runs.workflow_routes import build_workflow_routes
from rpg_backend.application.author_runs.workflow_state import AuthorWorkflowState
from rpg_backend.application.author_runs.workflow_topology import (
    WORKFLOW_CONDITIONAL_ROUTES,
    WORKFLOW_LINEAR_EDGES,
)
from rpg_backend.application.author_runs.workflow_vocabulary import (
    AUTHOR_WORKFLOW_GRAPH_NODE_ALL,
    AuthorWorkflowNode,
)
from rpg_backend.generator.author_workflow_chains import BeatGenerationChain, StoryOverviewChain
from rpg_backend.generator.author_workflow_policy import AuthorWorkflowPolicy


def build_author_workflow_graph(
    *,
    overview_chain_factory: Callable[..., StoryOverviewChain],
    beat_chain_factory: Callable[..., BeatGenerationChain],
    policy: AuthorWorkflowPolicy,
    mark_run_node_started: AuthorRunNodeStartRecorder,
    record_run_node_event: AuthorRunEventRecorder,
):
    from langgraph.graph import END, START, StateGraph

    node_handlers = build_workflow_nodes(
        overview_chain_factory=overview_chain_factory,
        beat_chain_factory=beat_chain_factory,
        policy=policy,
    )
    routes = build_workflow_routes(policy=policy)

    builder = StateGraph(AuthorWorkflowState)

    for node_name in AUTHOR_WORKFLOW_GRAPH_NODE_ALL:
        builder.add_node(
            node_name,
            tracked_node(
                node_name=node_name,
                func=node_handlers[node_name],
                policy=policy,
                mark_run_node_started=mark_run_node_started,
                record_run_node_event=record_run_node_event,
            ),
        )

    builder.add_edge(START, AuthorWorkflowNode.GENERATE_STORY_OVERVIEW)

    for source_node, route in routes.items():
        builder.add_conditional_edges(
            source_node,
            route,
            {target_node: target_node for target_node in WORKFLOW_CONDITIONAL_ROUTES[source_node]},
        )

    for source_node, target_node in WORKFLOW_LINEAR_EDGES:
        builder.add_edge(source_node, target_node)

    builder.add_edge(AuthorWorkflowNode.REVIEW_READY, END)
    builder.add_edge(AuthorWorkflowNode.WORKFLOW_FAILED, END)
    return builder.compile()


__all__ = [
    "WORKFLOW_CONDITIONAL_ROUTES",
    "WORKFLOW_LINEAR_EDGES",
    "build_author_workflow_graph",
]
