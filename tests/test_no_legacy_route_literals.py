from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = (_REPO_ROOT / "tests", _REPO_ROOT / "scripts")

_ALLOW_V2_LITERAL = {
    "tests/api/test_api_v2_cutover.py",
    "tests/llm/test_worker_route_cutover.py",
}
_ALLOW_WORKER_INTERNAL_LITERAL: set[str] = set()
_ALLOW_V1_TASKS_LITERAL: set[str] = set()
_ALLOW_LEGACY_LITERAL: set[str] = set()
_ALLOW_LEGACY_V2_LITERAL = {
    "tests/api/test_api_v2_cutover.py",
    "tests/llm/test_worker_route_cutover.py",
}

_RE_V2_LITERAL = re.compile(r"/v2/")
_RE_V1_TASKS_LITERAL = re.compile(r"/v1/tasks/")
_RE_WORKER_INTERNAL_LITERAL = re.compile(r"/internal/llm/tasks")
_RE_LEGACY_STORIES = re.compile(r"(?<!/v2)/stories(?:/|\\b)")
_RE_LEGACY_SESSIONS = re.compile(r"(?<!/v2)/sessions(?:/|\\b)")
_RE_LEGACY_ADMIN = re.compile(r"(?<!/v2)/admin(?:/|\\b)")


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        files.extend(sorted(root.rglob("*.py")))
    return files


def test_no_legacy_route_literals_in_tests_and_scripts() -> None:
    violations: list[str] = []
    for path in _iter_scan_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel == "tests/test_no_legacy_route_literals.py":
            continue
        content = path.read_text(encoding="utf-8")

        if rel not in _ALLOW_V2_LITERAL and _RE_V2_LITERAL.search(content):
            violations.append(f"{rel}: contains hardcoded /v2/ literal")
        if rel not in _ALLOW_WORKER_INTERNAL_LITERAL and _RE_WORKER_INTERNAL_LITERAL.search(content):
            violations.append(f"{rel}: contains hardcoded /internal/llm/tasks literal")
        if rel not in _ALLOW_V1_TASKS_LITERAL and _RE_V1_TASKS_LITERAL.search(content):
            violations.append(f"{rel}: contains legacy /v1/tasks/ literal")
        if rel not in _ALLOW_LEGACY_LITERAL and rel not in _ALLOW_LEGACY_V2_LITERAL and _RE_LEGACY_STORIES.search(content):
            violations.append(f"{rel}: contains legacy /stories literal")
        if rel not in _ALLOW_LEGACY_LITERAL and rel not in _ALLOW_LEGACY_V2_LITERAL and _RE_LEGACY_SESSIONS.search(content):
            violations.append(f"{rel}: contains legacy /sessions literal")
        if rel not in _ALLOW_LEGACY_LITERAL and rel not in _ALLOW_LEGACY_V2_LITERAL and _RE_LEGACY_ADMIN.search(content):
            violations.append(f"{rel}: contains legacy /admin literal")

    assert not violations, "route literal policy violations:\n" + "\n".join(sorted(violations))
