from __future__ import annotations

from pathlib import Path

from tools.play_benchmarks import switch_runtime_profile


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_build_managed_env_map_auto_appends_v1_and_builds_key_pool(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.toml"
    env_path = tmp_path / ".env"
    _write_text(
        profiles_path,
        """
[profiles.beecode]
description = "beecode"

[profiles.beecode.default]
base_url = "https://beecode.cc/"
model = "gpt-5.4-mini"
keys = ["${APP_PROFILE_BEECODE_KEY_1}", "${APP_PROFILE_BEECODE_KEY_2}"]
""".strip()
        + "\n",
    )
    _write_text(
        env_path,
        """
APP_PROFILE_BEECODE_KEY_1=key-a
APP_PROFILE_BEECODE_KEY_2=key-b
""".strip()
        + "\n",
    )
    profile_defs = switch_runtime_profile.load_profile_definitions(profiles_path)
    profile = switch_runtime_profile.resolve_profile(
        name="beecode",
        payload=profile_defs["beecode"],
        env_values=switch_runtime_profile._load_env_values(env_path),
    )

    env_map = switch_runtime_profile._build_managed_env_map(profile, auto_append_v1=True, rpm=200)

    assert env_map["APP_RESPONSES_AUTHOR_BASE_URL"] == "https://beecode.cc/v1"
    assert env_map["APP_RESPONSES_PLAY_BASE_URL"] == "https://beecode.cc/v1"
    assert env_map["APP_HELPER_SLOT_2_BASE_URL"] == "https://beecode.cc/v1"
    assert env_map["APP_HELPER_RESPONSES_API_KEYS"] == "key-a,key-b"
    assert env_map["APP_RESPONSES_AUTHOR_REQUESTS_PER_MINUTE"] == "200"
    assert env_map["APP_RESPONSES_PLAY_REQUESTS_PER_MINUTE"] == "200"
    assert env_map["APP_HELPER_RESPONSES_REQUESTS_PER_MINUTE"] == "200"


def test_main_dry_run_does_not_modify_env_file(tmp_path: Path) -> None:
    profiles_path = tmp_path / "profiles.toml"
    env_path = tmp_path / ".env"
    _write_text(
        profiles_path,
        """
[profiles.beecode]
description = "beecode"

[profiles.beecode.default]
base_url = "https://beecode.cc/"
model = "gpt-5.4-mini"
keys = ["${APP_PROFILE_BEECODE_KEY_1}", "${APP_PROFILE_BEECODE_KEY_2}"]
""".strip()
        + "\n",
    )
    original_env = """
APP_PROFILE_BEECODE_KEY_1=key-a
APP_PROFILE_BEECODE_KEY_2=key-b
APP_SOME_OTHER_VALUE=keep-me
""".strip() + "\n"
    _write_text(env_path, original_env)

    exit_code = switch_runtime_profile.main(
        [
            "--profile",
            "beecode",
            "--profiles-file",
            str(profiles_path),
            "--env-file",
            str(env_path),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert env_path.read_text(encoding="utf-8") == original_env
