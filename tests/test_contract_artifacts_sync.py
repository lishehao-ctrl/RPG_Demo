from __future__ import annotations

import json
from pathlib import Path

from scripts.export_openapi import canonical_openapi_json, generate_openapi_schema
from scripts.generate_frontend_sdk import generate_sdk_source


def test_backend_openapi_artifact_is_synced() -> None:
    artifact_path = Path(__file__).resolve().parents[1] / "contracts" / "openapi" / "backend.openapi.json"
    assert artifact_path.exists(), "missing backend OpenAPI artifact: contracts/openapi/backend.openapi.json"

    expected = canonical_openapi_json(generate_openapi_schema())
    actual = artifact_path.read_text(encoding="utf-8")
    assert (
        actual == expected
    ), "OpenAPI artifact is stale. Run `python -m scripts.export_openapi` and commit the result."


def test_frontend_generated_sdk_is_synced() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    openapi_path = repo_root / "contracts" / "openapi" / "backend.openapi.json"
    sdk_path = repo_root / "frontend" / "src" / "shared" / "api" / "generated" / "backend-sdk.ts"
    assert openapi_path.exists(), "missing OpenAPI artifact"
    assert sdk_path.exists(), "missing generated frontend SDK artifact"

    openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    expected = generate_sdk_source(openapi=openapi, openapi_source="contracts/openapi/backend.openapi.json")
    actual = sdk_path.read_text(encoding="utf-8")
    assert (
        actual == expected
    ), "Frontend SDK artifact is stale. Run `python -m scripts.generate_frontend_sdk` and commit the result."
