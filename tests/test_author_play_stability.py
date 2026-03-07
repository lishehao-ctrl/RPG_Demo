from __future__ import annotations

from scripts.release.run_author_play_stability import _case_pass


def test_case_pass_returns_true_when_all_metrics_meet_thresholds() -> None:
    case_result = {
        'generation': {'ok': True},
        'publish': {'ok': True},
        'ui_flow': {'passed': True},
        'system': {
            'coverage': {
                'scene_coverage_rate': 1.0,
                'conditional_edge_coverage_rate': 1.0,
                'terminal_edge_coverage_rate': 1.0,
                'untriggerable_conditional_edges': [],
            },
            'metrics': {
                'completion_rate': 1.0,
                'meaningful_accept_rate': 0.95,
                'llm_route_success_rate': 0.9,
                'step_error_rate': 0.0,
            },
        },
        'judge': {
            'successful': [
                {
                    'overall_score': 8.0,
                    'prompt_fidelity_score': 7.5,
                    'fun_score': 7.8,
                }
            ]
        },
    }
    passed, failures = _case_pass(case_result)
    assert passed is True
    assert failures == []


def test_case_pass_returns_failures_when_thresholds_miss() -> None:
    case_result = {
        'generation': {'ok': False},
        'publish': {'ok': False},
        'ui_flow': {'passed': False},
        'system': {
            'coverage': {
                'scene_coverage_rate': 0.3,
                'conditional_edge_coverage_rate': 0.5,
                'terminal_edge_coverage_rate': 0.5,
                'untriggerable_conditional_edges': ['edge-x'],
            },
            'metrics': {
                'completion_rate': 0.5,
                'meaningful_accept_rate': 0.4,
                'llm_route_success_rate': 0.5,
                'step_error_rate': 0.3,
            },
        },
        'judge': {'successful': []},
    }
    passed, failures = _case_pass(case_result)
    assert passed is False
    assert 'generation_failed' in failures
    assert 'publish_failed' in failures
    assert 'play_api_flow_failed' in failures
    assert 'judge_failed' in failures
