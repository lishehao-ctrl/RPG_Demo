from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Literal

GENERATOR_VERSION = "v3.3"
PalettePolicy = Literal["random", "balanced", "fixed"]


def normalize_variant_seed(value: str | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized if normalized else None
    return str(value)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: Any) -> str:
    canonical = _canonical_json(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_pack_hash(pack_json: dict[str, Any]) -> str:
    return compute_payload_hash(pack_json)


def compute_transcript_digest(transcript: list[dict[str, Any]]) -> str:
    return compute_payload_hash(transcript)


def build_seed_material(
    *,
    seed_text: str,
    target_minutes: int,
    npc_count: int,
    style: str | None,
    variant_seed: str,
    generator_version: str,
    palette_policy: PalettePolicy,
) -> str:
    style_value = style or ""
    return (
        f"{seed_text}|{target_minutes}|{npc_count}|{style_value}|"
        f"{variant_seed}|{generator_version}|{palette_policy}"
    )


def derive_rng(seed_material: str) -> random.Random:
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    seed_int = int(digest, 16)
    return random.Random(seed_int)
