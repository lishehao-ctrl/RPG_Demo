#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.release.run_author_play_stability import _load_suite, run_suite

DEFAULT_OUTPUT_DIR = Path('reports/author_play_release')


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _run_browser_gate(*, frontend_dir: Path, suite_file: Path, base_url: str, output_path: Path, screenshots_dir: Path) -> dict[str, Any]:
    command = [
        'node',
        './scripts/author_play_release_gate.mjs',
        '--suite-file', str(suite_file.resolve()),
        '--base-url', base_url,
        '--output', str(output_path.resolve()),
        '--screenshots-dir', str(screenshots_dir.resolve()),
    ]
    completed = subprocess.run(command, cwd=frontend_dir, text=True, capture_output=True)
    if output_path.exists():
        report = json.loads(output_path.read_text(encoding='utf-8'))
    else:
        report = {
            'status': 'failed',
            'error': 'browser_report_missing',
            'stdout': completed.stdout,
            'stderr': completed.stderr,
        }
    report['process_exit_code'] = completed.returncode
    report['stdout'] = completed.stdout
    report['stderr'] = completed.stderr
    report['suite_file'] = str(suite_file.resolve())
    return report


def _combine_release_verdict(*, browser_report: dict[str, Any], system_report: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    browser_status = browser_report.get('status', 'failed')
    system_status = system_report.get('status', 'failed')
    if browser_status != 'passed':
        failures.append('browser_gate_failed')
    if system_status != 'passed':
        failures.append('system_gate_failed')
    verdict = 'passed' if not failures else ('partial' if browser_status == 'passed' or system_status == 'passed' else 'failed')
    return {
        'status': verdict,
        'failures': failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Run release gate with browser layer plus system layer.')
    parser.add_argument('--suite-file', default='eval_data/author_play_stability_suite_v1.json')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--ui-base-url', default='http://127.0.0.1:8173')
    parser.add_argument('--frontend-dir', default='frontend')
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument('--max-steps', type=int, default=20)
    parser.add_argument('--branch-hunter-max-runs', type=int, default=4)
    parser.add_argument('--skip-browser', action='store_true')
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suite_path = Path(args.suite_file)
    suite = _load_suite(suite_path)

    browser_report = {
        'status': 'skipped',
        'cases': [],
    }
    if not args.skip_browser:
        browser_report = _run_browser_gate(
            frontend_dir=Path(args.frontend_dir),
            suite_file=suite_path,
            base_url=args.ui_base_url,
            output_path=output_dir / 'browser_report.json',
            screenshots_dir=output_dir / 'screenshots',
        )

    system_report = run_suite(
        suite=suite,
        base_url=args.base_url.rstrip('/'),
        output_dir=output_dir / 'system',
        max_steps=max(1, args.max_steps),
        branch_hunter_max_runs=max(1, args.branch_hunter_max_runs),
    )
    verdict = _combine_release_verdict(browser_report=browser_report, system_report=system_report)

    summary = {
        'generated_at': datetime.now(UTC).isoformat(),
        'suite': suite.model_dump(),
        'browser': browser_report,
        'system': system_report,
        'release_verdict': verdict,
    }
    summary_path = output_dir / 'summary.json'
    _write_json(summary_path, summary)
    print(summary_path)
    return 0 if verdict['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
