from rpg_backend.author_v2.contracts import CompiledPlayPlan
from rpg_backend.author_v3.workflow import run_author_v3_pipeline


def test_compiled_plan_roundtrip() -> None:
    result = run_author_v3_pipeline("test seed", run_mode="deterministic")
    plan = result["plan"]

    assert plan.semantic_strategy_pack.role_divergence_matrix.default_crowd_reason_priority
    assert plan.semantic_strategy_pack.supporting_divergence_policy.key_segment_required_pairs

    dumped = plan.model_dump(mode="json")
    reloaded = CompiledPlayPlan.model_validate(dumped)

    assert reloaded.author_version == "v3"
    assert reloaded.delta_pack_contract_version == 5
    assert reloaded.semantic_strategy_pack.role_divergence_matrix.default_crowd_reason_priority
    assert reloaded.semantic_strategy_pack.supporting_divergence_policy.key_segment_required_pairs
