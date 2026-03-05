from __future__ import annotations

from pathlib import Path


def test_no_legacy_v2_route_constants_in_prod_route_paths() -> None:
    route_paths = (
        Path(__file__).resolve().parents[1]
        / "rpg_backend"
        / "api"
        / "route_paths.py"
    )
    content = route_paths.read_text(encoding="utf-8")
    assert "LEGACY_V2_" not in content, "production route_paths.py must not define LEGACY_V2_* constants"
