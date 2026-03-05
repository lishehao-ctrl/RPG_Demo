from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = ("rpg_backend", "tests", "scripts")
_FORBIDDEN_NEEDLES = (
    "from rpg_backend.llm.http_pool import",
    "import rpg_backend.llm.http_pool",
    "get_shared_sync_client",
    "reset_http_pool",
)
_ALLOWLIST = {"tests/test_no_sync_llm_http_pool.py"}
_REMOVED_FILE = "rpg_backend/llm/http_pool.py"


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        base = _REPO_ROOT / root
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def test_sync_llm_http_pool_file_removed() -> None:
    assert not (_REPO_ROOT / _REMOVED_FILE).exists(), "sync llm http_pool.py must not exist"


def test_no_sync_llm_http_pool_imports() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative in _ALLOWLIST:
            continue
        content = path.read_text(encoding="utf-8")
        if any(needle in content for needle in _FORBIDDEN_NEEDLES):
            violations.append(relative)

    assert not violations, "sync llm http pool symbols are forbidden:\n" + "\n".join(violations)
