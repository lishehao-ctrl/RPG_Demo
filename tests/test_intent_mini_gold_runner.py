from __future__ import annotations

import json

from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph
from tools.urban_author_play_benchmarks.intent_mini_gold_runner import run_intent_mini_gold


def _compiled_plan_payload(seed: str) -> dict:
    preview, _ = run_preview_blueprint_graph(seed)
    accepted = apply_blueprint_edits(preview)
    return run_author_play_graph(accepted).play_plan.model_dump(mode="json")


def test_intent_mini_gold_runner_writes_latency_and_token_summary(tmp_path) -> None:
    plans_root = tmp_path / "plans"
    case_id = "campus_topic_homecoming_recording"
    plan_dir = plans_root / case_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    compiled_plan = _compiled_plan_payload("校庆晚会前，旧录音和前任回归把她逼进公开站队。做成标准都市关系戏。")
    (plan_dir / "compiled_play_plan.json").write_text(json.dumps(compiled_plan, ensure_ascii=False))

    output_dir = tmp_path / "report"
    summary = run_intent_mini_gold(
        plans_root=plans_root,
        output_dir=output_dir,
        case_ids=[case_id],
        enable_intent_llm=False,
        enable_micro_sim_llm=False,
    )

    assert summary["case_count"] == 1
    assert summary["sample_count"] >= 4
    assert 0.0 <= float(summary["check_pass_rate"]) <= 1.0
    assert "check_scores" in summary
    assert "intent_compile_source_distribution" in summary
    assert "control_source_distribution" in summary
    assert "intent_llm_status_distribution" in summary
    assert "micro_sim_status_distribution" in summary
    assert 0.0 <= float(summary["check_scores"]["intent_stage_latency_recorded"]) <= 1.0
    assert float(summary["latency_ms"]["intent_stage_median"]) >= 0.0
    assert float(summary["latency_ms"]["intent_stage_p90"]) >= 0.0
    assert int(summary["tokens"]["intent_stage_total_sum"]) >= 0
    assert float(summary["tokens"]["intent_stage_total_median"]) >= 0.0
    assert float(summary["tokens"]["intent_stage_total_p90"]) >= 0.0
    assert (output_dir / "intent_mini_gold_summary.json").exists()
    assert (output_dir / "intent_mini_gold_report.md").exists()
