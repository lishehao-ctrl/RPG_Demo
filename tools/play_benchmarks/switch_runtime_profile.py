from __future__ import annotations

import argparse
import difflib
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_PATH = Path(__file__).with_name("provider_profiles.toml")
DEFAULT_ENV_PATH = REPO_ROOT / ".env"
MANAGED_BLOCK_START = "# >>> RUNTIME_PROFILE_MANAGED >>>"
MANAGED_BLOCK_END = "# <<< RUNTIME_PROFILE_MANAGED <<<"


@dataclass(frozen=True)
class ProfileTarget:
    base_url: str
    model: str
    keys: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    description: str
    default: ProfileTarget
    author: ProfileTarget
    play: ProfileTarget
    helper: ProfileTarget


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Switch runtime provider profile by writing a managed .env block.")
    parser.add_argument("--profile")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--profiles-file", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--rpm", type=int, default=200)
    parser.add_argument("--no-auto-append-v1", action="store_true")
    return parser.parse_args(argv)


def _strip_wrapping_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _parse_env_text(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        candidate_key = key.strip()
        if not candidate_key:
            continue
        parsed[candidate_key] = _strip_wrapping_quotes(value)
    return parsed


def _load_env_values(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    return _parse_env_text(env_path.read_text(encoding="utf-8"))


def _resolve_token(value: str, env_values: dict[str, str]) -> str:
    stripped = str(value or "").strip()
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", stripped)
    if not match:
        return stripped
    variable = match.group(1)
    resolved = os.environ.get(variable)
    if resolved is None:
        resolved = env_values.get(variable)
    if resolved is None or not str(resolved).strip():
        raise RuntimeError(f"missing value for token {stripped}; set {variable} in env or .env first")
    return str(resolved).strip()


def _normalize_base_url(base_url: str, *, auto_append_v1: bool) -> str:
    normalized = str(base_url or "").strip()
    if not normalized:
        raise RuntimeError("base_url is required")
    if not auto_append_v1:
        return normalized.rstrip("/")
    split = urlsplit(normalized)
    if split.scheme and split.netloc:
        path = (split.path or "").rstrip("/")
        if not path:
            path = "/v1"
        elif not path.casefold().endswith("/v1"):
            path = f"{path}/v1"
        return urlunsplit((split.scheme, split.netloc, path, split.query, split.fragment))
    trimmed = normalized.rstrip("/")
    return trimmed if trimmed.casefold().endswith("/v1") else f"{trimmed}/v1"


def _parse_keys(raw_keys: Any, env_values: dict[str, str]) -> tuple[str, ...]:
    if not isinstance(raw_keys, list):
        raise RuntimeError("profile keys must be a list")
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_keys:
        resolved = _resolve_token(str(item or ""), env_values)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        values.append(resolved)
    if not values:
        raise RuntimeError("profile key list resolved to empty")
    return tuple(values)


def _build_target(raw: dict[str, Any] | None, *, env_values: dict[str, str], fallback: ProfileTarget | None) -> ProfileTarget:
    payload = raw or {}
    if fallback is None:
        base_url = _resolve_token(str(payload.get("base_url") or ""), env_values)
        model = _resolve_token(str(payload.get("model") or ""), env_values)
        keys = _parse_keys(payload.get("keys"), env_values)
        if not base_url or not model:
            raise RuntimeError("default profile target requires base_url/model/keys")
        return ProfileTarget(base_url=base_url, model=model, keys=keys)
    base_url = _resolve_token(str(payload.get("base_url") or fallback.base_url), env_values)
    model = _resolve_token(str(payload.get("model") or fallback.model), env_values)
    keys = _parse_keys(payload.get("keys"), env_values) if "keys" in payload else fallback.keys
    return ProfileTarget(base_url=base_url, model=model, keys=keys)


def load_profile_definitions(path: Path) -> dict[str, dict[str, Any]]:
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    profiles = parsed.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeError("profiles file must define [profiles.<name>] tables")
    normalized: dict[str, dict[str, Any]] = {}
    for name, payload in profiles.items():
        if not isinstance(payload, dict):
            raise RuntimeError(f"profile {name} must be a table")
        normalized[name] = payload
    return normalized


def resolve_profile(*, name: str, payload: dict[str, Any], env_values: dict[str, str]) -> RuntimeProfile:
    description = str(payload.get("description") or "").strip()
    default_target = _build_target(payload.get("default"), env_values=env_values, fallback=None)
    author_target = _build_target(payload.get("author"), env_values=env_values, fallback=default_target)
    play_target = _build_target(payload.get("play"), env_values=env_values, fallback=default_target)
    helper_target = _build_target(payload.get("helper"), env_values=env_values, fallback=default_target)
    return RuntimeProfile(
        name=name,
        description=description,
        default=default_target,
        author=author_target,
        play=play_target,
        helper=helper_target,
    )


def _csv(values: tuple[str, ...]) -> str:
    return ",".join(values)


def _mask_key(key: str) -> str:
    stripped = str(key or "").strip()
    if len(stripped) <= 10:
        return "***"
    return f"{stripped[:6]}...{stripped[-4:]}"


def _build_managed_env_map(profile: RuntimeProfile, *, auto_append_v1: bool, rpm: int) -> dict[str, str]:
    author_base = _normalize_base_url(profile.author.base_url, auto_append_v1=auto_append_v1)
    play_base = _normalize_base_url(profile.play.base_url, auto_append_v1=auto_append_v1)
    helper_base = _normalize_base_url(profile.helper.base_url, auto_append_v1=auto_append_v1)
    default_base = _normalize_base_url(profile.default.base_url, auto_append_v1=auto_append_v1)
    if rpm < 1:
        raise RuntimeError("rpm must be >= 1")
    return {
        "APP_RUNTIME_PROFILE": profile.name,
        "APP_RESPONSES_BASE_URL": default_base,
        "APP_RESPONSES_API_KEY": profile.default.keys[0],
        "APP_RESPONSES_API_KEYS": _csv(profile.default.keys),
        "APP_RESPONSES_MODEL": profile.default.model,
        "APP_RESPONSES_AUTHOR_BASE_URL": author_base,
        "APP_RESPONSES_AUTHOR_API_KEY": profile.author.keys[0],
        "APP_RESPONSES_AUTHOR_API_KEYS": _csv(profile.author.keys),
        "APP_RESPONSES_AUTHOR_MODEL": profile.author.model,
        "APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE": str(int(rpm)),
        "APP_RESPONSES_PLAY_BASE_URL": play_base,
        "APP_RESPONSES_PLAY_API_KEY": profile.play.keys[0],
        "APP_RESPONSES_PLAY_API_KEYS": _csv(profile.play.keys),
        "APP_RESPONSES_PLAY_MODEL": profile.play.model,
        "APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE": str(int(rpm)),
        "APP_HELPER_SLOT_1_BASE_URL": "",
        "APP_HELPER_SLOT_1_API_KEY": "",
        "APP_HELPER_SLOT_1_MODEL": "",
        "APP_HELPER_SLOT_1_USE_SESSION_CACHE": "false",
        "APP_HELPER_SLOT_1_WEIGHT": "1.0",
        "APP_HELPER_SLOT_1_ROLE": "backup",
        "APP_HELPER_SLOT_2_BASE_URL": helper_base,
        "APP_HELPER_SLOT_2_API_KEY": profile.helper.keys[0],
        "APP_HELPER_SLOT_2_MODEL": profile.helper.model,
        "APP_HELPER_SLOT_2_USE_SESSION_CACHE": "false",
        "APP_HELPER_SLOT_2_WEIGHT": "1.0",
        "APP_HELPER_SLOT_2_ROLE": "primary",
        "APP_HELPER_SLOT_3_BASE_URL": "",
        "APP_HELPER_SLOT_3_API_KEY": "",
        "APP_HELPER_SLOT_3_MODEL": "",
        "APP_HELPER_SLOT_3_USE_SESSION_CACHE": "false",
        "APP_HELPER_SLOT_3_WEIGHT": "1.0",
        "APP_HELPER_SLOT_3_ROLE": "backup",
        "APP_HELPER_RESPONSES_BASE_URL": helper_base,
        "APP_HELPER_RESPONSES_API_KEY": profile.helper.keys[0],
        "APP_HELPER_RESPONSES_MODEL": profile.helper.model,
        "APP_HELPER_RESPONSES_API_KEYS": _csv(profile.helper.keys),
        "APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE": str(int(rpm)),
        "APP_HELPER_RESPONSES_ENABLE_WEB_SEARCH": "false",
    }


def _render_managed_block(env_map: dict[str, str]) -> str:
    ordered_keys = [
        "APP_RUNTIME_PROFILE",
        "APP_RESPONSES_BASE_URL",
        "APP_RESPONSES_API_KEY",
        "APP_RESPONSES_API_KEYS",
        "APP_RESPONSES_MODEL",
        "APP_RESPONSES_AUTHOR_BASE_URL",
        "APP_RESPONSES_AUTHOR_API_KEY",
        "APP_RESPONSES_AUTHOR_API_KEYS",
        "APP_RESPONSES_AUTHOR_MODEL",
        "APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE",
        "APP_RESPONSES_PLAY_BASE_URL",
        "APP_RESPONSES_PLAY_API_KEY",
        "APP_RESPONSES_PLAY_API_KEYS",
        "APP_RESPONSES_PLAY_MODEL",
        "APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE",
        "APP_HELPER_SLOT_1_BASE_URL",
        "APP_HELPER_SLOT_1_API_KEY",
        "APP_HELPER_SLOT_1_MODEL",
        "APP_HELPER_SLOT_1_USE_SESSION_CACHE",
        "APP_HELPER_SLOT_1_WEIGHT",
        "APP_HELPER_SLOT_1_ROLE",
        "APP_HELPER_SLOT_2_BASE_URL",
        "APP_HELPER_SLOT_2_API_KEY",
        "APP_HELPER_SLOT_2_MODEL",
        "APP_HELPER_SLOT_2_USE_SESSION_CACHE",
        "APP_HELPER_SLOT_2_WEIGHT",
        "APP_HELPER_SLOT_2_ROLE",
        "APP_HELPER_SLOT_3_BASE_URL",
        "APP_HELPER_SLOT_3_API_KEY",
        "APP_HELPER_SLOT_3_MODEL",
        "APP_HELPER_SLOT_3_USE_SESSION_CACHE",
        "APP_HELPER_SLOT_3_WEIGHT",
        "APP_HELPER_SLOT_3_ROLE",
        "APP_HELPER_RESPONSES_BASE_URL",
        "APP_HELPER_RESPONSES_API_KEY",
        "APP_HELPER_RESPONSES_MODEL",
        "APP_HELPER_RESPONSES_API_KEYS",
        "APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE",
        "APP_HELPER_RESPONSES_ENABLE_WEB_SEARCH",
    ]
    lines = [
        MANAGED_BLOCK_START,
        "# Auto-generated by tools/play_benchmarks/switch_runtime_profile.py",
    ]
    for key in ordered_keys:
        value = env_map.get(key, "")
        lines.append(f"{key}={value}")
    lines.append(MANAGED_BLOCK_END)
    return "\n".join(lines)


def _replace_managed_block(original: str, block: str) -> str:
    pattern = re.compile(
        rf"{re.escape(MANAGED_BLOCK_START)}.*?{re.escape(MANAGED_BLOCK_END)}\n?",
        flags=re.DOTALL,
    )
    candidate = block.rstrip("\n") + "\n"
    if pattern.search(original):
        return pattern.sub(candidate, original)
    if original and not original.endswith("\n"):
        return original + "\n\n" + candidate
    if original:
        return original + "\n" + candidate
    return candidate


def _render_diff(before: str, after: str, *, env_path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{env_path} (before)",
            tofile=f"{env_path} (after)",
        )
    )


def _print_profile_summary(profile: RuntimeProfile, env_map: dict[str, str], *, auto_append_v1: bool, rpm: int) -> None:
    materialized = _build_managed_env_map(profile, auto_append_v1=auto_append_v1, rpm=rpm)
    print(f"profile={profile.name}")
    if profile.description:
        print(f"description={profile.description}")
    print(f"runtime_profile={materialized['APP_RUNTIME_PROFILE']}")
    for channel in ("author", "play", "helper"):
        base = materialized[f"APP_RESPONSES_{channel.upper()}_BASE_URL"] if channel != "helper" else materialized["APP_HELPER_SLOT_2_BASE_URL"]
        model = materialized[f"APP_RESPONSES_{channel.upper()}_MODEL"] if channel != "helper" else materialized["APP_HELPER_SLOT_2_MODEL"]
        keys_raw = (
            materialized[f"APP_RESPONSES_{channel.upper()}_API_KEYS"]
            if channel != "helper"
            else materialized["APP_HELPER_RESPONSES_API_KEYS"]
        )
        keys = tuple(token for token in keys_raw.split(",") if token)
        print(f"{channel}: base_url={base} model={model} key_count={len(keys)} keys={[ _mask_key(item) for item in keys ]}")
    print(f"author_rpm={materialized['APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE']}")
    print(f"play_rpm={materialized['APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE']}")
    print(f"helper_rpm={materialized['APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE']}")
    _ = env_map


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    profiles_path = Path(args.profiles_file).expanduser().resolve()
    env_path = Path(args.env_file).expanduser().resolve()
    env_values = _load_env_values(env_path)
    profile_defs = load_profile_definitions(profiles_path)

    if args.list:
        for name in sorted(profile_defs):
            description = str(profile_defs[name].get("description") or "").strip()
            suffix = f" - {description}" if description else ""
            print(f"{name}{suffix}")
        return 0

    if not args.profile:
        raise RuntimeError("--profile is required unless --list is used")
    if args.profile not in profile_defs:
        raise RuntimeError(f"unknown profile: {args.profile}")

    selected = resolve_profile(name=args.profile, payload=profile_defs[args.profile], env_values=env_values)
    auto_append_v1 = not bool(args.no_auto_append_v1)
    env_map = _build_managed_env_map(selected, auto_append_v1=auto_append_v1, rpm=int(args.rpm))
    if args.show:
        _print_profile_summary(selected, env_map, auto_append_v1=auto_append_v1, rpm=int(args.rpm))
        if not args.dry_run:
            return 0

    block = _render_managed_block(env_map)
    before = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    after = _replace_managed_block(before, block)
    diff = _render_diff(before, after, env_path=env_path)
    if args.dry_run:
        print(diff or "(no changes)")
        return 0

    env_path.write_text(after, encoding="utf-8")
    if diff:
        print(diff)
    print(f"updated {env_path} with runtime profile '{selected.name}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
