from __future__ import annotations

import pytest

from rpg_backend.author_v2.contracts import BoundIPCastMember, CompiledPlayPlan, CompiledSegment
from rpg_backend.author_v3.quality_evaluator import QualityReport
from rpg_backend.author_v3.workflow import run_author_v3_pipeline


@pytest.fixture
def pipeline_result() -> dict:
    return run_author_v3_pipeline("董事会权力斗争", run_mode="deterministic")


@pytest.fixture
def plan(pipeline_result: dict) -> CompiledPlayPlan:
    return pipeline_result["plan"]


class TestDeterministicPipeline:
    def test_returns_dict_with_plan(self, pipeline_result: dict) -> None:
        assert "plan" in pipeline_result

    def test_plan_is_compiled_play_plan(self, plan: CompiledPlayPlan) -> None:
        assert isinstance(plan, CompiledPlayPlan)

    def test_plan_version_is_v5(self, plan: CompiledPlayPlan) -> None:
        assert plan.delta_pack_contract_version == 5

    def test_plan_semantic_version_is_v9(self, plan: CompiledPlayPlan) -> None:
        assert plan.semantic_strategy_version == 9

    def test_plan_author_version_is_v3(self, plan: CompiledPlayPlan) -> None:
        assert plan.author_version == "v3"

    def test_plan_has_cast_members(self, plan: CompiledPlayPlan) -> None:
        assert len(plan.cast) == 5

    def test_plan_cast_are_bound_members(self, plan: CompiledPlayPlan) -> None:
        for member in plan.cast:
            assert isinstance(member, BoundIPCastMember)

    def test_plan_has_segments(self, plan: CompiledPlayPlan) -> None:
        assert len(plan.segments) >= 3

    def test_plan_segments_match_flagship_6(self, plan: CompiledPlayPlan) -> None:
        roles = [s.segment_role for s in plan.segments]
        assert roles == ["opening", "misread", "pressure", "reversal", "reveal", "terminal"]

    def test_plan_terminal_segment(self, plan: CompiledPlayPlan) -> None:
        assert plan.segments[-1].is_terminal is True

    def test_plan_cast_have_required_fields(self, plan: CompiledPlayPlan) -> None:
        for m in plan.cast:
            assert m.slot_function
            assert m.display_name
            assert m.portrait_asset
            assert m.drama_profile
            assert m.strategic_intent

    def test_plan_has_storylet_pool(self, plan: CompiledPlayPlan) -> None:
        assert plan.storylet_pool is not None
        assert plan.organic_secrets is not None and len(plan.organic_secrets) >= 2, f"Expected >=2 organic_secrets, got {plan.organic_secrets}"
        assert plan.hooks is not None and len(plan.hooks) >= 1, f"Expected >=1 hooks, got {plan.hooks}"

    def test_plan_segments_preserve_selected_storylet_payload(self, plan: CompiledPlayPlan) -> None:
        assert all(segment.source_storylet_id for segment in plan.segments)
        assert all(segment.source_storylet for segment in plan.segments)
        first_segment = plan.segments[0]
        source_storylet = dict(first_segment.source_storylet or {})
        assert source_storylet.get("storylet_id") == first_segment.source_storylet_id
        assert "preconditions" in source_storylet
        assert "effects" in source_storylet

    def test_plan_storylet_pool_keeps_selected_storylets(self, plan: CompiledPlayPlan) -> None:
        pool_storylet_ids = {
            str(item.get("storylet_id") or "").strip()
            for item in list(plan.storylet_pool or [])
            if isinstance(item, dict)
        }
        selected_storylet_ids = {
            str(segment.source_storylet_id or "").strip()
            for segment in plan.segments
            if str(segment.source_storylet_id or "").strip()
        }
        assert selected_storylet_ids
        assert selected_storylet_ids.issubset(pool_storylet_ids)

    def test_plan_has_ending_matrix(self, plan: CompiledPlayPlan) -> None:
        assert len(plan.ending_matrix.endings) >= 4

    def test_plan_has_route_targets(self, plan: CompiledPlayPlan) -> None:
        assert len(plan.route_target_ids) >= 2

    def test_plan_max_turns_reasonable(self, plan: CompiledPlayPlan) -> None:
        assert 8 <= plan.max_turns <= 56

    def test_plan_opening_narration(self, plan: CompiledPlayPlan) -> None:
        assert plan.opening_narration.strip()


class TestPipelineResults:
    def test_quality_report_present(self, pipeline_result: dict) -> None:
        assert "quality_report" in pipeline_result
        assert isinstance(pipeline_result["quality_report"], QualityReport)

    def test_quality_report_passed(self, pipeline_result: dict) -> None:
        assert pipeline_result["quality_report"].passed is True

    def test_world_config_present(self, pipeline_result: dict) -> None:
        assert "world_config" in pipeline_result

    def test_tension_web_present(self, pipeline_result: dict) -> None:
        assert "tension_web" in pipeline_result

    def test_storylet_pool_present(self, pipeline_result: dict) -> None:
        assert "storylet_pool" in pipeline_result


class TestArcVariants:
    def test_short_3_arc(self) -> None:
        result = run_author_v3_pipeline("test", run_mode="deterministic", arc_template_id="short_3")
        plan = result["plan"]
        assert len(plan.segments) == 3
        assert plan.segments[-1].is_terminal is True

    def test_compact_4_arc(self) -> None:
        result = run_author_v3_pipeline("test", run_mode="deterministic", arc_template_id="compact_4")
        plan = result["plan"]
        assert len(plan.segments) == 4
