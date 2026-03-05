from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = ("rpg_backend", "tests", "scripts")
_FORBIDDEN_IMPORTS = (
    "from rpg_backend.runtime.session_step.",
    "from rpg_backend.runtime.session_step import",
    "import rpg_backend.runtime.session_step",
)
_ALLOWLIST = {"tests/test_no_runtime_session_step_facade_imports.py"}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        base = _REPO_ROOT / root
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def test_no_runtime_session_step_facade_imports() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative in _ALLOWLIST:
            continue
        content = path.read_text(encoding="utf-8")
        if any(needle in content for needle in _FORBIDDEN_IMPORTS):
            violations.append(relative)

    assert not violations, (
        "runtime.session_step imports are forbidden:\n"
        + "\n".join(violations)
    )
