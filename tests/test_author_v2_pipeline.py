from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from rpg_backend.author_v2.gateway import (
    AUTHOR_V2_PRIORITY_CHAIN,
    AuthorV2LLMGateway,
    get_author_v2_llm_gateway,
    resolve_author_v2_live_mode_chain,
)
from rpg_backend.author_v2.ip_library import URBAN_IP_LIBRARY, bind_slots_to_ip_cast, build_slot_candidate_pool
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.author_v2.quality_gates import (
    evaluate_seed_preservation_gate,
    evaluate_sibling_divergence_gate,
    evaluate_surface_signal_readability,
)
from rpg_backend.author_v2.template_library import TEMPLATE_LIBRARY, build_seed_fingerprint, get_template_spec, match_story_template
from rpg_backend.author_v2.workflow import (
    _compile_segment_with_mode,
    _compile_single_segment,
    _sanitize_voice_atoms_delta_payload,
    allocate_segment_contracts,
    bind_ip_cast,
    compile_voice_atoms,
    compile_segment_playbooks,
    plan_cast_slots,
    run_author_play_graph,
    select_arc_template,
)
import rpg_backend.author_v2.workflow as workflow_module
from rpg_backend.config import Settings, get_settings
from tools.urban_author_play_benchmarks.gold_set import mini_gold_realistic_6, v1_topic_gold_14
from tools.urban_author_play_benchmarks.holdout_case_catalog import build_holdout_case_catalog


class _DynamicFakeGateway:
    def __init__(self, profile_id: str = "live_gpt_5_4_mini") -> None:
        self.profile_id = profile_id
        self.model = "gpt-5.4-mini"
        self.call_trace: list[dict] = []
        self.max_output_tokens_preview = 800
        self.max_output_tokens_cast_slots = 800
        self.max_output_tokens_segment_allocation = 1500
        self.max_output_tokens_segment_playbook = 1600

    def invoke_json(
        self,
        *,
        system_prompt,
        user_payload,
        max_output_tokens,
        operation_name,
        response_format_type=None,
    ):  # noqa: ANN001
        self.call_trace.append(
            {
                "operation": operation_name,
                "response_id": f"{operation_name}_resp",
                "used_previous_response_id": False,
                "session_cache_enabled": False,
                "max_output_tokens": max_output_tokens,
                "input_characters": len(str(user_payload)),
                "response_format_type": response_format_type,
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        )
        if operation_name == "author_v2.preview_synthesis":
            payload = _preview_delta_from_draft(user_payload["deterministic_draft"])
            payload["bomb_moment"] = "在董事会镜头前，当众把最不该说破的录音放出来。"
            return SimpleNamespace(payload=payload)
        if operation_name == "author_v2.voice_atoms":
            delta_payload: dict[str, list[dict[str, object]]] = {}
            for character_id, atoms in user_payload["voice_atom_catalog_by_character"].items():
                assert atoms
                sampled = atoms[:2]
                delta_payload[character_id] = [
                    {
                        "atom_id": atom["atom_id"],
                        "line_stub": f"{atom.get('line_stub_seed') or atom.get('line_stub') or '这句要更像当场压迫'} 这句要更像当场压迫。",
                        "style_tags": list(atom.get("style_tags") or [])[:3],
                    }
                    for atom in sampled
                ]
            return SimpleNamespace(payload={"voice_atom_deltas_by_character": delta_payload})
        if operation_name == "author_v2.segment_playbook":
            playbook = dict(user_payload["playbook_base"])
            return SimpleNamespace(
                payload={
                    "scene_goal": f"{playbook['scene_goal']} 让公开失控真正发生。",
                    "emotional_goal": str(playbook["emotional_goal"]),
                    "render_cues": list(playbook["render_cues"][:4]) + ["style:bomb:public_drop"],
                }
            )
        raise AssertionError(f"unexpected operation {operation_name}")


def _preview_delta_from_draft(draft: dict[str, object]) -> dict[str, object]:
    delta_keys = (
        "hook",
        "bomb_moment",
        "cost_of_truth",
        "protagonist_public_identity",
        "protagonist_hidden_need",
        "social_arena",
        "relationship_setup",
        "taboo_secret",
        "share_hook",
    )
    return {key: draft[key] for key in delta_keys if key in draft}


def _accepted_blueprint(seed: str = "豪门订婚宴上，最体面的未婚夫、旧爱和律师一起逼她站队，做成标准都市关系戏。"):
    preview, _ = run_preview_blueprint_graph(seed)
    return apply_blueprint_edits(preview)


def test_preview_graph_returns_valid_blueprint() -> None:
    preview, state = run_preview_blueprint_graph("顶流直播夜，隐恋偷拍视频即将引爆热搜。")

    assert preview.preview_id.startswith("preview_")
    assert preview.story_shell_id == "entertainment_scandal"
    assert preview.cast_count_target >= 3
    assert state["quality_trace"]


def test_preview_live_mode_falls_back_when_gateway_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("rpg_backend.author_v2.preview.get_author_v2_llm_gateway", lambda _mode: (_ for _ in ()).throw(RuntimeError("missing")))

    preview, state = run_preview_blueprint_graph("豪门家宴上，旧案录音要被当众说破。", live_mode="live_qwen3_5_plus")

    assert preview.story_shell_id == "wealth_families"
    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")
    assert synth_record["outcome"] == "fallback"
    assert synth_record["source"] == "live_qwen3_5_plus"
    assert synth_record["reasons"] == ["retry_exhausted:live_gateway_unavailable"]


def test_preview_live_mode_rejects_schema_drift_and_falls_back() -> None:
    seed = "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。"
    preview_id = "preview_locked_case"

    deterministic_preview, _ = run_preview_blueprint_graph(seed, preview_id=preview_id)

    class _PreviewRepairGateway(_DynamicFakeGateway):
        def invoke_json(
            self,
            *,
            system_prompt,
            user_payload,
            max_output_tokens,
            operation_name,
            response_format_type=None,
        ):  # noqa: ANN001
            self.call_trace.append(
                {
                    "operation": operation_name,
                    "response_id": f"{operation_name}_resp",
                    "used_previous_response_id": False,
                    "session_cache_enabled": False,
                    "max_output_tokens": max_output_tokens,
                    "input_characters": len(str(user_payload)),
                    "response_format_type": response_format_type,
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                }
            )
            payload = _preview_delta_from_draft(user_payload["deterministic_draft"])
            payload.update(
                {
                    "route_promise": "",
                    "bomb_moment": "在订婚宴主桌前，当众放出那段最不该见光的录音。",
                    "extra_field": "should be ignored",
                }
            )
            return SimpleNamespace(payload=payload)

    preview, state = run_preview_blueprint_graph(
        seed,
        preview_id=preview_id,
        live_mode="live_qwen3_5_flash",
        gateway=_PreviewRepairGateway(profile_id="live_qwen3_5_flash"),
    )

    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")

    assert synth_record["outcome"] == "accepted"
    assert preview.preview_id == deterministic_preview.preview_id
    assert preview.story_shell_id == deterministic_preview.story_shell_id
    assert preview.worldly_desire_type == deterministic_preview.worldly_desire_type
    assert preview.route_promise == deterministic_preview.route_promise
    assert preview.bomb_moment == "在订婚宴主桌前，当众放出那段最不该见光的录音。"


def test_preview_seed_fingerprint_json_equivalence_does_not_trigger_locked() -> None:
    class _EquivalentFingerprintGateway(_DynamicFakeGateway):
        def invoke_json(
            self,
            *,
            system_prompt,
            user_payload,
            max_output_tokens,
            operation_name,
            response_format_type=None,
        ):  # noqa: ANN001
            self.call_trace.append(
                {
                    "operation": operation_name,
                    "response_id": f"{operation_name}_resp",
                    "used_previous_response_id": False,
                    "session_cache_enabled": False,
                    "max_output_tokens": max_output_tokens,
                    "input_characters": len(str(user_payload)),
                    "response_format_type": response_format_type,
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                }
            )
            payload = _preview_delta_from_draft(user_payload["deterministic_draft"])
            return SimpleNamespace(payload=payload)

    _preview, state = run_preview_blueprint_graph(
        "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。",
        live_mode="live_qwen3_5_flash",
        gateway=_EquivalentFingerprintGateway(profile_id="live_qwen3_5_flash"),
    )
    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")

    assert synth_record["outcome"] == "accepted"
    assert all("seed_fingerprint_locked" not in reason for reason in synth_record["reasons"])


def test_preview_strict_no_repair_fallback_raises_on_retry_exhausted(monkeypatch) -> None:
    monkeypatch.setenv("APP_INTERNAL_TEST_STRICT_NO_REPAIR_FALLBACK", "true")
    get_settings.cache_clear()

    class _PreviewRepairGateway(_DynamicFakeGateway):
        def __init__(self, profile_id: str = "live_qwen3_5_flash") -> None:
            super().__init__(profile_id=profile_id)
            self.attempts = 0

        def invoke_json(
            self,
            *,
            system_prompt,
            user_payload,
            max_output_tokens,
            operation_name,
            response_format_type=None,
        ):  # noqa: ANN001
            self.attempts += 1
            self.call_trace.append(
                {
                    "operation": operation_name,
                    "response_id": f"{operation_name}_resp",
                    "used_previous_response_id": False,
                    "session_cache_enabled": False,
                    "max_output_tokens": max_output_tokens,
                    "input_characters": len(str(user_payload)),
                    "response_format_type": response_format_type,
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                }
            )
            return SimpleNamespace(
                payload={
                    "bomb_moment": "在订婚宴主桌前，当众放出那段最不该见光的录音。",
                    "cost_of_truth": "真相一旦落地，她会赔上位置和体面。",
                }
            )

    gateway = _PreviewRepairGateway(profile_id="live_qwen3_5_flash")
    try:
        try:
            run_preview_blueprint_graph(
                "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。",
                live_mode="live_qwen3_5_flash",
                gateway=gateway,
            )
            assert False, "strict mode should reject retry exhausted preview outcome"
        except RuntimeError as exc:
            assert "strict_no_repair_fallback:synthesize_preview_blueprint:retry_exhausted" in str(exc)
            assert gateway.attempts == 3
    finally:
        get_settings.cache_clear()


def test_preview_live_mode_reports_missing_required_delta_fields() -> None:
    class _MissingDeltaGateway(_DynamicFakeGateway):
        def invoke_json(
            self,
            *,
            system_prompt,
            user_payload,
            max_output_tokens,
            operation_name,
            response_format_type=None,
        ):  # noqa: ANN001
            self.call_trace.append(
                {
                    "operation": operation_name,
                    "response_id": f"{operation_name}_resp",
                    "used_previous_response_id": False,
                    "session_cache_enabled": False,
                    "max_output_tokens": max_output_tokens,
                    "input_characters": len(str(user_payload)),
                    "response_format_type": response_format_type,
                    "usage": {"input_tokens": 10, "output_tokens": 20},
                }
            )
            return SimpleNamespace(
                payload={
                    "bomb_moment": "在直播镜头前，最体面的人先失控。",
                    "cost_of_truth": "真相一旦落地，她会赔上位置和体面。",
                }
            )

    _preview, state = run_preview_blueprint_graph(
        "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。",
        live_mode="live_qwen3_5_flash",
        gateway=_MissingDeltaGateway(profile_id="live_qwen3_5_flash"),
    )
    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")

    assert synth_record["outcome"] == "fallback"
    assert "missing_required_keys=hook" in synth_record["reasons"][0]
    assert "returned_keys=bomb_moment+cost_of_truth" in synth_record["reasons"][0]


def test_apply_blueprint_edits_only_changes_editable_fields() -> None:
    preview, _ = run_preview_blueprint_graph("董事会前夜，并购黑账和暧昧站队一起逼近。")

    accepted = apply_blueprint_edits(
        preview,
        {
            "social_arena": "闭门董事会",
            "bomb_moment": "在闭门董事会上，当众放出决定性录音。",
            "cast_count_target": 5,
        },
    )

    assert accepted.social_arena == "闭门董事会"
    assert accepted.bomb_moment == "在闭门董事会上，当众放出决定性录音。"
    assert accepted.cast_count_target == 5
    assert accepted.hook == preview.hook
    assert accepted.route_target_count == preview.route_target_count


def test_arc_template_selection_is_deterministic() -> None:
    short = _accepted_blueprint().model_copy(update={"play_length_preset": "5_8", "cast_count_target": 4})
    compact = _accepted_blueprint().model_copy(update={"play_length_preset": "10_12", "cast_count_target": 4})
    standard = _accepted_blueprint().model_copy(update={"play_length_preset": "12_15", "cast_count_target": 5})
    long = _accepted_blueprint().model_copy(update={"play_length_preset": "15_20", "cast_count_target": 6})
    flagship = _accepted_blueprint().model_copy(update={"play_length_preset": "20_25", "cast_count_target": 6})
    super_flagship = _accepted_blueprint().model_copy(update={"play_length_preset": "30_45", "cast_count_target": 7})

    assert select_arc_template(short) == "short_3"
    assert select_arc_template(compact) == "compact_4"
    assert select_arc_template(standard) == "standard_4"
    assert select_arc_template(long) == "long_5"
    assert select_arc_template(flagship) == "flagship_6"
    assert select_arc_template(super_flagship) == "super_flagship_8"


def test_cast_slot_planning_supports_three_to_seven_cast() -> None:
    blueprint = _accepted_blueprint()

    for cast_count in range(3, 8):
        state = {
            "accepted_blueprint": blueprint.model_copy(
                update={
                    "cast_count_target": cast_count,
                    "route_target_count": min(4, cast_count - 1),
                }
            ),
            "quality_trace": [],
        }
        cast_slots = plan_cast_slots(state)["cast_slots"]
        assert len(cast_slots) == cast_count


def test_cast_slot_public_mask_is_semantic_fragment_not_full_sentence() -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]

    assert cast_slots
    assert all("TA" not in slot.public_mask for slot in cast_slots)
    assert all("在外人眼里" not in slot.public_mask for slot in cast_slots)
    assert all("的人" not in slot.public_mask for slot in cast_slots)
    assert all("体面" in slot.public_mask for slot in cast_slots)


def test_urban_ip_library_expands_to_sixty_profiles_with_gender_balance() -> None:
    assert len(URBAN_IP_LIBRARY) == 60
    assert sum(1 for profile in URBAN_IP_LIBRARY if profile.gender == "female") == 30
    assert sum(1 for profile in URBAN_IP_LIBRARY if profile.gender == "male") == 30


def test_preview_gender_pref_propagates_to_binding() -> None:
    preview, _ = run_preview_blueprint_graph("豪门订婚宴上，旧录音和家族站队同时逼近。")
    accepted = apply_blueprint_edits(
        preview,
        {"target_gender_pref": "female", "cast_count_target": 5},
    )
    cast_slots = plan_cast_slots({"accepted_blueprint": accepted, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, accepted)

    assert bound_cast
    assert all(member.gender == "female" for member in bound_cast)


def test_bind_ip_cast_honors_preferred_slot_selection_reason() -> None:
    blueprint = _accepted_blueprint("发布会前夜，旧账、舆论和站队都压到同一桌。").model_copy(
        update={"cast_count_target": 5, "route_target_count": 3}
    )
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    candidate_pool = build_slot_candidate_pool(cast_slots, blueprint, top_k=8)
    first_slot = cast_slots[0]
    candidates = list(candidate_pool.get(first_slot.slot_id) or [])
    assert candidates
    assert all("candidate_index" in row for row in candidates)
    preferred = candidates[1]["ip_character_id"] if len(candidates) >= 2 else candidates[0]["ip_character_id"]
    bound_cast = bind_slots_to_ip_cast(
        cast_slots,
        blueprint,
        preferred_selection_by_slot={first_slot.slot_id: preferred},
        preferred_reasons_by_slot={first_slot.slot_id: "llm:关系张力更强，口吻更贴合"},
    )

    assert bound_cast[0].character_id == preferred
    assert "llm:" in bound_cast[0].selection_reason


def test_bind_ip_cast_stage_records_frozen_snapshot_metrics() -> None:
    blueprint = _accepted_blueprint("豪门家宴前夜，旧录音和顺位争夺一起顶到台前。").model_copy(
        update={"cast_count_target": 5, "route_target_count": 3}
    )
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    stage_state = bind_ip_cast(
        {
            "accepted_blueprint": blueprint,
            "cast_slots": cast_slots,
            "quality_trace": [],
            "live_mode": "deterministic",
        }
    )

    snapshot = stage_state["decision_snapshot"].frozen_candidate_pool
    bind_record = next(record for record in stage_state["quality_trace"] if record["stage"] == "bind_ip_cast")

    assert snapshot.snapshot_id.startswith("cast_snapshot_")
    assert bind_record["decision_source"] == "deterministic"
    assert bind_record["frozen_snapshot_id"] == snapshot.snapshot_id
    assert bind_record["frozen_candidate_pool_slots"] == len(cast_slots)
    assert bind_record["frozen_candidate_pool_size"] >= len(cast_slots)


def test_ip_binding_is_stable_and_respects_disallowed_pairings() -> None:
    blueprint = _accepted_blueprint("办公室权斗里，总裁、秘书、律师和旧同盟逼主角站队，做成旗舰局。").model_copy(
        update={"story_shell_id": "office_power", "cast_count_target": 6, "route_target_count": 3}
    )
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]

    first = bind_slots_to_ip_cast(cast_slots, blueprint)
    second = bind_slots_to_ip_cast(cast_slots, blueprint)
    ids = {member.character_id for member in first}

    assert [member.character_id for member in first] == [member.character_id for member in second]
    assert not ({"lu_jue", "gu_shaoting"} <= ids)


def test_author_pipeline_compiles_voice_atoms_into_bundle_and_plan() -> None:
    pipeline = run_author_play_graph(_accepted_blueprint("校庆夜场里，旧录音和站队压力一起逼近。"))
    cast_ids = {member.character_id for member in pipeline.bundle.bound_cast}
    required_roles = {segment.segment_role for segment in pipeline.play_plan.segments}

    assert cast_ids
    assert cast_ids <= set(pipeline.bundle.voice_atoms_by_character.keys())
    assert cast_ids <= set(pipeline.play_plan.voice_atoms_by_character.keys())
    for character_id in cast_ids:
        bundle_atoms = pipeline.bundle.voice_atoms_by_character[character_id]
        plan_atoms = pipeline.play_plan.voice_atoms_by_character[character_id]
        assert bundle_atoms
        assert plan_atoms
        assert required_roles <= {atom.segment_role for atom in plan_atoms}


def test_compile_voice_atoms_live_calls_gateway_on_first_attempt(monkeypatch) -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)

    class _CaptureGateway(_DynamicFakeGateway):
        def __init__(self) -> None:
            super().__init__()
            self.voice_calls = 0
            self.last_payload: dict[str, object] | None = None

        def invoke_json(self, **kwargs):  # noqa: ANN003, ANN201
            if kwargs.get("operation_name") == "author_v2.voice_atoms":
                self.voice_calls += 1
                self.last_payload = kwargs.get("user_payload")
            return super().invoke_json(**kwargs)

    gateway = _CaptureGateway()
    monkeypatch.setattr(
        "rpg_backend.author_v2.workflow._resolve_live_gateway",
        lambda live_mode, gateway_override: [("live_gpt_5_4_mini", gateway)],
    )

    result_state = compile_voice_atoms(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
            "llm_call_trace": [],
            "live_mode": "live_gpt_5_4_mini",
        }
    )
    quality_record = next(record for record in result_state["quality_trace"] if record["stage"] == "compile_voice_atoms")

    assert gateway.voice_calls >= 1
    assert quality_record["outcome"] == "accepted"
    assert quality_record["live_attempt_count"] == 1
    assert isinstance(gateway.last_payload, dict)
    assert "batch_character_ids" in gateway.last_payload
    assert gateway.voice_calls == int(gateway.last_payload.get("batch_count") or 1)


def test_sanitize_voice_atoms_delta_payload_coerces_weight_string() -> None:
    payload = {
        "voice_atom_deltas_by_character": {
            "npc_1": [
                {
                    "atom_id": "npc_1:opening:a",
                    "line_stub": "这句要更狠一点",
                    "weight": "约0.82",
                    "style_tags": [" sharp "],
                },
                {
                    "atom_id": "npc_1:opening:b",
                    "line_stub": "这句要更稳一点",
                    "weight": "不提供",
                },
            ]
        }
    }

    sanitized = _sanitize_voice_atoms_delta_payload(payload)
    rows = sanitized["voice_atom_deltas_by_character"]["npc_1"]

    assert rows[0]["weight"] == 0.82
    assert "weight" not in rows[1]


def test_sanitize_voice_atoms_delta_payload_deduplicates_atom_ids() -> None:
    payload = {
        "voice_atom_deltas_by_character": {
            "npc_1": [
                {"atom_id": "npc_1:opening:a", "line_stub": "第一条"},
                {"atom_id": "npc_1:opening:a", "line_stub": "重复条目应该被丢弃"},
                {"atom_id": "npc_1:opening:b", "line_stub": "第二条"},
            ]
        }
    }

    sanitized = _sanitize_voice_atoms_delta_payload(payload)
    rows = sanitized["voice_atom_deltas_by_character"]["npc_1"]

    assert [row["atom_id"] for row in rows] == ["npc_1:opening:a", "npc_1:opening:b"]


def test_segment_allocation_is_coherent_and_has_single_terminal_segment() -> None:
    result = run_author_play_graph(_accepted_blueprint())
    contracts = result.bundle.segment_contracts

    assert len(contracts) == 4
    assert sum(1 for contract in contracts if contract.is_terminal) == 1
    assert len({contract.segment_id for contract in contracts}) == len(contracts)


def test_opening_segment_keeps_high_risk_move_family() -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    contracts = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )["segment_contracts"]

    opening = next(contract for contract in contracts if contract.segment_role == "opening")
    assert any(move in {"accuse", "public_reveal", "betray"} for move in opening.allowed_move_families)


def test_parallel_segment_compile_merges_deterministically(monkeypatch) -> None:
    blueprint = _accepted_blueprint()
    state = {"accepted_blueprint": blueprint, "quality_trace": []}
    arc_state = plan_cast_slots(state)
    cast_slots = arc_state["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    allocation_state = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )

    original = _compile_single_segment

    def _slow_compile(*, blueprint, contract, bound_cast):
        if contract.segment_role == "opening":
            time.sleep(0.03)
        return original(blueprint=blueprint, contract=contract, bound_cast=bound_cast)

    monkeypatch.setattr("rpg_backend.author_v2.workflow._compile_single_segment", _slow_compile)
    result_state = compile_segment_playbooks(
        {
            "accepted_blueprint": blueprint,
            "segment_contracts": allocation_state["segment_contracts"],
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )

    assert [playbook.segment_id for playbook in result_state["segment_playbooks"]] == [
        contract.segment_id for contract in allocation_state["segment_contracts"]
    ]


def test_compile_segment_playbooks_uses_reduced_live_parallelism(monkeypatch) -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    allocation_state = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )
    captured: dict[str, int] = {}
    real_executor = __import__("concurrent.futures").futures.ThreadPoolExecutor

    class _Executor(real_executor):
        def __init__(self, max_workers=None, *args, **kwargs):  # noqa: ANN001
            captured["max_workers"] = int(max_workers)
            super().__init__(max_workers=max_workers, *args, **kwargs)

    def _fake_compile(**kwargs):  # noqa: ANN003, ANN202
        contract = kwargs["contract"]
        playbook = _compile_single_segment(
            blueprint=kwargs["blueprint"],
            contract=contract,
            bound_cast=kwargs["bound_cast"],
        )
        return playbook, [], [], True, {"live_attempt_count": 1, "live_success_count": 1, "provider_failure_count": 0, "used_modes": ["live_gpt_5_4_mini"]}

    monkeypatch.setattr("rpg_backend.author_v2.workflow.ThreadPoolExecutor", _Executor)
    monkeypatch.setattr("rpg_backend.author_v2.workflow._compile_segment_with_mode", _fake_compile)

    compile_segment_playbooks(
        {
            "accepted_blueprint": blueprint,
            "segment_contracts": allocation_state["segment_contracts"],
            "bound_cast": bound_cast,
            "quality_trace": [],
            "live_mode": "pure_gpt",
        }
    )

    assert captured["max_workers"] == 2


def test_compile_segment_playbooks_uses_single_worker_under_strict_gate(monkeypatch) -> None:
    monkeypatch.setenv("APP_INTERNAL_TEST_STRICT_NO_REPAIR_FALLBACK", "true")
    get_settings.cache_clear()
    try:
        blueprint = _accepted_blueprint()
        cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
        bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
        allocation_state = allocate_segment_contracts(
            {
                "accepted_blueprint": blueprint,
                "arc_template_id": "standard_4",
                "bound_cast": bound_cast,
                "quality_trace": [],
            }
        )
        captured: dict[str, int] = {}
        real_executor = __import__("concurrent.futures").futures.ThreadPoolExecutor

        class _Executor(real_executor):
            def __init__(self, max_workers=None, *args, **kwargs):  # noqa: ANN001
                captured["max_workers"] = int(max_workers)
                super().__init__(max_workers=max_workers, *args, **kwargs)

        def _fake_compile(**kwargs):  # noqa: ANN003, ANN202
            contract = kwargs["contract"]
            playbook = _compile_single_segment(
                blueprint=kwargs["blueprint"],
                contract=contract,
                bound_cast=kwargs["bound_cast"],
            )
            return playbook, [], [], True, {"live_attempt_count": 1, "live_success_count": 1, "provider_failure_count": 0, "used_modes": ["live_gpt_5_4_mini"]}

        monkeypatch.setattr("rpg_backend.author_v2.workflow.ThreadPoolExecutor", _Executor)
        monkeypatch.setattr("rpg_backend.author_v2.workflow._compile_segment_with_mode", _fake_compile)

        compile_segment_playbooks(
            {
                "accepted_blueprint": blueprint,
                "segment_contracts": allocation_state["segment_contracts"],
                "bound_cast": bound_cast,
                "quality_trace": [],
                "live_mode": "pure_gpt",
            }
        )
        assert captured["max_workers"] == 1
    finally:
        monkeypatch.delenv("APP_INTERNAL_TEST_STRICT_NO_REPAIR_FALLBACK", raising=False)
        get_settings.cache_clear()


def test_compile_segment_playbook_pure_gpt_retries_three_times_and_uses_shorter_timeout(monkeypatch) -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    allocation_state = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "short_3",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )
    contract = allocation_state["segment_contracts"][0]
    local_cast = [
        member
        for member in bound_cast
        if member.character_id in set(contract.focus_target_ids + contract.rival_target_ids) or member.is_route_target
    ][:3] or bound_cast[:3]

    class _ProviderFailGateway(_DynamicFakeGateway):
        def __init__(self) -> None:
            super().__init__(profile_id="live_gpt_5_4_mini")
            self.timeout_seconds = 20.0
            self.observed_timeout_seconds: list[float] = []

        def invoke_json(self, **kwargs):  # noqa: ANN003, ANN201
            self.observed_timeout_seconds.append(float(self.timeout_seconds))
            self.call_trace.append(
                {
                    "operation": kwargs["operation_name"],
                    "response_id": None,
                    "used_previous_response_id": False,
                    "session_cache_enabled": False,
                    "max_output_tokens": kwargs["max_output_tokens"],
                    "input_characters": len(str(kwargs["user_payload"])),
                    "response_format_type": kwargs.get("response_format_type"),
                    "usage": {},
                    "response_received": False,
                    "failure_code": "llm_provider_failed",
                    "failure_message_bucket": "timeout",
                }
            )
            exc = RuntimeError("timed out")
            exc.code = "llm_provider_failed"  # type: ignore[attr-defined]
            raise exc

    gateway = _ProviderFailGateway()
    monkeypatch.setattr(
        "rpg_backend.author_v2.workflow._resolve_live_gateway",
        lambda live_mode, gateway_override: [("live_gpt_5_4_mini", gateway)],
    )

    _, trace, reasons, live_success, metrics = _compile_segment_with_mode(
        blueprint=blueprint,
        contract=contract,
        bound_cast=local_cast,
        live_mode="pure_gpt",
    )

    assert live_success is False
    assert metrics["live_attempt_count"] == 3
    assert metrics["provider_failure_count"] == 3
    assert gateway.observed_timeout_seconds == [12.0, 12.0, 12.0]
    assert len(trace) == 3
    assert reasons == ["retry_exhausted:live_gpt_5_4_mini:llm_provider_failed"]


def test_compiled_segments_include_three_suggestion_lanes() -> None:
    result = run_author_play_graph(_accepted_blueprint("董事会前夜，并购黑账和暧昧站队一起逼近。"))

    for segment in result.play_plan.segments:
        lane_ids = [lane.lane_id for lane in segment.suggestion_lanes]
        assert lane_ids == ["relationship", "side", "burst"]
        assert all(lane.candidate_move_families for lane in segment.suggestion_lanes)
        assert any(lane.target_priority_ids for lane in segment.suggestion_lanes)


def test_bound_cast_members_include_drama_profile() -> None:
    result = run_author_play_graph(_accepted_blueprint("董事会前夜，并购黑账和暧昧站队一起逼近。"))

    for member in result.play_plan.cast:
        assert member.drama_profile.character_id == member.character_id
        assert member.drama_profile.public_role == member.public_role
        assert member.drama_profile.speech_pattern
        assert member.drama_profile.breaking_point


def test_bound_cast_members_include_strategic_intent() -> None:
    result = run_author_play_graph(_accepted_blueprint("董事会前夜，并购黑账和暧昧站队一起逼近。"))

    for member in result.play_plan.cast:
        assert member.strategic_intent.character_id == member.character_id
        assert member.strategic_intent.primary_stake
        assert member.strategic_intent.loss_trigger
        assert member.strategic_intent.public_survival_mode
        assert member.strategic_intent.debt_memory_bias
        assert member.strategic_intent.preferred_latent_kind
        assert member.strategic_intent.sensitive_latent_kind
        assert member.strategic_intent.delay_preference
        assert member.strategic_intent.regression_payoff


def test_every_bound_cast_member_gets_intent_frame() -> None:
    result = run_author_play_graph(_accepted_blueprint("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。"))

    assert all(member.strategic_intent.protect_target_ids is not None for member in result.play_plan.cast)
    assert all(member.strategic_intent.opportunism_target_ids is not None for member in result.play_plan.cast)
    assert all(member.strategic_intent.sacrifice_target_ids is not None for member in result.play_plan.cast)
    assert all(member.strategic_intent.preferred_latent_kind is not None for member in result.play_plan.cast)
    assert all(member.strategic_intent.sensitive_latent_kind is not None for member in result.play_plan.cast)


def test_play_length_presets_compile_expected_segment_budgets_and_turn_caps() -> None:
    cases = [
        ("5_8", "short_3", [4, 5, 4], 24),
        ("10_12", "compact_4", [4, 5, 5, 4], 28),
        ("12_15", "standard_4", [4, 5, 6, 4], 32),
        ("15_20", "long_5", [4, 5, 6, 6, 4], 36),
        ("20_25", "flagship_6", [4, 5, 6, 6, 5, 4], 40),
        ("30_45", "super_flagship_8", [4, 5, 6, 6, 6, 6, 5, 4], 56),
    ]

    for play_length_preset, expected_template, expected_budget, expected_turn_cap in cases:
        blueprint = _accepted_blueprint().model_copy(update={"play_length_preset": play_length_preset})
        result = run_author_play_graph(blueprint)

        assert result.play_plan.play_length_preset == play_length_preset
        assert result.play_plan.arc_template_id == expected_template
        assert [segment.progress_required for segment in result.play_plan.segments] == expected_budget
        assert all(segment.segment_turn_floor == 6 for segment in result.play_plan.segments)
        assert result.play_plan.max_turns == expected_turn_cap


def test_preview_blueprint_infers_mainstream_play_length_preset() -> None:
    preview, _ = run_preview_blueprint_graph("董事会前夜，并购黑账和暧昧站队一起逼近。想要一个12到15分钟的职场修罗场。")

    assert preview.play_length_preset == "12_15"
    assert preview.experience_band == "8_15"


def test_preview_blueprint_infers_super_flagship_play_length_preset() -> None:
    preview, _ = run_preview_blueprint_graph("并购终局跨夜推进，想要一个30到45分钟的超级旗舰群像局。")

    assert preview.play_length_preset == "30_45"
    assert preview.experience_band == "15_25"


def test_preview_blueprint_has_temptation_public_bomb_and_material_cost() -> None:
    preview, _ = run_preview_blueprint_graph("董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。想要一个12到15分钟的职场修罗场。")

    assert any(token in preview.route_promise for token in ("选谁", "护谁", "逼谁"))
    assert any(token in preview.bomb_moment for token in ("当众", "董事会", "失控"))
    assert any(token in preview.cost_of_truth for token in ("位置", "前途", "体面", "退路"))


def test_ending_matrix_supports_targeted_relationship_and_side_plus_shared_burst() -> None:
    result = run_author_play_graph(_accepted_blueprint("董事会前夜，并购黑账和暧昧站队一起逼近。"))
    ending_ids = {ending.ending_id for ending in result.play_plan.ending_matrix.endings}

    assert "burst_reckoning" in ending_ids
    assert "pyrrhic_control" in ending_ids
    assert "burned_alone" in ending_ids
    route_target_ids = [member.character_id for member in result.play_plan.cast if member.is_route_target]
    for target_id in route_target_ids:
        assert f"relationship_{target_id}" in ending_ids
        assert f"side_{target_id}" in ending_ids


def test_compiled_play_plan_caps_scene_active_cast() -> None:
    result = run_author_play_graph(_accepted_blueprint("豪门继承夜，家宴、旧爱、私生录音和律师一起把她逼到墙角。做成20分钟旗舰局。"))

    assert all(segment.scene_active_cap <= 3 for segment in result.play_plan.segments)


def test_author_play_graph_live_records_trace_and_uses_live_content(monkeypatch) -> None:
    monkeypatch.setattr("rpg_backend.author_v2.workflow.get_author_v2_llm_gateway", lambda _mode: _DynamicFakeGateway())
    blueprint = _accepted_blueprint("董事会前夜，并购黑账和暧昧站队一起逼近。")

    result = run_author_play_graph(blueprint, live_mode="live_gpt_5_4_mini", gateway=_DynamicFakeGateway())

    assert result.state["llm_call_trace"]
    assert any(record["source"] == "live_gpt_5_4_mini" for record in result.state["quality_trace"] if record["stage"] in {"compile_voice_atoms", "compile_segment_playbooks"})
    assert all(record["source"] == "deterministic" for record in result.state["quality_trace"] if record["stage"] in {"plan_cast_slots", "bind_ip_cast", "allocate_segment_contracts"})
    assert any("公开代价" in segment.public_pressure_cue for segment in result.play_plan.segments)


def test_author_play_graph_flash_live_mode_uses_live_branch() -> None:
    blueprint = _accepted_blueprint("豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。")

    result = run_author_play_graph(blueprint, live_mode="live_qwen3_5_flash", gateway=_DynamicFakeGateway(profile_id="live_qwen3_5_flash"))

    assert result.state["llm_call_trace"]
    assert any(record["source"] == "live_qwen3_5_flash" for record in result.state["quality_trace"] if record["stage"] in {"compile_voice_atoms", "compile_segment_playbooks"})
    assert all(record["source"] == "deterministic" for record in result.state["quality_trace"] if record["stage"] in {"plan_cast_slots", "bind_ip_cast", "allocate_segment_contracts"})


def test_live_priority_chain_is_gpt_then_flash_then_plus() -> None:
    assert resolve_author_v2_live_mode_chain("live_priority") == AUTHOR_V2_PRIORITY_CHAIN


def test_pure_gpt_chain_is_gpt_only() -> None:
    assert resolve_author_v2_live_mode_chain("pure_gpt") == ("live_gpt_5_4_mini",)


def test_mainline_live_chain_matches_priority_chain() -> None:
    assert resolve_author_v2_live_mode_chain("mainline_live") == AUTHOR_V2_PRIORITY_CHAIN


def test_preview_live_priority_falls_through_to_flash(monkeypatch) -> None:
    class _FailingGateway(_DynamicFakeGateway):
        def invoke_json(
            self,
            *,
            system_prompt,
            user_payload,
            max_output_tokens,
            operation_name,
            response_format_type=None,
        ):  # noqa: ANN001
            raise RuntimeError("provider down")

    def _gateway_for_mode(mode: str):  # noqa: ANN001, ANN202
        if mode == "live_gpt_5_4_mini":
            return _FailingGateway(profile_id=mode)
        if mode == "live_qwen3_5_flash":
            return _DynamicFakeGateway(profile_id=mode)
        raise AssertionError(f"unexpected mode {mode}")

    monkeypatch.setattr("rpg_backend.author_v2.preview.get_author_v2_llm_gateway", _gateway_for_mode)

    preview, state = run_preview_blueprint_graph(
        "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。",
        live_mode="live_priority",
    )

    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")

    assert preview.bomb_moment.startswith("在董事会镜头前") or "当众" in preview.bomb_moment


def test_seed_fingerprint_rejects_out_of_scope_seed() -> None:
    fingerprint = build_seed_fingerprint("架空王朝里，摄政王和女将军在边境决战前互试底牌。", "12_15")

    assert fingerprint.fit_mode == "out_of_scope"


def test_template_matching_hits_expected_hero_templates() -> None:
    wealth = build_seed_fingerprint("豪门订婚宴上，最体面的未婚夫、突然回来的旧爱和握着遗嘱录音的律师同时逼她站队。", "5_8")
    office = build_seed_fingerprint("董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。", "12_15")
    entertainment = build_seed_fingerprint("综艺录制夜，顶流、经纪人和掌握黑料的人一起玩舆论与真心。", "12_15")
    campus = build_seed_fingerprint("导师评审周里，奖学金、学生会站队和前任回归一起点燃校园修罗场。", "12_15")

    assert match_story_template(wealth).template_id == "wealth_engagement_sideswitch"
    assert match_story_template(office).template_id == "office_board_vote_blackledger"
    assert match_story_template(entertainment).template_id == "entertainment_variety_blackmail_flip"
    assert match_story_template(campus).template_id == "campus_mentor_review_sideswitch"


def test_template_matching_prefers_awards_when_seed_mentions_awards_even_with_live_keyword() -> None:
    fingerprint = build_seed_fingerprint("颁奖礼直播夜，顶流和经纪人都在抢解释权，旧绯闻偷拍视频随时会被推上公屏。", "12_15")

    assert fingerprint.arena_type == "awards_backstage"
    assert match_story_template(fingerprint).template_id == "entertainment_awards_scandal"


def test_template_matching_tiebreak_resolves_holdout_four_misclass_cases() -> None:
    holdout_cases = build_holdout_case_catalog(v1_topic_gold_14(), seed=20260401, variants_per_case=2)
    target_case_ids = {
        "wealth_topic_inheritance_evidence_drop_holdout_1",
        "wealth_topic_inheritance_evidence_drop_holdout_2",
        "office_topic_board_vote_blackledger_holdout_1",
        "office_topic_board_vote_blackledger_holdout_2",
    }
    selected = [case for case in holdout_cases if case.case_id in target_case_ids]

    assert len(selected) == 4
    for case in selected:
        fingerprint = build_seed_fingerprint(case.seed, "12_15")
        assert match_story_template(fingerprint).template_id == case.expected_template_id


def test_template_matching_tiebreak_does_not_regress_base_14_expected_templates() -> None:
    for case in v1_topic_gold_14():
        assert case.expected_template_id is not None
        fingerprint = build_seed_fingerprint(case.seed, "12_15")
        assert match_story_template(fingerprint).template_id == case.expected_template_id


def test_mini_long_arc_problem_cases_match_expected_templates() -> None:
    targeted_case_ids = {
        "entertainment_flagship_awards",
        "wealth_light_sideswitch",
        "wealth_flagship_succession",
        "office_flagship_merger",
    }
    for case in mini_gold_realistic_6():
        if case.case_id not in targeted_case_ids:
            continue
        assert case.expected_template_id is not None
        assert case.expected_play_length_preset is not None
        fingerprint = build_seed_fingerprint(case.seed, str(case.expected_play_length_preset))
        assert fingerprint.fit_mode != "out_of_scope"
        assert match_story_template(fingerprint).template_id == case.expected_template_id


def test_preview_normalization_validates_without_post_patch_repair(monkeypatch) -> None:
    class _NoPublicBombGateway(_DynamicFakeGateway):
        def invoke_json(self, *, system_prompt, user_payload, max_output_tokens, operation_name, response_format_type=None):  # noqa: ANN001
            if operation_name == "author_v2.preview_synthesis":
                payload = _preview_delta_from_draft(user_payload["deterministic_draft"])
                payload["bomb_moment"] = "那段录音突然响起，她连呼吸都卡住了。"
                return SimpleNamespace(payload=payload)
            return super().invoke_json(
                system_prompt=system_prompt,
                user_payload=user_payload,
                max_output_tokens=max_output_tokens,
                operation_name=operation_name,
                response_format_type=response_format_type,
            )

    monkeypatch.setattr("rpg_backend.author_v2.preview.get_author_v2_llm_gateway", lambda _mode: _NoPublicBombGateway(profile_id="live_qwen3_5_flash"))

    preview, state = run_preview_blueprint_graph(
        "校庆晚会前，奖学金竞争和旧录音同时逼她选边。",
        live_mode="live_qwen3_5_flash",
    )

    assert any(token in preview.bomb_moment for token in ("公开", "当众", "直播", "镜头"))
    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")
    assert synth_record["outcome"] == "fallback"
    assert synth_record["reasons"][0].startswith("retry_exhausted:")
    normalize_record = next(record for record in state["quality_trace"] if record["stage"] == "normalize_preview_blueprint")
    assert normalize_record["outcome"] == "accepted"


def test_every_modern_template_has_tone_example_pack() -> None:
    modern_templates = [template for template in TEMPLATE_LIBRARY if template.shell_id != "urban_supernatural"]

    assert len(modern_templates) == 14
    assert all(5 <= len(template.tone_example_pack.lines) <= 8 for template in modern_templates)
    assert all(len(template.tone_example_pack.scenes) == 2 for template in modern_templates)


def test_supernatural_template_has_minimal_tone_example_pack() -> None:
    template = get_template_spec("urban_supernatural_legacy_contract")

    assert len(template.tone_example_pack.lines) >= 5
    assert len(template.tone_example_pack.scenes) == 2


def test_tone_example_pack_semantic_tags_are_populated() -> None:
    for template in TEMPLATE_LIBRARY:
        assert template.tone_example_pack.lines
        assert template.tone_example_pack.scenes
        assert all(line.semantic_tag.reason_family for line in template.tone_example_pack.lines)
        assert all(line.semantic_tag.signal_family for line in template.tone_example_pack.lines)
        assert all(line.semantic_tag.cost_family for line in template.tone_example_pack.lines)
        assert all(scene.semantic_tag.signal_family for scene in template.tone_example_pack.scenes)


def test_deterministic_render_cues_use_template_examples_without_full_copy() -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    contract = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )["segment_contracts"][0]

    playbook = _compile_single_segment(blueprint=blueprint, contract=contract, bound_cast=bound_cast)

    assert playbook.template_tone_example_lines
    assert playbook.template_tone_scene_examples
    assert all(cue.startswith("style:") for cue in playbook.render_cues)
    source_lines = [line.text for line in playbook.template_tone_example_lines]
    assert all(source_line not in " ".join(playbook.render_cues) for source_line in source_lines)
    assert not any(scene.text in " ".join(playbook.render_cues) for scene in playbook.template_tone_scene_examples)


def test_deterministic_segment_playbook_prioritizes_control_leverage_moves() -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    contracts = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )["segment_contracts"]
    first_by_role = {contract.segment_role: contract for contract in contracts}

    opening_playbook = _compile_single_segment(
        blueprint=blueprint,
        contract=first_by_role["opening"],
        bound_cast=bound_cast,
    )
    late_role = "pressure" if "pressure" in first_by_role else ("reversal" if "reversal" in first_by_role else "reveal")
    pressure_playbook = _compile_single_segment(
        blueprint=blueprint,
        contract=first_by_role[late_role],
        bound_cast=bound_cast,
    )

    assert opening_playbook.move_priorities[0] in {"accuse", "probe_secret", "deflect"}
    assert pressure_playbook.move_priorities[0] in {"accuse", "probe_secret", "public_reveal", "betray"}


def test_deterministic_playbook_contains_control_oriented_progression_and_render_cues() -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    reveal_contract = next(
        contract
        for contract in allocate_segment_contracts(
            {
                "accepted_blueprint": blueprint,
                "arc_template_id": "standard_4",
                "bound_cast": bound_cast,
                "quality_trace": [],
            }
        )["segment_contracts"]
        if contract.segment_role == "reveal"
    )

    playbook = _compile_single_segment(blueprint=blueprint, contract=reveal_contract, bound_cast=bound_cast)

    assert "style:control:force_public_settlement" in playbook.render_cues
    assert any(token in playbook.progression_rule_summary for token in ("兑现", "背锅", "失态", "切人"))


def test_tuned_progression_summary_mentions_tradeoff_contract_when_hint_weight_is_high() -> None:
    summary = workflow_module._tuned_progression_summary(
        summary="这一段继续推进局势，不要原地解释。",
        intensity=1.0,
        control_contract_hint_weight=1.3,
    )

    assert "让步" in summary
    assert "升级" in summary


def test_compiled_segment_includes_segment_style_profile() -> None:
    result = run_author_play_graph(_accepted_blueprint())
    segment = result.play_plan.segments[0]

    assert segment.segment_style_profile.reason_families
    assert segment.segment_style_profile.signal_families
    assert segment.segment_style_profile.cost_families
    assert segment.segment_style_profile.cadence_order
    assert segment.segment_style_profile.shell_anchor_tokens


def test_compiled_play_plan_contains_semantic_strategy_pack() -> None:
    result = run_author_play_graph(_accepted_blueprint())
    play_plan = result.play_plan

    assert play_plan.semantic_strategy_version == 8
    assert play_plan.semantic_strategy_pack.question_progress_policy.min_status_by_segment_role
    assert play_plan.semantic_strategy_pack.question_progress_policy_v2.by_segment_id
    assert play_plan.semantic_strategy_pack.segment_interest_policy.by_segment_id
    assert play_plan.semantic_strategy_pack.supporting_divergence_policy.require_reason_family_split
    assert play_plan.semantic_strategy_pack.role_divergence_matrix_v2.by_segment_id
    assert play_plan.semantic_strategy_pack.cost_routing_matrix.rules
    assert play_plan.semantic_strategy_pack.cost_ownership_policy.rules
    assert play_plan.semantic_strategy_pack.callback_policy.rules
    assert play_plan.semantic_strategy_pack.question_arc_policy_v2.by_segment_id
    assert play_plan.semantic_strategy_pack.role_divergence_matrix.by_segment_id
    assert play_plan.semantic_strategy_pack.cost_ownership_matrix_v2.rules
    assert play_plan.semantic_strategy_pack.callback_commit_policy_v2.rules
    assert play_plan.semantic_strategy_pack.cost_return_policy.by_segment_id
    assert play_plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id
    assert play_plan.semantic_strategy_pack.cost_narrative_binding_policy.by_segment_id
    assert play_plan.semantic_strategy_pack.cost_primary_driver_policy_v7.by_segment_id
    assert play_plan.semantic_strategy_pack.cost_primary_driver_policy_v7.due_cost_forces_primary_driver is True
    assert play_plan.semantic_strategy_pack.cost_narrative_binding_policy.due_cost_forces_primary_driver is True
    assert all(
        list(rule.reason_family_priority[:3]) == ["old_debt", "self_preserve", "blame_shift"]
        for rule in play_plan.semantic_strategy_pack.cost_narrative_binding_policy.by_segment_id.values()
    )
    assert all(
        int(rule.max_return_turns) == 3
        and bool(rule.require_visible_owner)
        and bool(rule.require_main_clause_subject)
        and bool(rule.require_two_sided_exchange)
        and int(rule.min_payer_loss) >= 1
        and int(rule.min_beneficiary_gain) >= 1
        and list(rule.main_clause_subject_order[:3]) == ["payer", "beneficiary", "blamed_party"]
        for rule in play_plan.semantic_strategy_pack.cost_visibility_contract.by_segment_id.values()
    )
    assert all(
        list(rule.eligible_segment_roles) == ["pressure", "reversal", "reveal", "terminal"]
        and int(rule.due_window_turns) == 3
        and rule.player_override_mode == "player_first"
        and int(rule.deferred_retry_bias) >= 0
        for rule in play_plan.semantic_strategy_pack.cost_primary_driver_policy_v7.by_segment_id.values()
    )
    assert play_plan.semantic_strategy_pack.cost_escalation_ladder_policy_v8.enabled is True
    assert all(
        int(rule.stage1_turn_offset) == 1
        and int(rule.stage2_turn_offset) >= int(rule.stage1_turn_offset)
        and int(rule.stage3_turn_offset) >= int(rule.stage2_turn_offset)
        and bool(rule.stage3_force_question_cost_focus)
        and bool(rule.stage3_force_primary_driver)
        for rule in play_plan.semantic_strategy_pack.cost_escalation_ladder_policy_v8.by_segment_id.values()
    )
    assert set(play_plan.semantic_strategy_pack.control_signature_policy_v8.by_action.keys()) == {"press", "redirect", "detonate"}
    assert all(
        rule.expected_route_kind in {"deferred_cost", "transferred_cost", "immediate_cost"}
        for rule in play_plan.semantic_strategy_pack.control_signature_policy_v8.by_action.values()
    )
    assert play_plan.semantic_strategy_pack.role_function_lexicon_policy_v8.by_segment_id
    assert all(
        rule.counter_entries and rule.crowd_entries
        for rule in play_plan.semantic_strategy_pack.role_function_lexicon_policy_v8.by_segment_id.values()
    )
    assert all(
        1 <= int(rule.max_return_turns) <= 3
        for rule in play_plan.semantic_strategy_pack.cost_return_policy.by_segment_id.values()
    )
    assert play_plan.semantic_strategy_pack.shell_signal_graph_v2.edges
    assert play_plan.semantic_strategy_pack.style_register.by_segment_role
    assert play_plan.semantic_strategy_pack.utility_weight_profile.intent_hit_weight >= 1
    assert play_plan.semantic_strategy_pack.cost_intensity_profile.segment_role_multiplier
    assert play_plan.semantic_strategy_pack.cost_intensity_profile.control_action_multiplier
    assert play_plan.semantic_strategy_pack.cost_intensity_profile.shell_multiplier
    assert play_plan.semantic_strategy_pack.shell_propagation_graph.shell_id == play_plan.story_shell_id
    assert play_plan.semantic_strategy_pack.shell_propagation_graph.edges
    assert play_plan.semantic_strategy_pack.propagation_priority_policy.edge_priority_by_segment_role
    assert play_plan.semantic_strategy_pack.invariant_policy.max_main_triggers_per_turn == 1
    assert play_plan.semantic_strategy_pack.invariant_policy.require_cost_return_within_window is True
    assert play_plan.semantic_strategy_pack.invariant_policy.require_cost_owner_visible is True
    assert play_plan.semantic_strategy_pack.invariant_policy.require_cost_linked_to_question is True
    assert play_plan.semantic_strategy_pack.causal_contract_policy.rules
    segment_ids = {segment.segment_id for segment in play_plan.segments}
    policy_segment_ids = set(play_plan.semantic_strategy_pack.segment_interest_policy.by_segment_id.keys())
    assert segment_ids <= policy_segment_ids


def test_compiled_play_plan_contains_initial_beat_delta_contract() -> None:
    result = run_author_play_graph(_accepted_blueprint())
    play_plan = result.play_plan

    assert play_plan.delta_pack_contract_version == 4
    assert play_plan.delta_kernel.template_id == play_plan.template_id
    assert play_plan.delta_kernel.story_shell_id == play_plan.story_shell_id
    assert play_plan.initial_beat_delta_pack.source == "author_initial"
    assert play_plan.initial_beat_delta_pack.segment_id == play_plan.segments[0].segment_id
    assert set(play_plan.initial_beat_delta_pack.move_priority_boosts).issubset(set(play_plan.segments[0].move_priorities))
    assert set(play_plan.initial_beat_delta_pack.lane_objective_bias_by_lane).issubset({"relationship", "side", "burst"})
    assert set(play_plan.initial_beat_delta_pack.lane_target_bias_by_lane).issubset({"relationship", "side", "burst"})
    assert set(play_plan.initial_beat_delta_pack.voice_atom_weight_bias_by_character).issubset(
        {member.character_id for member in play_plan.cast}
    )
    assert play_plan.initial_beat_delta_pack.normal_turn_card.directive
    assert play_plan.initial_beat_delta_pack.burst_turn_card.directive
    assert play_plan.initial_beat_delta_pack.compose_payload_hint_bundle.key_cues
    assert play_plan.initial_beat_delta_pack.micro_sim_hint_bundle.summary
    payload = play_plan.initial_beat_delta_pack.model_dump(mode="json")
    assert "allowed_move_families" not in payload
    assert "focus_target_ids" not in payload
    assert "rival_target_ids" not in payload
    assert "allocated_secret_ids" not in payload


def test_compile_play_plan_applies_semantic_autotune_patch(monkeypatch) -> None:
    baseline_plan = run_author_play_graph(_accepted_blueprint()).play_plan
    baseline_pack = baseline_plan.semantic_strategy_pack

    monkeypatch.setattr(
        "rpg_backend.author_v2.workflow._load_semantic_autotune_patch",
        lambda: {
            "recommended_overrides": {
                "utility_weight_profile": {
                    "intent_hit_weight_delta": 1,
                },
                "cost_intensity_profile": {
                    "latent_pressure_step_bonus_delta": 0.03,
                    "payoff_family_multiplier_delta": {"status_loss": 0.1},
                },
                "causal_contract_policy": {
                    "stale_pending_turns_threshold_delta": -1,
                },
            },
        },
    )
    patched_plan = run_author_play_graph(_accepted_blueprint()).play_plan
    patched_pack = patched_plan.semantic_strategy_pack

    assert patched_pack.utility_weight_profile.intent_hit_weight == baseline_pack.utility_weight_profile.intent_hit_weight + 1
    assert patched_pack.cost_intensity_profile.latent_pressure_step_bonus > baseline_pack.cost_intensity_profile.latent_pressure_step_bonus
    assert (
        patched_pack.cost_intensity_profile.payoff_family_multiplier["status_loss"]
        > baseline_pack.cost_intensity_profile.payoff_family_multiplier["status_loss"]
    )
    assert (
        patched_pack.causal_contract_policy.stale_pending_turns_threshold
        <= baseline_pack.causal_contract_policy.stale_pending_turns_threshold
    )


def test_segment_playbook_payload_uses_delta_contract_and_base_excerpt(monkeypatch) -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    contract = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )["segment_contracts"][0]
    local_cast = [
        member
        for member in bound_cast
        if member.character_id in set(contract.focus_target_ids + contract.rival_target_ids) or member.is_route_target
    ][:3] or bound_cast[:3]
    captured: dict[str, object] = {}

    class _CaptureGateway(_DynamicFakeGateway):
        def invoke_json(self, *, system_prompt, user_payload, max_output_tokens, operation_name, response_format_type=None):  # noqa: ANN001
            if operation_name == "author_v2.segment_playbook":
                captured.update(user_payload)
            return super().invoke_json(
                system_prompt=system_prompt,
                user_payload=user_payload,
                max_output_tokens=max_output_tokens,
                operation_name=operation_name,
                response_format_type=response_format_type,
            )

    gateway = _CaptureGateway()
    monkeypatch.setattr(
        "rpg_backend.author_v2.workflow._resolve_live_gateway",
        lambda live_mode, gateway_override: [("live_gpt_5_4_mini", gateway)],
    )

    _compile_segment_with_mode(
        blueprint=blueprint,
        contract=contract,
        bound_cast=local_cast,
        live_mode="live_gpt_5_4_mini",
    )

    assert captured["playbook_base"]
    assert captured["allowed_move_families"]
    assert captured["segment_contract_summary"]
    assert float(captured["control_contract_hint_weight"]) == pytest.approx(1.0, abs=1e-4)
    control_contract_reference = captured.get("control_contract_reference")
    assert isinstance(control_contract_reference, dict)
    assert all(
        key in control_contract_reference
        for key in ("must_yield_side", "yield_cost", "refuse_escalation", "settlement_window", "observable_evidence")
    )
    assert "template_tone_example_lines" not in captured
    assert "template_tone_scene_examples" not in captured


def test_segment_playbook_delta_sanitizer_truncates_render_cues_overflow(monkeypatch) -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    contract = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )["segment_contracts"][0]
    local_cast = [
        member
        for member in bound_cast
        if member.character_id in set(contract.focus_target_ids + contract.rival_target_ids) or member.is_route_target
    ][:3] or bound_cast[:3]

    class _CueOverflowGateway(_DynamicFakeGateway):
        def invoke_json(self, *, system_prompt, user_payload, max_output_tokens, operation_name, response_format_type=None):  # noqa: ANN001
            if operation_name == "author_v2.segment_playbook":
                playbook = dict(user_payload["playbook_base"])
                return SimpleNamespace(
                    payload={
                        "scene_goal": playbook["scene_goal"],
                        "emotional_goal": playbook["emotional_goal"],
                        "render_cues": [f"style:cue:{idx}" for idx in range(8)],
                        "terminal_pressure": "extra_field_should_be_dropped",
                    }
                )
            return super().invoke_json(
                system_prompt=system_prompt,
                user_payload=user_payload,
                max_output_tokens=max_output_tokens,
                operation_name=operation_name,
                response_format_type=response_format_type,
            )

    gateway = _CueOverflowGateway()
    monkeypatch.setattr(
        "rpg_backend.author_v2.workflow._resolve_live_gateway",
        lambda live_mode, gateway_override: [("live_gpt_5_4_mini", gateway)],
    )

    playbook, _trace, reasons, live_success, _metrics = _compile_segment_with_mode(
        blueprint=blueprint,
        contract=contract,
        bound_cast=local_cast,
        live_mode="live_gpt_5_4_mini",
    )

    assert live_success is True
    assert reasons == []
    assert len(playbook.render_cues) == 5


def test_segment_playbook_missing_scene_goal_uses_deterministic_base(monkeypatch) -> None:
    blueprint = _accepted_blueprint()
    cast_slots = plan_cast_slots({"accepted_blueprint": blueprint, "quality_trace": []})["cast_slots"]
    bound_cast = bind_slots_to_ip_cast(cast_slots, blueprint)
    contract = allocate_segment_contracts(
        {
            "accepted_blueprint": blueprint,
            "arc_template_id": "standard_4",
            "bound_cast": bound_cast,
            "quality_trace": [],
        }
    )["segment_contracts"][0]
    local_cast = [
        member
        for member in bound_cast
        if member.character_id in set(contract.focus_target_ids + contract.rival_target_ids) or member.is_route_target
    ][:3] or bound_cast[:3]

    class _MissingSceneGoalGateway(_DynamicFakeGateway):
        def invoke_json(self, *, system_prompt, user_payload, max_output_tokens, operation_name, response_format_type=None):  # noqa: ANN001
            if operation_name == "author_v2.segment_playbook":
                playbook = dict(user_payload["playbook_base"])
                return SimpleNamespace(
                    payload={
                        "emotional_goal": playbook["emotional_goal"],
                        "render_cues": list(playbook["render_cues"][:2]),
                    }
                )
            return super().invoke_json(
                system_prompt=system_prompt,
                user_payload=user_payload,
                max_output_tokens=max_output_tokens,
                operation_name=operation_name,
                response_format_type=response_format_type,
            )

    gateway = _MissingSceneGoalGateway()
    monkeypatch.setattr(
        "rpg_backend.author_v2.workflow._resolve_live_gateway",
        lambda live_mode, gateway_override: [("live_gpt_5_4_mini", gateway)],
    )

    deterministic_playbook = _compile_single_segment(blueprint=blueprint, contract=contract, bound_cast=local_cast)
    playbook, _trace, reasons, live_success, _metrics = _compile_segment_with_mode(
        blueprint=blueprint,
        contract=contract,
        bound_cast=local_cast,
        live_mode="live_gpt_5_4_mini",
    )

    assert live_success is True
    assert reasons == []
    assert playbook.scene_goal == deterministic_playbook.scene_goal


def test_seed_preservation_gate_passes_hero_case_and_detects_collapse_pair() -> None:
    seed = "豪门订婚宴上，最体面的未婚夫、突然回来的旧爱和握着遗嘱录音的律师同时逼她站队。"
    preview_a, _ = run_preview_blueprint_graph(seed, live_mode="deterministic")
    accepted_a = apply_blueprint_edits(preview_a)
    pipeline_a = run_author_play_graph(accepted_a, live_mode="deterministic")
    package_a = RelationshipDramaV2Package(
        preview_blueprint=preview_a,
        accepted_blueprint=accepted_a,
        urban_bundle=pipeline_a.bundle,
        compiled_play_plan=pipeline_a.play_plan,
        quality_trace=list(pipeline_a.state.get("quality_trace") or []),
        llm_call_trace=list(pipeline_a.state.get("llm_call_trace") or []),
    )

    preview_b, _ = run_preview_blueprint_graph(seed, live_mode="deterministic")
    accepted_b = apply_blueprint_edits(preview_b)
    pipeline_b = run_author_play_graph(accepted_b, live_mode="deterministic")
    package_b = RelationshipDramaV2Package(
        preview_blueprint=preview_b,
        accepted_blueprint=accepted_b,
        urban_bundle=pipeline_b.bundle,
        compiled_play_plan=pipeline_b.play_plan,
        quality_trace=list(pipeline_b.state.get("quality_trace") or []),
        llm_call_trace=list(pipeline_b.state.get("llm_call_trace") or []),
    )

    assert evaluate_seed_preservation_gate(package_a) == []
    divergence = evaluate_sibling_divergence_gate([package_a, package_b])
    assert divergence


def test_surface_signal_readability_gate_passes_deterministic_package() -> None:
    seed = "豪门订婚宴上，最体面的未婚夫、突然回来的旧爱和握着遗嘱录音的律师同时逼她站队。"
    preview, _ = run_preview_blueprint_graph(seed, live_mode="deterministic")
    accepted = apply_blueprint_edits(preview)
    pipeline = run_author_play_graph(accepted, live_mode="deterministic")
    package = RelationshipDramaV2Package(
        preview_blueprint=preview,
        accepted_blueprint=accepted,
        urban_bundle=pipeline.bundle,
        compiled_play_plan=pipeline.play_plan,
        quality_trace=list(pipeline.state.get("quality_trace") or []),
        llm_call_trace=list(pipeline.state.get("llm_call_trace") or []),
    )

    assert evaluate_surface_signal_readability(package) == []


def test_surface_signal_readability_gate_flags_flat_segments() -> None:
    seed = "董事会前夜，项目负责人被上司、对手和法务一起拖进并购黑账与暧昧站队里。"
    preview, _ = run_preview_blueprint_graph(seed, live_mode="deterministic")
    accepted = apply_blueprint_edits(preview)
    pipeline = run_author_play_graph(accepted, live_mode="deterministic")
    package = RelationshipDramaV2Package(
        preview_blueprint=preview,
        accepted_blueprint=accepted,
        urban_bundle=pipeline.bundle,
        compiled_play_plan=pipeline.play_plan,
        quality_trace=list(pipeline.state.get("quality_trace") or []),
        llm_call_trace=list(pipeline.state.get("llm_call_trace") or []),
    )
    flattened_segments = [
        segment.model_copy(
            update={
                "scene_goal": "关系继续推进。",
                "emotional_goal": "情绪继续波动。",
                "public_pressure_cue": "场面有点紧张。",
                "private_pressure_cue": "私下气氛微妙。",
                "progression_rule_summary": "继续观察变化。",
                "render_cues": ["style:segment:generic", "style:cadence:tight"],
            }
        )
        for segment in package.compiled_play_plan.segments
    ]
    degraded_plan = package.compiled_play_plan.model_copy(update={"segments": flattened_segments})
    degraded_package = package.model_copy(update={"compiled_play_plan": degraded_plan})

    failures = evaluate_surface_signal_readability(degraded_package)
    assert "surface_signal_triplet_missing" in failures
    assert "public_cost_visibility_missing" in failures
    assert "relationship_backlash_missing" in failures


def test_preview_pure_gpt_retries_provider_failures_without_downgrade(monkeypatch) -> None:
    class _ProviderFailure(RuntimeError):
        code = "llm_provider_failed"

    class _RetryGateway(_DynamicFakeGateway):
        def __init__(self, profile_id: str = "live_gpt_5_4_mini") -> None:
            super().__init__(profile_id=profile_id)
            self.attempts = 0

        def invoke_json(self, **kwargs):  # noqa: ANN003, ANN201
            self.attempts += 1
            if self.attempts < 3:
                raise _ProviderFailure("provider down")
            return super().invoke_json(**kwargs)

    monkeypatch.setattr("rpg_backend.author_v2.preview.get_author_v2_llm_gateway", lambda _mode: _RetryGateway())

    preview, state = run_preview_blueprint_graph(
        "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。",
        live_mode="pure_gpt",
    )

    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")
    assert preview.bomb_moment
    assert synth_record["actual_mode"] == "live_gpt_5_4_mini"
    assert synth_record["used_live_output"] is True
    assert synth_record["live_attempt_count"] == 3
    assert synth_record["provider_failure_count"] == 2
    assert "fallback_chain_used:live_qwen3_5_flash" not in synth_record["reasons"]


def test_preview_mainline_live_downgrades_after_gpt_retries(monkeypatch) -> None:
    class _ProviderFailure(RuntimeError):
        code = "llm_provider_failed"

    class _AlwaysFailGateway(_DynamicFakeGateway):
        def invoke_json(self, **kwargs):  # noqa: ANN003, ANN201
            raise _ProviderFailure("provider down")

    def _gateway_for_mode(mode: str):  # noqa: ANN001, ANN202
        if mode == "live_gpt_5_4_mini":
            return _AlwaysFailGateway(profile_id=mode)
        if mode == "live_qwen3_5_flash":
            return _DynamicFakeGateway(profile_id=mode)
        raise AssertionError(f"unexpected mode {mode}")

    monkeypatch.setattr("rpg_backend.author_v2.preview.get_author_v2_llm_gateway", _gateway_for_mode)

    _preview, state = run_preview_blueprint_graph(
        "豪门订婚宴上，未婚夫、旧爱和律师一起逼她在众目睽睽下选边。",
        live_mode="mainline_live",
    )
    synth_record = next(record for record in state["quality_trace"] if record["stage"] == "synthesize_preview_blueprint")

    assert synth_record["source"] == "live_qwen3_5_flash"
    assert synth_record["actual_mode"] == "live_qwen3_5_flash"
    assert synth_record["used_live_output"] is True
    assert synth_record["live_attempt_count"] == 2
    assert synth_record["provider_failure_count"] == 1
    assert "live_gpt_5_4_mini:llm_provider_failed" in synth_record["reasons"]


def test_author_v2_qwen_gateway_defaults_to_json_mode() -> None:
    recorded: dict[str, object] = {}

    def _fake_invoke_json(self, **kwargs):  # noqa: ANN001, ANN202
        recorded.update(kwargs)
        return SimpleNamespace(payload={"ok": True}, response_id="resp_demo", usage={}, input_characters=10)

    gateway = AuthorV2LLMGateway(
        client=SimpleNamespace(responses=SimpleNamespace(create=None)),
        model="qwen3.5-flash",
        profile_id="live_qwen3_5_flash",
        timeout_seconds=45.0,
        max_output_tokens_preview=800,
        max_output_tokens_cast_slots=800,
        max_output_tokens_segment_allocation=1500,
        max_output_tokens_segment_playbook=1600,
    )

    from unittest.mock import patch

    with patch("rpg_backend.author_v2.gateway.ResponsesJSONTransport.invoke_json", _fake_invoke_json):
        gateway.invoke_json(
            system_prompt="Return JSON.",
            user_payload={"demo": True},
            max_output_tokens=32,
            operation_name="author_v2.preview_synthesis",
        )

    assert recorded["response_format_type"] == "json_object"


def test_author_v2_gpt_gateway_defaults_to_json_mode() -> None:
    recorded: dict[str, object] = {}

    def _fake_invoke_json(self, **kwargs):  # noqa: ANN001, ANN202
        recorded.update(kwargs)
        return SimpleNamespace(payload={"ok": True}, response_id="resp_demo", usage={}, input_characters=10)

    gateway = AuthorV2LLMGateway(
        client=SimpleNamespace(responses=SimpleNamespace(create=None)),
        model="gpt-5.4-mini",
        profile_id="live_gpt_5_4_mini",
        timeout_seconds=45.0,
        max_output_tokens_preview=800,
        max_output_tokens_cast_slots=800,
        max_output_tokens_segment_allocation=1500,
        max_output_tokens_segment_playbook=1600,
    )

    from unittest.mock import patch

    with patch("rpg_backend.author_v2.gateway.ResponsesJSONTransport.invoke_json", _fake_invoke_json):
        gateway.invoke_json(
            system_prompt="Return JSON.",
            user_payload={"demo": True},
            max_output_tokens=32,
            operation_name="author_v2.preview_synthesis",
        )

    assert recorded["response_format_type"] == "json_object"


def test_author_v2_qwen_gateway_uses_dedicated_timeout(monkeypatch) -> None:
    monkeypatch.setattr("rpg_backend.author_v2.gateway.build_openai_client", lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(create=None)))
    settings = Settings(
        responses_base_url="https://generic.example/v1",
        responses_api_key="generic-key",
        responses_author_base_url="https://author.example/v1",
        responses_author_api_key="author-key",
        responses_timeout_seconds=20.0,
        responses_timeout_seconds_author_v2_qwen=45.0,
    )

    qwen_gateway = get_author_v2_llm_gateway("live_qwen3_5_flash", settings=settings)
    gpt_gateway = get_author_v2_llm_gateway("live_gpt_5_4_mini", settings=settings)

    assert qwen_gateway.timeout_seconds == 45.0
    assert gpt_gateway.timeout_seconds == 20.0


def test_author_v2_qwen_gateway_applies_rpm_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_build_openai_client(**kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return SimpleNamespace(responses=SimpleNamespace(create=None))

    monkeypatch.setattr("rpg_backend.author_v2.gateway.build_openai_client", _fake_build_openai_client)
    settings = Settings(
        responses_author_base_url="https://author.example/v1",
        responses_author_api_key="author-key",
        responses_author_qwen_requests_per_minute=500,
    )

    _ = get_author_v2_llm_gateway("live_qwen3_5_flash", settings=settings)

    assert captured["requests_per_minute"] == 500
    assert captured["rate_limit_scope"] == "author_v2:qwen"
