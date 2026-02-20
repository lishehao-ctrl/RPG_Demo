#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select, update

from app.db.models import Story
from app.db.session import SessionLocal
from app.modules.story.router import StoryPack
from app.modules.story.validation import validate_story_pack_structural

DEFAULT_STORY_FILE = Path("examples/storypacks/campus_week_v1.json")


def _load_pack_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"story file must contain a JSON object: {path}")
    return payload


def _validate_pack(payload: dict, *, source_path: Path) -> StoryPack:
    pack = StoryPack.model_validate(payload)
    errors = validate_story_pack_structural(pack)
    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"story pack structural validation failed for {source_path}: {joined}")
    return pack


def seed_story(*, story_file: Path, publish: bool) -> dict:
    if not story_file.exists():
        raise FileNotFoundError(f"story file not found: {story_file}")

    payload = _load_pack_json(story_file)
    pack = _validate_pack(payload, source_path=story_file)
    now = datetime.utcnow()

    with SessionLocal() as db:
        with db.begin():
            row = db.execute(
                select(Story).where(
                    Story.story_id == pack.story_id,
                    Story.version == pack.version,
                )
            ).scalar_one_or_none()

            if row is None:
                row = Story(
                    story_id=pack.story_id,
                    version=pack.version,
                    is_published=False,
                    pack_json=payload,
                    created_at=now,
                )
                db.add(row)
            else:
                row.pack_json = payload

            if publish:
                db.execute(
                    update(Story)
                    .where(Story.story_id == pack.story_id)
                    .values(is_published=False)
                )
                row.is_published = True

    return {
        "story_id": pack.story_id,
        "version": pack.version,
        "published": bool(publish),
        "source_path": str(story_file),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed or update a story pack into the database.")
    parser.add_argument(
        "--story-file",
        default=str(DEFAULT_STORY_FILE),
        help="Path to story pack JSON file.",
    )
    parser.add_argument(
        "--publish",
        dest="publish",
        action="store_true",
        help="Publish the seeded version (default).",
    )
    parser.add_argument(
        "--no-publish",
        dest="publish",
        action="store_false",
        help="Seed without publishing.",
    )
    parser.set_defaults(publish=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    story_file = Path(args.story_file)
    result = seed_story(story_file=story_file, publish=bool(args.publish))
    print(
        "seeded story "
        f"story_id={result['story_id']} version={result['version']} "
        f"published={result['published']} source={result['source_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
