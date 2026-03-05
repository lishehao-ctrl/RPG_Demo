from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_OPENAPI_PATH = Path("contracts/openapi/backend.openapi.json")
DEFAULT_SDK_OUTPUT_PATH = Path("frontend/src/shared/api/generated/backend-sdk.ts")

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "trace")


def _read_openapi(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_operation_id(path: str, method: str) -> str:
    normalized_path = path.strip("/")
    if not normalized_path:
        normalized_path = "root"
    tokens: list[str] = []
    for token in normalized_path.replace("{", "").replace("}", "").split("/"):
        token = token.strip().replace("-", "_")
        if token:
            tokens.append(token)
    return "_".join([method.lower(), *tokens])


def _collect_operations(openapi: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for path in sorted((openapi.get("paths") or {}).keys()):
        path_item = (openapi.get("paths") or {}).get(path) or {}
        for method in _HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId") or _derive_operation_id(path, method))
            tags = [str(tag) for tag in (operation.get("tags") or [])]
            responses = sorted(str(code) for code in (operation.get("responses") or {}).keys())
            operations.append(
                {
                    "operationId": operation_id,
                    "method": method.upper(),
                    "path": path,
                    "tags": tags,
                    "hasRequestBody": "requestBody" in operation,
                    "hasParameters": bool(operation.get("parameters")),
                    "responseCodes": responses,
                }
            )
    return operations


def generate_sdk_source(*, openapi: dict[str, Any], openapi_source: str) -> str:
    canonical_openapi = json.dumps(openapi, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    openapi_sha256 = hashlib.sha256(canonical_openapi.encode("utf-8")).hexdigest()
    operations = _collect_operations(openapi)
    operation_map = {item["operationId"]: item for item in operations}

    operations_json = json.dumps(operations, ensure_ascii=False, indent=2)
    operation_map_json = json.dumps(operation_map, ensure_ascii=False, indent=2)
    return (
        "// AUTO-GENERATED FILE. DO NOT EDIT.\n"
        "// Source: scripts/generate_frontend_sdk.py\n"
        f"// OpenAPI source: {openapi_source}\n"
        f"// OpenAPI sha256: {openapi_sha256}\n\n"
        "export type ApiHttpMethod =\n"
        "  | 'GET'\n"
        "  | 'POST'\n"
        "  | 'PUT'\n"
        "  | 'PATCH'\n"
        "  | 'DELETE'\n"
        "  | 'OPTIONS'\n"
        "  | 'HEAD'\n"
        "  | 'TRACE';\n\n"
        "export type ApiOperationMeta = {\n"
        "  operationId: string;\n"
        "  method: ApiHttpMethod;\n"
        "  path: string;\n"
        "  tags: string[];\n"
        "  hasRequestBody: boolean;\n"
        "  hasParameters: boolean;\n"
        "  responseCodes: string[];\n"
        "};\n\n"
        "export const BACKEND_OPENAPI_SHA256 = "
        f"'{openapi_sha256}' as const;\n\n"
        "export const API_OPERATIONS: ApiOperationMeta[] = "
        f"{operations_json} as ApiOperationMeta[];\n\n"
        "export const API_OPERATION_MAP: Record<string, ApiOperationMeta> = "
        f"{operation_map_json} as Record<string, ApiOperationMeta>;\n\n"
        "export type ApiErrorEnvelope = {\n"
        "  error: {\n"
        "    code: string;\n"
        "    message: string;\n"
        "    retryable: boolean;\n"
        "    request_id: string | null;\n"
        "    details: Record<string, unknown>;\n"
        "  };\n"
        "};\n\n"
        "export function buildApiUrl(baseUrl: string, path: string): string {\n"
        "  return `${baseUrl.replace(/\\/$/, '')}${path}`;\n"
        "}\n"
    )


def generate_frontend_sdk(*, input_path: Path, output_path: Path, check: bool) -> int:
    if not input_path.exists():
        print(f"[generate-frontend-sdk] missing OpenAPI artifact: {input_path}")
        return 1

    openapi = _read_openapi(input_path)
    source = generate_sdk_source(openapi=openapi, openapi_source=str(input_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if check:
        if not output_path.exists():
            print(f"[generate-frontend-sdk] missing generated SDK: {output_path}")
            return 1
        existing = output_path.read_text(encoding="utf-8")
        if existing != source:
            print(f"[generate-frontend-sdk] out-of-sync SDK: {output_path}")
            return 1
        print(f"[generate-frontend-sdk] up-to-date: {output_path}")
        return 0

    output_path.write_text(source, encoding="utf-8")
    print(f"[generate-frontend-sdk] wrote: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate frontend TypeScript SDK metadata from OpenAPI artifact.")
    parser.add_argument("--input", default=str(DEFAULT_OPENAPI_PATH), help="input OpenAPI JSON artifact path")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_SDK_OUTPUT_PATH),
        help="output path for generated frontend SDK TypeScript file",
    )
    parser.add_argument("--check", action="store_true", help="validate generated output is up-to-date without writing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return generate_frontend_sdk(
        input_path=Path(args.input),
        output_path=Path(args.output),
        check=bool(args.check),
    )


if __name__ == "__main__":
    raise SystemExit(main())
