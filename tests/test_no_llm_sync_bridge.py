from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = (
    "rpg_backend/runtime",
    "rpg_backend/application/session_step",
    "rpg_backend/observability/readiness.py",
)
_NEEDLE = "asyncio.to_thread"
_ALLOWLIST = {"tests/test_no_llm_sync_bridge.py"}


def _iter_paths() -> list[Path]:
    paths: list[Path] = []
    for root in _SCAN_ROOTS:
        candidate = _REPO_ROOT / root
        if not candidate.exists():
            continue
        if candidate.is_file():
            paths.append(candidate)
            continue
        paths.extend(sorted(candidate.rglob("*.py")))
    return paths


def test_no_llm_sync_to_thread_bridges() -> None:
    violations: list[str] = []
    for path in _iter_paths():
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative in _ALLOWLIST:
            continue
        content = path.read_text(encoding="utf-8")
        if _NEEDLE in content:
            violations.append(relative)

    assert not violations, (
        "LLM hot paths may not use asyncio.to_thread:\n" + "\n".join(violations)
    )
