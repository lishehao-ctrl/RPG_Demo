from __future__ import annotations

import json
from pathlib import Path

from scripts.eval.branch_coverage import analyze_branch_graph, summarize_branch_coverage

PACK_PATH = Path('sample_data/story_pack_v1.json')


def _sample_pack() -> dict:
    return json.loads(PACK_PATH.read_text(encoding='utf-8'))


def test_analyze_branch_graph_reports_expected_branch_points() -> None:
    graph = analyze_branch_graph(_sample_pack())
    assert graph['entry_scene_id'] == 'sc1'
    assert graph['scene_count'] >= 10
    branch_scene_ids = {item['scene_id'] for item in graph['branch_points']}
    assert 'sc2' in branch_scene_ids
    assert not graph['unreachable_scene_ids']


def test_summarize_branch_coverage_counts_edges_and_paths() -> None:
    graph = analyze_branch_graph(_sample_pack())
    report = {
        'scene_path': ['sc1', 'sc2', 'sc3', 'sc5'],
        'traversed_edges': [
            {'from_scene_id': 'sc1', 'to_scene_id': 'sc2', 'move_id': 'trace_anomaly'},
            {'from_scene_id': 'sc2', 'to_scene_id': 'sc3', 'move_id': 'trace_anomaly'},
            {'from_scene_id': 'sc3', 'to_scene_id': 'sc5', 'move_id': 'inspect_infrastructure'},
        ],
    }
    coverage = summarize_branch_coverage(graph=graph, play_reports=[report])
    assert coverage['scene_covered_count'] >= 4
    assert coverage['edge_covered_count'] >= 3
    assert coverage['edge_coverage_rate'] > 0.0


def test_analyze_branch_graph_flags_untriggerable_branch_edge() -> None:
    graph = analyze_branch_graph(_sample_pack())
    branch_edge = next(edge for edge in graph['edges'] if edge['edge_id'] == 'branch_sneak')
    assert branch_edge['trigger_move_id'] == 'sneak_route'
    assert branch_edge['triggerable'] is False
