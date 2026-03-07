from __future__ import annotations

from scripts.release.run_author_play_release_gate import _combine_release_verdict


def test_release_verdict_passes_when_browser_and_system_pass() -> None:
    verdict = _combine_release_verdict(
        browser_report={'status': 'passed'},
        system_report={'status': 'passed'},
    )
    assert verdict['status'] == 'passed'
    assert verdict['failures'] == []


def test_release_verdict_partial_when_only_one_layer_passes() -> None:
    verdict = _combine_release_verdict(
        browser_report={'status': 'passed'},
        system_report={'status': 'failed'},
    )
    assert verdict['status'] == 'partial'
    assert 'system_gate_failed' in verdict['failures']


def test_release_verdict_failed_when_both_layers_fail() -> None:
    verdict = _combine_release_verdict(
        browser_report={'status': 'failed'},
        system_report={'status': 'failed'},
    )
    assert verdict['status'] == 'failed'
    assert 'browser_gate_failed' in verdict['failures']
    assert 'system_gate_failed' in verdict['failures']
