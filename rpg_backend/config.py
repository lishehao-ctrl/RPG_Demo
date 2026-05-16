from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class HelperResponsesEndpoint:
    slot_name: str
    base_url: str
    api_key: str
    model: str
    use_session_cache: bool
    weight: float
    role: Literal["primary", "backup"]


class Settings(BaseSettings):
    story_library_db_path: str = "artifacts/story_library.sqlite3"
    runtime_state_db_path: str = "artifacts/runtime_state.sqlite3"
    default_actor_id: str = "local-dev"
    auth_session_ttl_seconds: int = Field(default=60 * 60 * 24 * 30, ge=300)
    auth_session_cookie_name: str = "rpg_demo_session"
    auth_session_cookie_secure: bool = False
    auth_session_cookie_domain: str | None = None
    auth_session_cookie_samesite: str = "lax"
    play_session_ttl_seconds: int = Field(default=900, ge=60)
    enable_benchmark_api: bool = False
    public_demo_authoring_enabled: bool = True
    public_demo_daily_ip_llm_limit: int | None = Field(default=500, ge=1)
    public_demo_daily_user_llm_limit: int | None = Field(default=120, ge=1)
    author_product_run_mode: str = "deterministic"
    author_v3_enabled: bool = False
    author_v3_run_mode: str = "deterministic"
    author_v3_max_llm_rounds: int = Field(default=2, ge=1, le=5)
    author_v3_tension_score_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    runtime_profile: str | None = None
    gateway_base_url: str | None = None
    gateway_responses_base_url: str | None = None
    gateway_api_key: str | None = None
    gateway_model: str | None = None
    gateway_author_base_url: str | None = None
    gateway_author_responses_base_url: str | None = None
    gateway_author_api_key: str | None = None
    gateway_author_model: str | None = None
    gateway_play_base_url: str | None = None
    gateway_play_responses_base_url: str | None = None
    gateway_play_api_key: str | None = None
    gateway_play_model: str | None = None
    helper_gateway_base_url: str | None = None
    helper_gateway_responses_base_url: str | None = None
    helper_gateway_api_key: str | None = None
    helper_gateway_model: str | None = None
    responses_base_url: str | None = None
    responses_api_key: str | None = None
    responses_api_keys: str | None = None
    responses_model: str | None = None
    responses_author_base_url: str | None = None
    responses_author_api_key: str | None = None
    responses_author_api_keys: str | None = None
    responses_author_model: str | None = None
    responses_play_base_url: str | None = None
    responses_play_api_key: str | None = None
    responses_play_api_keys: str | None = None
    responses_play_model: str | None = None
    responses_play_requests_per_minute: int | None = Field(default=500, ge=1)
    responses_author_requests_per_minute: int | None = Field(default=None, ge=1)
    responses_timeout_seconds: float = Field(default=20.0, gt=0)
    responses_timeout_seconds_llm_text_audit: float = Field(default=120.0, gt=0)
    responses_timeout_seconds_author_v2_qwen: float = Field(default=45.0, gt=0)
    responses_author_qwen_requests_per_minute: int | None = Field(default=None, ge=1)
    responses_author_use_session_cache: bool | None = None
    responses_play_use_session_cache: bool | None = None
    responses_use_session_cache: bool | None = None
    helper_responses_base_url: str | None = None
    helper_responses_api_key: str | None = None
    helper_responses_model: str | None = None
    helper_responses_use_session_cache: bool | None = None
    helper_responses_requests_per_minute: int | None = Field(default=None, ge=1)
    helper_responses_api_keys: str | None = None
    helper_responses_enable_web_search: bool = False
    helper_slot_1_base_url: str | None = None
    helper_slot_1_api_key: str | None = None
    helper_slot_1_model: str | None = None
    helper_slot_1_use_session_cache: bool | None = None
    helper_slot_1_weight: float | None = Field(default=None, gt=0)
    helper_slot_1_role: Literal["primary", "backup"] | None = None
    helper_slot_2_base_url: str | None = None
    helper_slot_2_api_key: str | None = None
    helper_slot_2_model: str | None = None
    helper_slot_2_use_session_cache: bool | None = None
    helper_slot_2_weight: float | None = Field(default=None, gt=0)
    helper_slot_2_role: Literal["primary", "backup"] | None = None
    helper_slot_3_base_url: str | None = None
    helper_slot_3_api_key: str | None = None
    helper_slot_3_model: str | None = None
    helper_slot_3_use_session_cache: bool | None = None
    helper_slot_3_weight: float | None = Field(default=None, gt=0)
    helper_slot_3_role: Literal["primary", "backup"] | None = None
    responses_session_cache_header: str = "x-dashscope-session-cache"
    responses_session_cache_value: str = "enable"
    responses_input_price_per_million_tokens_rmb: float = Field(default=0.2, ge=0)
    responses_output_price_per_million_tokens_rmb: float = Field(default=2.0, ge=0)
    responses_usd_per_rmb: float = Field(default=0.14, ge=0)
    responses_session_cache_hit_multiplier: float = Field(default=0.1, ge=0)
    responses_session_cache_creation_multiplier: float = Field(default=1.25, ge=0)
    responses_enable_thinking_play: bool = False
    responses_json_content_type_hint: bool = False
    responses_json_object_prompt_only: bool = True
    responses_chat_json_stream_mode: Literal["auto", "force", "off"] = "auto"
    responses_chat_json_stream_hosts: str = "api.xcode.best,beecode.cc"
    play_v2_narration_profile: Literal["npc_texture_v2"] = "npc_texture_v2"
    internal_test_strict_no_repair_fallback: bool = False
    play_v2_intent_compiler_use_llm: bool = True
    play_v2_intent_compiler_max_output_tokens: int = Field(default=220, ge=64, le=1200)
    play_v2_micro_sim_use_llm: bool = True
    play_v2_micro_sim_max_output_tokens: int = Field(default=260, ge=80, le=1200)
    play_v2_micro_sim_max_candidates: int = Field(default=5, ge=1, le=5)
    play_v2_policy_cost_visibility_enabled: bool = True
    play_v2_policy_question_progress_v2_enabled: bool = True
    play_v2_policy_role_divergence_v2_enabled: bool = True
    play_v2_dramatic_rewrite_use_llm: bool = True
    play_v2_dramatic_rewrite_max_output_tokens: int = Field(default=360, ge=120, le=1400)
    play_v2_spec_compose_prewarm_enabled: bool = False
    semantic_autotune_patch_path: str | None = None
    quality_tuning_patch_path: str | None = None
    responses_enable_thinking_author_overview: bool = False
    responses_enable_thinking_author_beat_plan: bool = False
    responses_enable_thinking_author_scene: bool = False
    responses_enable_thinking_author_rulepack: bool = False
    responses_enable_thinking_story_quality_judge: bool = False
    responses_max_output_tokens_author_beat_skeleton: int | None = Field(default=1200, ge=1)
    responses_max_output_tokens_author_beat_repair: int | None = Field(default=1000, ge=1)
    responses_max_output_tokens_play_interpret: int | None = Field(default=280, ge=1)
    responses_max_output_tokens_play_interpret_repair: int | None = Field(default=320, ge=1)
    responses_max_output_tokens_play_ending_judge: int | None = Field(default=180, ge=1)
    responses_max_output_tokens_play_ending_judge_repair: int | None = Field(default=120, ge=1)
    responses_max_output_tokens_play_pyrrhic_critic: int | None = Field(default=120, ge=1)
    responses_max_output_tokens_play_render: int | None = Field(default=560, ge=1)
    responses_max_output_tokens_play_render_repair: int | None = Field(default=720, ge=1)
    responses_max_output_tokens_author_overview: int | None = Field(default=800, ge=1)
    responses_max_output_tokens_author_beat_plan: int | None = Field(default=1500, ge=1)
    responses_max_output_tokens_author_scene: int | None = Field(default=1600, ge=1)
    responses_max_output_tokens_author_rulepack: int | None = Field(default=900, ge=1)
    responses_max_output_tokens_story_quality_judge: int | None = Field(default=700, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        extra="ignore",
    )

    @staticmethod
    def _clean_optional(value: str | None) -> str:
        return (value or "").strip()

    @staticmethod
    def _parse_api_key_pool(raw: str | None) -> tuple[str, ...]:
        tokenized = (raw or "").strip()
        if not tokenized:
            return ()
        keys: list[str] = []
        seen: set[str] = set()
        for token in re.split(r"[,\n;\s]+", tokenized):
            candidate = token.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            keys.append(candidate)
        return tuple(keys)

    def resolved_responses_base_url(self) -> str:
        return (
            self._clean_optional(self.responses_base_url)
            or self._clean_optional(self.gateway_responses_base_url)
            or self._clean_optional(self.gateway_base_url)
        )

    def resolved_responses_api_key(self) -> str:
        return self._clean_optional(self.responses_api_key) or self._clean_optional(self.gateway_api_key)

    def responses_api_key_pool(self) -> tuple[str, ...]:
        parsed = self._parse_api_key_pool(self.responses_api_keys)
        if parsed:
            return parsed
        resolved = self.resolved_responses_api_key()
        return (resolved,) if resolved else ()

    def resolved_responses_model(self) -> str:
        return self._clean_optional(self.responses_model) or self._clean_optional(self.gateway_model)

    def resolved_author_responses_base_url(self) -> str:
        return (
            self._clean_optional(self.responses_author_base_url)
            or self._clean_optional(self.gateway_author_responses_base_url)
            or self._clean_optional(self.gateway_author_base_url)
            or self.resolved_responses_base_url()
        )

    def resolved_author_responses_api_key(self) -> str:
        return (
            self._clean_optional(self.responses_author_api_key)
            or self._clean_optional(self.gateway_author_api_key)
            or self.resolved_responses_api_key()
        )

    def author_responses_api_key_pool(self) -> tuple[str, ...]:
        parsed = self._parse_api_key_pool(self.responses_author_api_keys)
        if parsed:
            return parsed
        keys: list[str] = []
        seen: set[str] = set()
        author_key = self.resolved_author_responses_api_key()
        if author_key:
            keys.append(author_key)
            seen.add(author_key)
        for candidate in self.responses_api_key_pool():
            if candidate in seen:
                continue
            seen.add(candidate)
            keys.append(candidate)
        return tuple(keys)

    def resolved_author_responses_model(self) -> str:
        return (
            self._clean_optional(self.responses_author_model)
            or self._clean_optional(self.gateway_author_model)
            or self.resolved_responses_model()
        )

    def resolved_play_responses_base_url(self) -> str:
        return (
            self._clean_optional(self.responses_play_base_url)
            or self._clean_optional(self.gateway_play_responses_base_url)
            or self._clean_optional(self.gateway_play_base_url)
            or self.resolved_responses_base_url()
        )

    def resolved_play_responses_api_key(self) -> str:
        return (
            self._clean_optional(self.responses_play_api_key)
            or self._clean_optional(self.gateway_play_api_key)
            or self.resolved_responses_api_key()
        )

    def resolved_play_responses_model(self) -> str:
        return (
            self._clean_optional(self.responses_play_model)
            or self._clean_optional(self.gateway_play_model)
            or self.resolved_responses_model()
        )

    def responses_chat_json_stream_host_list(self) -> tuple[str, ...]:
        raw = self._clean_optional(self.responses_chat_json_stream_hosts)
        if not raw:
            return ()
        hosts: list[str] = []
        seen: set[str] = set()
        for token in re.split(r"[,\n;\s]+", raw):
            candidate = token.strip().lower()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            hosts.append(candidate)
        return tuple(hosts)

    def play_responses_api_key_pool(self) -> tuple[str, ...]:
        parsed = self._parse_api_key_pool(self.responses_play_api_keys)
        if parsed:
            return parsed
        keys: list[str] = []
        seen: set[str] = set()
        play_key = self.resolved_play_responses_api_key()
        if play_key:
            keys.append(play_key)
            seen.add(play_key)
        for candidate in self.responses_api_key_pool():
            if candidate in seen:
                continue
            seen.add(candidate)
            keys.append(candidate)
        return tuple(keys)

    def resolved_responses_model_for_text_capability(self, capability: str) -> str:
        if capability.startswith("play."):
            return self.resolved_play_responses_model()
        return self.resolved_author_responses_model()

    def resolved_responses_use_session_cache(self) -> bool:
        base_url = self.resolved_responses_base_url()
        if self.responses_use_session_cache is not None:
            return bool(self.responses_use_session_cache)
        return "dashscope" in base_url.casefold()

    def resolved_author_responses_use_session_cache(self) -> bool:
        base_url = self.resolved_author_responses_base_url()
        if self.responses_author_use_session_cache is not None:
            return bool(self.responses_author_use_session_cache)
        if self.responses_use_session_cache is not None:
            return bool(self.responses_use_session_cache)
        return "dashscope" in base_url.casefold()

    def resolved_play_responses_use_session_cache(self) -> bool:
        base_url = self.resolved_play_responses_base_url()
        if self.responses_play_use_session_cache is not None:
            return bool(self.responses_play_use_session_cache)
        if self.responses_use_session_cache is not None:
            return bool(self.responses_use_session_cache)
        return "dashscope" in base_url.casefold()

    def resolved_helper_responses_base_url(self) -> str:
        endpoints = self.configured_helper_responses_endpoints()
        return endpoints[0].base_url if endpoints else ""

    def resolved_helper_responses_api_key(self) -> str:
        endpoints = self.configured_helper_responses_endpoints()
        return endpoints[0].api_key if endpoints else ""

    def resolved_helper_responses_model(self) -> str:
        endpoints = self.configured_helper_responses_endpoints()
        return endpoints[0].model if endpoints else ""

    def resolved_helper_responses_use_session_cache(self) -> bool:
        endpoints = self.configured_helper_responses_endpoints()
        return endpoints[0].use_session_cache if endpoints else False

    def helper_responses_api_key_pool(self) -> tuple[str, ...]:
        parsed = self._parse_api_key_pool(self.helper_responses_api_keys)
        if parsed:
            return parsed
        endpoints = self.configured_helper_responses_endpoints()
        return (endpoints[0].api_key,) if endpoints else ()

    def _helper_slot_endpoint(self, slot_number: int) -> HelperResponsesEndpoint | None:
        base_url = self._clean_optional(getattr(self, f"helper_slot_{slot_number}_base_url"))
        api_key = self._clean_optional(getattr(self, f"helper_slot_{slot_number}_api_key"))
        model = self._clean_optional(getattr(self, f"helper_slot_{slot_number}_model"))
        use_session_cache = getattr(self, f"helper_slot_{slot_number}_use_session_cache")
        weight = getattr(self, f"helper_slot_{slot_number}_weight")
        role = getattr(self, f"helper_slot_{slot_number}_role")
        if not any((base_url, api_key, model)):
            return None
        if not (base_url and api_key and model):
            raise RuntimeError(f"helper slot {slot_number} config incomplete")
        return HelperResponsesEndpoint(
            slot_name=f"helper_slot_{slot_number}",
            base_url=base_url,
            api_key=api_key,
            model=model,
            use_session_cache=bool(use_session_cache) if use_session_cache is not None else ("dashscope" in base_url.casefold()),
            weight=float(weight) if weight is not None else 1.0,
            role=str(role or "").strip() or "backup",  # type: ignore[arg-type]
        )

    def _legacy_helper_endpoint(self) -> HelperResponsesEndpoint | None:
        base_url = (
            self._clean_optional(self.helper_responses_base_url)
            or self._clean_optional(self.helper_gateway_responses_base_url)
            or self._clean_optional(self.helper_gateway_base_url)
        )
        api_key = self._clean_optional(self.helper_responses_api_key) or self._clean_optional(self.helper_gateway_api_key)
        model = self._clean_optional(self.helper_responses_model) or self._clean_optional(self.helper_gateway_model)
        if not any((base_url, api_key, model)):
            return None
        if not (base_url and api_key and model):
            raise RuntimeError("legacy helper config incomplete")
        return HelperResponsesEndpoint(
            slot_name="legacy_helper",
            base_url=base_url,
            api_key=api_key,
            model=model,
            use_session_cache=bool(self.helper_responses_use_session_cache)
            if self.helper_responses_use_session_cache is not None
            else ("dashscope" in base_url.casefold()),
            weight=1.0,
            role="primary",
        )

    def configured_helper_responses_endpoints(self) -> tuple[HelperResponsesEndpoint, ...]:
        endpoints = [
            endpoint
            for endpoint in (
                self._helper_slot_endpoint(1),
                self._helper_slot_endpoint(2),
                self._helper_slot_endpoint(3),
            )
            if endpoint is not None
        ]
        if endpoints:
            explicit_primary = next((endpoint.slot_name for endpoint in endpoints if endpoint.role == "primary"), None)
            primary_slot_name = explicit_primary or endpoints[0].slot_name
            primary = next(endpoint for endpoint in endpoints if endpoint.slot_name == primary_slot_name)
            backups = [endpoint for endpoint in endpoints if endpoint.slot_name != primary_slot_name]
            normalized = [
                HelperResponsesEndpoint(
                    slot_name=primary.slot_name,
                    base_url=primary.base_url,
                    api_key=primary.api_key,
                    model=primary.model,
                    use_session_cache=primary.use_session_cache,
                    weight=primary.weight,
                    role="primary",
                ),
                *[
                    HelperResponsesEndpoint(
                        slot_name=endpoint.slot_name,
                        base_url=endpoint.base_url,
                        api_key=endpoint.api_key,
                        model=endpoint.model,
                        use_session_cache=endpoint.use_session_cache,
                        weight=endpoint.weight,
                        role="backup",
                    )
                    for endpoint in backups
                ],
            ]
            return tuple(normalized)
        legacy = self._legacy_helper_endpoint()
        return (legacy,) if legacy is not None else ()


@lru_cache
def get_settings() -> Settings:
    return Settings()
