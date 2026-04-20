from __future__ import annotations

from pydantic import ValidationError

import rpg_backend.author.gateway as author_gateway_module
import rpg_backend.play.gateway as play_gateway_module
from rpg_backend.config import Settings
from tools.play_benchmarks import live_api_playtest


def _settings_from_env(monkeypatch, values: dict[str, str]) -> Settings:
    for key in list(values):
        monkeypatch.setenv(key, values[key])
    return Settings(_env_file=None)


def test_legacy_gateway_envs_populate_resolved_responses(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_GATEWAY_BASE_URL": "https://legacy.example/v1",
            "APP_GATEWAY_API_KEY": "legacy-key",
            "APP_GATEWAY_MODEL": "legacy-model",
        },
    )

    assert settings.resolved_responses_base_url() == "https://legacy.example/v1"
    assert settings.resolved_responses_api_key() == "legacy-key"
    assert settings.resolved_responses_model() == "legacy-model"
    assert settings.resolved_author_responses_base_url() == "https://legacy.example/v1"
    assert settings.resolved_author_responses_api_key() == "legacy-key"
    assert settings.resolved_author_responses_model() == "legacy-model"
    assert settings.resolved_play_responses_base_url() == "https://legacy.example/v1"
    assert settings.resolved_play_responses_api_key() == "legacy-key"
    assert settings.resolved_play_responses_model() == "legacy-model"


def test_play_v2_intent_and_micro_sim_defaults_are_enabled(monkeypatch) -> None:
    settings = _settings_from_env(monkeypatch, {})

    assert settings.play_v2_narration_profile == "npc_texture_v2"
    assert settings.play_v2_intent_compiler_use_llm is True
    assert settings.play_v2_micro_sim_use_llm is True
    assert settings.play_v2_micro_sim_max_candidates == 5


def test_non_v2_narration_profile_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("APP_PLAY_V2_NARRATION_PROFILE", "baseline")
    try:
        Settings(_env_file=None)
    except ValidationError as exc:
        assert "play_v2_narration_profile" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected invalid narration profile to fail")


def test_responses_envs_override_legacy_and_play_model_override_is_honored(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_GATEWAY_BASE_URL": "https://legacy.example/v1",
            "APP_GATEWAY_API_KEY": "legacy-key",
            "APP_GATEWAY_MODEL": "legacy-model",
            "APP_GATEWAY_PLAY_MODEL": "legacy-play-model",
            "APP_RESPONSES_BASE_URL": "https://responses.example/v1",
            "APP_RESPONSES_API_KEY": "responses-key",
            "APP_RESPONSES_MODEL": "responses-model",
            "APP_RESPONSES_PLAY_MODEL": "responses-play-model",
        },
    )

    assert settings.resolved_responses_base_url() == "https://responses.example/v1"
    assert settings.resolved_responses_api_key() == "responses-key"
    assert settings.resolved_responses_model() == "responses-model"
    assert settings.resolved_responses_model_for_text_capability("play.render") == "responses-play-model"
    assert settings.resolved_responses_model_for_text_capability("author.story_frame_scaffold") == "responses-model"
    assert settings.resolved_author_responses_model() == "responses-model"
    assert settings.resolved_play_responses_model() == "responses-play-model"


def test_author_and_play_specific_envs_override_generic_responses(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_BASE_URL": "https://generic.example/v1",
            "APP_RESPONSES_API_KEY": "generic-key",
            "APP_RESPONSES_MODEL": "generic-model",
            "APP_RESPONSES_AUTHOR_BASE_URL": "https://author.example/v1",
            "APP_RESPONSES_AUTHOR_API_KEY": "author-key",
            "APP_RESPONSES_AUTHOR_MODEL": "author-model",
            "APP_RESPONSES_PLAY_BASE_URL": "https://play.example/v1",
            "APP_RESPONSES_PLAY_API_KEY": "play-key",
            "APP_RESPONSES_PLAY_MODEL": "play-model",
        },
    )

    assert settings.resolved_author_responses_base_url() == "https://author.example/v1"
    assert settings.resolved_author_responses_api_key() == "author-key"
    assert settings.resolved_author_responses_model() == "author-model"
    assert settings.resolved_play_responses_base_url() == "https://play.example/v1"
    assert settings.resolved_play_responses_api_key() == "play-key"
    assert settings.resolved_play_responses_model() == "play-model"


def test_helper_responses_falls_back_to_legacy_helper_gateway_envs(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_HELPER_GATEWAY_BASE_URL": "https://helper-legacy.example/v1",
            "APP_HELPER_GATEWAY_API_KEY": "helper-legacy-key",
            "APP_HELPER_GATEWAY_MODEL": "helper-legacy-model",
        },
    )

    assert settings.resolved_helper_responses_base_url() == "https://helper-legacy.example/v1"
    assert settings.resolved_helper_responses_api_key() == "helper-legacy-key"
    assert settings.resolved_helper_responses_model() == "helper-legacy-model"


def test_helper_slots_override_legacy_helper_and_preserve_order(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_HELPER_GATEWAY_BASE_URL": "https://helper-legacy.example/v1",
            "APP_HELPER_GATEWAY_API_KEY": "helper-legacy-key",
            "APP_HELPER_GATEWAY_MODEL": "gpt-5.4-mini",
            "APP_HELPER_SLOT_1_BASE_URL": "https://helper-1.example/v1",
            "APP_HELPER_SLOT_1_API_KEY": "helper-1-key",
            "APP_HELPER_SLOT_1_MODEL": "gpt-5.4-mini",
            "APP_HELPER_SLOT_1_WEIGHT": "2.0",
            "APP_HELPER_SLOT_1_ROLE": "backup",
            "APP_HELPER_SLOT_2_BASE_URL": "https://helper-2.example/v1",
            "APP_HELPER_SLOT_2_API_KEY": "helper-2-key",
            "APP_HELPER_SLOT_2_MODEL": "gpt-5.4-mini",
            "APP_HELPER_SLOT_2_ROLE": "primary",
        },
    )

    endpoints = settings.configured_helper_responses_endpoints()

    assert [endpoint.slot_name for endpoint in endpoints] == ["helper_slot_2", "helper_slot_1"]
    assert endpoints[0].role == "primary"
    assert endpoints[1].role == "backup"
    assert endpoints[0].weight == 1.0
    assert endpoints[1].weight == 2.0
    assert settings.resolved_helper_responses_base_url() == "https://helper-2.example/v1"
    assert settings.resolved_helper_responses_api_key() == "helper-2-key"
    assert settings.resolved_helper_responses_model() == "gpt-5.4-mini"


def test_helper_api_key_pool_supports_csv_and_dedup(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_HELPER_SLOT_2_BASE_URL": "https://helper-2.example/v1",
            "APP_HELPER_SLOT_2_API_KEY": "helper-2-key",
            "APP_HELPER_SLOT_2_MODEL": "gpt-5.4-mini",
            "APP_HELPER_SLOT_2_ROLE": "primary",
            "APP_HELPER_RESPONSES_API_KEYS": " key-a, key-b ; key-a\nkey-c ",
        },
    )

    assert settings.helper_responses_api_key_pool() == ("key-a", "key-b", "key-c")


def test_responses_api_key_pool_supports_csv_and_dedup(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_BASE_URL": "https://responses.example/v1",
            "APP_RESPONSES_API_KEY": "responses-key-default",
            "APP_RESPONSES_MODEL": "gpt-5.4-mini",
            "APP_RESPONSES_API_KEYS": " key-a, key-b ; key-a\nkey-c ",
        },
    )

    assert settings.responses_api_key_pool() == ("key-a", "key-b", "key-c")


def test_author_api_key_pool_falls_back_to_author_then_generic(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_BASE_URL": "https://responses.example/v1",
            "APP_RESPONSES_API_KEY": "generic-key",
            "APP_RESPONSES_MODEL": "gpt-5.4-mini",
            "APP_RESPONSES_AUTHOR_BASE_URL": "https://author.example/v1",
            "APP_RESPONSES_AUTHOR_API_KEY": "author-key",
            "APP_RESPONSES_AUTHOR_MODEL": "gpt-5.4-mini",
        },
    )

    assert settings.author_responses_api_key_pool() == ("author-key", "generic-key")


def test_helper_api_key_pool_falls_back_to_primary_key(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_HELPER_SLOT_2_BASE_URL": "https://helper-2.example/v1",
            "APP_HELPER_SLOT_2_API_KEY": "helper-2-key",
            "APP_HELPER_SLOT_2_MODEL": "gpt-5.4-mini",
            "APP_HELPER_SLOT_2_ROLE": "primary",
        },
    )

    assert settings.helper_responses_api_key_pool() == ("helper-2-key",)


def test_play_api_key_pool_supports_csv_and_dedup(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_PLAY_BASE_URL": "https://play.example/v1",
            "APP_RESPONSES_PLAY_API_KEY": "play-key-default",
            "APP_RESPONSES_PLAY_MODEL": "gpt-5.4-mini",
            "APP_RESPONSES_PLAY_API_KEYS": " key-a, key-b ; key-a\nkey-c ",
        },
    )

    assert settings.play_responses_api_key_pool() == ("key-a", "key-b", "key-c")


def test_play_api_key_pool_falls_back_to_play_key(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_PLAY_BASE_URL": "https://play.example/v1",
            "APP_RESPONSES_PLAY_API_KEY": "play-key-default",
            "APP_RESPONSES_PLAY_MODEL": "gpt-5.4-mini",
        },
    )

    assert settings.play_responses_api_key_pool() == ("play-key-default",)


def test_responses_chat_json_stream_policy_defaults(monkeypatch) -> None:
    settings = _settings_from_env(monkeypatch, {})

    assert settings.responses_chat_json_stream_mode == "auto"
    assert settings.responses_chat_json_stream_host_list() == ("api.xcode.best", "beecode.cc")


def test_responses_chat_json_stream_policy_parses_mode_and_hosts(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_CHAT_JSON_STREAM_MODE": "off",
            "APP_RESPONSES_CHAT_JSON_STREAM_HOSTS": " api.xcode.best ; beecode.cc\ncustom.example ",
        },
    )

    assert settings.responses_chat_json_stream_mode == "off"
    assert settings.responses_chat_json_stream_host_list() == (
        "api.xcode.best",
        "beecode.cc",
        "custom.example",
    )


def test_incomplete_helper_slot_raises(monkeypatch) -> None:
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_HELPER_SLOT_1_BASE_URL": "https://helper-1.example/v1",
            "APP_HELPER_SLOT_1_API_KEY": "helper-1-key",
        },
    )

    try:
        settings.configured_helper_responses_endpoints()
    except RuntimeError as exc:
        assert "helper slot 1 config incomplete" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected incomplete helper slot to raise")


def test_author_gateway_uses_resolved_legacy_gateway_envs(monkeypatch) -> None:
    monkeypatch.setattr(author_gateway_module, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_GATEWAY_BASE_URL": "https://legacy.example/v1",
            "APP_GATEWAY_API_KEY": "legacy-key",
            "APP_GATEWAY_MODEL": "legacy-model",
        },
    )

    gateway = author_gateway_module.get_author_llm_gateway(settings=settings)

    assert gateway.client["base_url"] == "https://legacy.example/v1"
    assert gateway.client["api_key"] == "legacy-key"
    assert gateway.model == "legacy-model"


def test_author_gateway_prefers_author_specific_envs(monkeypatch) -> None:
    monkeypatch.setattr(author_gateway_module, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_BASE_URL": "https://generic.example/v1",
            "APP_RESPONSES_API_KEY": "generic-key",
            "APP_RESPONSES_MODEL": "generic-model",
            "APP_RESPONSES_AUTHOR_BASE_URL": "https://author.example/v1",
            "APP_RESPONSES_AUTHOR_API_KEY": "author-key",
            "APP_RESPONSES_AUTHOR_MODEL": "author-model",
        },
    )

    gateway = author_gateway_module.get_author_llm_gateway(settings=settings)

    assert gateway.client["base_url"] == "https://author.example/v1"
    assert gateway.client["api_key"] == "author-key"
    assert gateway.model == "author-model"


def test_play_gateway_uses_play_model_override_from_legacy_envs(monkeypatch) -> None:
    monkeypatch.setattr(play_gateway_module, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_GATEWAY_BASE_URL": "https://legacy.example/v1",
            "APP_GATEWAY_API_KEY": "legacy-key",
            "APP_GATEWAY_MODEL": "legacy-model",
            "APP_GATEWAY_PLAY_MODEL": "legacy-play-model",
        },
    )

    gateway = play_gateway_module.get_play_llm_gateway(settings=settings)

    assert gateway.client["base_url"] == "https://legacy.example/v1"
    assert gateway.client["api_key"] == "legacy-key"
    assert gateway.model == "legacy-play-model"


def test_play_gateway_prefers_play_specific_envs(monkeypatch) -> None:
    monkeypatch.setattr(play_gateway_module, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_BASE_URL": "https://generic.example/v1",
            "APP_RESPONSES_API_KEY": "generic-key",
            "APP_RESPONSES_MODEL": "generic-model",
            "APP_RESPONSES_PLAY_BASE_URL": "https://play.example/v1",
            "APP_RESPONSES_PLAY_API_KEY": "play-key",
            "APP_RESPONSES_PLAY_MODEL": "play-model",
        },
    )

    gateway = play_gateway_module.get_play_llm_gateway(settings=settings)

    assert gateway.client["base_url"] == "https://play.example/v1"
    assert gateway.client["api_key"] == "play-key"
    assert gateway.model == "play-model"


def test_author_gateway_passes_author_api_key_pool(monkeypatch) -> None:
    monkeypatch.setattr(author_gateway_module, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_AUTHOR_BASE_URL": "https://author.example/v1",
            "APP_RESPONSES_AUTHOR_API_KEY": "author-key-a",
            "APP_RESPONSES_AUTHOR_API_KEYS": "author-key-a,author-key-b",
            "APP_RESPONSES_AUTHOR_MODEL": "gpt-5.4-mini",
        },
    )

    gateway = author_gateway_module.get_author_llm_gateway(settings=settings)

    assert gateway.client["api_keys"] == ("author-key-a", "author-key-b")


def test_play_gateway_passes_play_api_key_pool(monkeypatch) -> None:
    monkeypatch.setattr(play_gateway_module, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_PLAY_BASE_URL": "https://play.example/v1",
            "APP_RESPONSES_PLAY_API_KEY": "play-key-a",
            "APP_RESPONSES_PLAY_API_KEYS": "play-key-a,play-key-b",
            "APP_RESPONSES_PLAY_MODEL": "gpt-5.4-mini",
        },
    )

    gateway = play_gateway_module.get_play_llm_gateway(settings=settings)

    assert gateway.client["api_keys"] == ("play-key-a", "play-key-b")


def test_benchmark_playtest_agent_client_uses_resolved_primary_and_helper_envs(monkeypatch) -> None:
    monkeypatch.setattr(live_api_playtest, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_GATEWAY_BASE_URL": "https://legacy.example/v1",
            "APP_GATEWAY_API_KEY": "legacy-key",
            "APP_GATEWAY_MODEL": "legacy-model",
            "APP_GATEWAY_PLAY_MODEL": "legacy-play-model",
            "APP_HELPER_GATEWAY_BASE_URL": "https://helper.example/v1",
            "APP_HELPER_GATEWAY_API_KEY": "helper-key",
            "APP_HELPER_GATEWAY_MODEL": "helper-model",
        },
    )

    primary = live_api_playtest.PlaytestAgentClient(live_api_playtest.PERSONAS[0], settings=settings)
    helper = live_api_playtest.PlaytestAgentClient(live_api_playtest.PERSONAS[0], settings=settings, provider="helper")

    assert primary._provider == "primary"
    assert primary._transport.client["base_url"] == "https://legacy.example/v1"
    assert primary._transport.model == "legacy-play-model"
    assert helper._provider == "helper"
    assert helper._transport.client["base_url"] == "https://helper.example/v1"
    assert helper._transport.model == "helper-model"


def test_benchmark_playtest_agent_client_uses_play_specific_envs(monkeypatch) -> None:
    monkeypatch.setattr(live_api_playtest, "build_openai_client", lambda **kwargs: kwargs)
    settings = _settings_from_env(
        monkeypatch,
        {
            "APP_RESPONSES_BASE_URL": "https://generic.example/v1",
            "APP_RESPONSES_API_KEY": "generic-key",
            "APP_RESPONSES_MODEL": "generic-model",
            "APP_RESPONSES_PLAY_BASE_URL": "https://play.example/v1",
            "APP_RESPONSES_PLAY_API_KEY": "play-key",
            "APP_RESPONSES_PLAY_MODEL": "play-model",
        },
    )

    primary = live_api_playtest.PlaytestAgentClient(live_api_playtest.PERSONAS[0], settings=settings)

    assert primary._provider == "primary"
    assert primary._transport.client["base_url"] == "https://play.example/v1"
    assert primary._transport.client["api_key"] == "play-key"
    assert primary._transport.model == "play-model"
