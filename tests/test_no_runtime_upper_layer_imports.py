from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_ROOT = _REPO_ROOT / "rpg_backend" / "runtime"
_ALLOWLIST = {"tests/test_no_runtime_upper_layer_imports.py"}
_FORBIDDEN_PREFIXES = (
    "from rpg_backend.api.",
    "import rpg_backend.api.",
    "from rpg_backend.application.",
    "import rpg_backend.application.",
    "from rpg_backend.infrastructure.",
    "import rpg_backend.infrastructure.",
    "from rpg_backend.storage.",
    "import rpg_backend.storage.",
)


def test_runtime_layer_does_not_depend_on_upper_or_adapter_layers() -> None:
    violations: list[str] = []
    for path in sorted(_RUNTIME_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWLIST:
            continue
        content = path.read_text(encoding="utf-8")
        if any(marker in content for marker in _FORBIDDEN_PREFIXES):
            violations.append(rel)
    assert not violations, "runtime layer import boundary violations:\n" + "\n".join(violations)
