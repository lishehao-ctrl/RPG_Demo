from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_APPLICATION_ROOT = _REPO_ROOT / "rpg_backend" / "application"
_ALLOWLIST = {"tests/test_no_application_api_or_storage_imports.py"}
_FORBIDDEN_PREFIXES = (
    "from rpg_backend.api.",
    "import rpg_backend.api.",
    "from rpg_backend.storage.models",
    "import rpg_backend.storage.models",
)


def test_application_layer_does_not_depend_on_api_or_orm_models() -> None:
    violations: list[str] = []
    for path in sorted(_APPLICATION_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWLIST:
            continue
        content = path.read_text(encoding="utf-8")
        if any(marker in content for marker in _FORBIDDEN_PREFIXES):
            violations.append(rel)
    assert not violations, "application layer import boundary violations:\n" + "\n".join(violations)
