from __future__ import annotations

from pathlib import Path


def test_no_readiness_compat_helpers() -> None:
    readiness_file = (
        Path(__file__).resolve().parents[1]
        / "rpg_backend"
        / "observability"
        / "readiness.py"
    )
    content = readiness_file.read_text(encoding="utf-8")
    forbidden = (
        "_await_if_needed",
        "_resolve_check_result",
        "run_readiness_checks(",
        "asyncio.run(",
    )
    violations = [needle for needle in forbidden if needle in content]
    assert not violations, "readiness compat helpers are forbidden: " + ", ".join(violations)
