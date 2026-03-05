from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rpg_backend.main import app

DEFAULT_OUTPUT_PATH = Path("contracts/openapi/backend.openapi.json")


def generate_openapi_schema() -> dict[str, Any]:
    return app.openapi()


def canonical_openapi_json(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export_openapi(*, output_path: Path, check: bool) -> int:
    schema = generate_openapi_schema()
    content = canonical_openapi_json(schema)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if check:
        if not output_path.exists():
            print(f"[export-openapi] missing artifact: {output_path}")
            return 1
        existing = output_path.read_text(encoding="utf-8")
        if existing != content:
            print(f"[export-openapi] out-of-sync artifact: {output_path}")
            return 1
        print(f"[export-openapi] up-to-date: {output_path}")
        return 0

    output_path.write_text(content, encoding="utf-8")
    print(f"[export-openapi] wrote: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export FastAPI OpenAPI artifact for frontend SDK generation.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="output path for OpenAPI JSON artifact")
    parser.add_argument("--check", action="store_true", help="validate artifact is up-to-date without writing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return export_openapi(output_path=Path(args.output), check=bool(args.check))


if __name__ == "__main__":
    raise SystemExit(main())
