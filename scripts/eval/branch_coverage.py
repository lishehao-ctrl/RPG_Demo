from __future__ import annotations

from collections import defaultdict
from typing import Any


def analyze_branch_graph(pack_json: dict[str, Any]) -> dict[str, Any]:
    beats = [item for item in pack_json.get("beats", []) if isinstance(item, dict)]
    scenes = [item for item in pack_json.get("scenes", []) if isinstance(item, dict)]
    moves = [item for item in pack_json.get("moves", []) if isinstance(item, dict)]
    move_ids = {str(item.get("id")) for item in moves if isinstance(item.get("id"), str)}

    scene_map = {str(scene.get("id")): scene for scene in scenes if isinstance(scene.get("id"), str)}
    entry_scene_id = str(beats[0].get("entry_scene_id")) if beats and isinstance(beats[0].get("entry_scene_id"), str) else None

    edges: list[dict[str, Any]] = []
    edges_by_scene: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scene in scenes:
        scene_id = scene.get("id")
        if not isinstance(scene_id, str):
            continue
        available_moves = {
            str(move_id)
            for move_id in [*(scene.get("enabled_moves") or []), *(scene.get("always_available_moves") or [])]
            if isinstance(move_id, str)
        }
        for cond in scene.get("exit_conditions", []) or []:
            if not isinstance(cond, dict):
                continue
            next_scene_id = cond.get("next_scene_id")
            trigger_move_id = None
            if cond.get("condition_kind") == "state_equals" and cond.get("key") == "last_move" and isinstance(cond.get("value"), str):
                trigger_move_id = cond["value"]
            edge = {
                "edge_id": str(cond.get("id") or f"{scene_id}->{next_scene_id or 'end'}"),
                "from_scene_id": scene_id,
                "to_scene_id": str(next_scene_id) if isinstance(next_scene_id, str) else None,
                "condition_kind": str(cond.get("condition_kind") or "always"),
                "key": cond.get("key"),
                "value": cond.get("value"),
                "end_story": bool(cond.get("end_story", False)),
                "trigger_move_id": trigger_move_id,
                "triggerable": trigger_move_id is None or (trigger_move_id in available_moves and trigger_move_id in move_ids),
            }
            edges.append(edge)
            edges_by_scene[scene_id].append(edge)

    reachable_scene_ids: set[str] = set()
    reachable_edge_ids: set[str] = set()
    if entry_scene_id and entry_scene_id in scene_map:
        stack = [entry_scene_id]
        while stack:
            scene_id = stack.pop()
            if scene_id in reachable_scene_ids:
                continue
            reachable_scene_ids.add(scene_id)
            for edge in edges_by_scene.get(scene_id, []):
                reachable_edge_ids.add(edge["edge_id"])
                next_scene_id = edge.get("to_scene_id")
                if isinstance(next_scene_id, str) and next_scene_id in scene_map and next_scene_id not in reachable_scene_ids:
                    stack.append(next_scene_id)

    unreachable_scene_ids = sorted(scene_id for scene_id in scene_map if scene_id not in reachable_scene_ids)
    branch_points = [
        {
            "scene_id": scene_id,
            "edge_ids": [edge["edge_id"] for edge in scene_edges],
        }
        for scene_id, scene_edges in edges_by_scene.items()
        if len(scene_edges) > 1 and scene_id in reachable_scene_ids
    ]

    terminal_edge_ids = {
        edge["edge_id"]
        for edge in edges
        if edge["end_story"] or edge.get("to_scene_id") is None or bool(scene_map.get(edge.get("to_scene_id") or "", {}).get("is_terminal", False))
    }
    conditional_edge_ids = {edge["edge_id"] for edge in edges if edge["condition_kind"] != "always"}

    terminal_paths: list[list[str]] = []
    if entry_scene_id and entry_scene_id in scene_map:
        def walk(scene_id: str, path: list[str]) -> None:
            scene = scene_map[scene_id]
            scene_edges = edges_by_scene.get(scene_id, [])
            if bool(scene.get("is_terminal")) or not scene_edges:
                terminal_paths.append(path[:])
                return
            for edge in scene_edges:
                next_scene_id = edge.get("to_scene_id")
                if edge["end_story"] or not isinstance(next_scene_id, str) or next_scene_id not in scene_map:
                    terminal_paths.append(path[:])
                    continue
                if next_scene_id in path:
                    continue
                walk(next_scene_id, [*path, next_scene_id])
        walk(entry_scene_id, [entry_scene_id])

    return {
        "entry_scene_id": entry_scene_id,
        "scene_count": len(scene_map),
        "edge_count": len(edges),
        "reachable_scene_ids": sorted(reachable_scene_ids),
        "reachable_edge_ids": sorted(reachable_edge_ids),
        "unreachable_scene_ids": unreachable_scene_ids,
        "branch_points": branch_points,
        "edges": edges,
        "edges_by_scene": {key: value for key, value in edges_by_scene.items()},
        "terminal_edge_ids": sorted(terminal_edge_ids),
        "conditional_edge_ids": sorted(conditional_edge_ids),
        "terminal_paths": terminal_paths,
    }


def summarize_branch_coverage(*, graph: dict[str, Any], play_reports: list[dict[str, Any]]) -> dict[str, Any]:
    visited_scene_ids: set[str] = set()
    covered_edge_ids: set[str] = set()
    covered_terminal_paths: set[tuple[str, ...]] = set()

    edge_lookup: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.get("edges", []):
        edge_lookup[(edge.get("from_scene_id"), edge.get("to_scene_id"))].append(edge)

    for report in play_reports:
        scene_path = report.get("scene_path") or []
        if isinstance(scene_path, list):
            normalized_path = tuple(str(item) for item in scene_path if isinstance(item, str))
            visited_scene_ids.update(normalized_path)
            if normalized_path:
                terminal_paths = {tuple(path) for path in graph.get("terminal_paths", [])}
                if normalized_path in terminal_paths:
                    covered_terminal_paths.add(normalized_path)

        for edge_hit in report.get("traversed_edges") or []:
            if not isinstance(edge_hit, dict):
                continue
            from_scene = edge_hit.get("from_scene_id")
            to_scene = edge_hit.get("to_scene_id")
            move_id = edge_hit.get("move_id")
            candidates = edge_lookup.get((from_scene, to_scene), [])
            selected = None
            if isinstance(move_id, str):
                for edge in candidates:
                    if edge.get("trigger_move_id") == move_id:
                        selected = edge
                        break
            if selected is None and candidates:
                selected = candidates[0]
            if selected is not None:
                covered_edge_ids.add(str(selected["edge_id"]))

    reachable_scene_ids = set(graph.get("reachable_scene_ids") or [])
    reachable_edge_ids = set(graph.get("reachable_edge_ids") or [])
    conditional_edge_ids = set(graph.get("conditional_edge_ids") or [])
    terminal_edge_ids = set(graph.get("terminal_edge_ids") or [])
    terminal_paths = {tuple(path) for path in graph.get("terminal_paths") or []}

    return {
        "scene_covered_count": len(visited_scene_ids & reachable_scene_ids),
        "scene_total": len(reachable_scene_ids),
        "scene_coverage_rate": (len(visited_scene_ids & reachable_scene_ids) / len(reachable_scene_ids)) if reachable_scene_ids else 0.0,
        "edge_covered_count": len(covered_edge_ids & reachable_edge_ids),
        "edge_total": len(reachable_edge_ids),
        "edge_coverage_rate": (len(covered_edge_ids & reachable_edge_ids) / len(reachable_edge_ids)) if reachable_edge_ids else 0.0,
        "conditional_edge_covered_count": len(covered_edge_ids & conditional_edge_ids),
        "conditional_edge_total": len(conditional_edge_ids),
        "conditional_edge_coverage_rate": (len(covered_edge_ids & conditional_edge_ids) / len(conditional_edge_ids)) if conditional_edge_ids else 1.0,
        "terminal_edge_covered_count": len(covered_edge_ids & terminal_edge_ids),
        "terminal_edge_total": len(terminal_edge_ids),
        "terminal_edge_coverage_rate": (len(covered_edge_ids & terminal_edge_ids) / len(terminal_edge_ids)) if terminal_edge_ids else 1.0,
        "terminal_path_covered_count": len(covered_terminal_paths & terminal_paths),
        "terminal_path_total": len(terminal_paths),
        "terminal_path_coverage_rate": (len(covered_terminal_paths & terminal_paths) / len(terminal_paths)) if terminal_paths else 1.0,
        "visited_scene_ids": sorted(visited_scene_ids),
        "covered_edge_ids": sorted(covered_edge_ids),
        "unreachable_scene_ids": list(graph.get("unreachable_scene_ids") or []),
        "untriggerable_conditional_edges": [
            edge["edge_id"]
            for edge in graph.get("edges", [])
            if edge.get("condition_kind") != "always" and not edge.get("triggerable", False)
        ],
    }
