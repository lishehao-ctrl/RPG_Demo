from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPOSITORIES_ROOT = _REPO_ROOT / "rpg_backend" / "infrastructure" / "repositories"
_ALLOWLIST = {"tests/test_no_repository_transaction_ownership.py"}
_FORBIDDEN = ("await db.commit(", "await db.rollback(")


def test_repositories_do_not_own_transaction_commit_or_rollback() -> None:
    violations: list[str] = []
    for path in sorted(_REPOSITORIES_ROOT.glob("*_async.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWLIST:
            continue
        content = path.read_text(encoding="utf-8")
        if any(marker in content for marker in _FORBIDDEN):
            violations.append(rel)
    assert not violations, "repository transaction ownership violations:\n" + "\n".join(violations)
