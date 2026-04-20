from __future__ import annotations

import json
import shutil
from pathlib import Path

from tools.urban_author_play_benchmarks.gold_set import v1_topic_gold_14
from tools.urban_author_play_benchmarks.play_eval_recompute_runner import recompute_v1_topic_play_eval
from tools.urban_author_play_benchmarks.runner import run_case
from tools.urban_author_play_benchmarks.self_play_runner import run_self_play_pilot


def test_recompute_v1_topic_play_eval_rewrites_mainline_artifacts(tmp_path) -> None:
    case = v1_topic_gold_14()[0]
    source = tmp_path / "source"
    run_case(case, source / "benchmark", mode="deterministic")
    source_artifacts = source / "benchmark" / "smoke" / case.case_id / "deterministic"
    deep_play = run_self_play_pilot(
        source / "deep",
        case_id=case.case_id,
        case_catalog=[case],
        live_mode="deterministic",
        execution_mode="sequential",
        source_artifacts_dir=source_artifacts,
        enable_turn_play_eval=True,
        enable_session_play_eval=True,
    )
    deep_play_dir = Path(deep_play["artifacts_dir"])

    root = tmp_path / "eval"
    variant_root = root / "npc_texture_v2"
    case_root = variant_root / "deep_play" / "self_play" / case.case_id / "live_qwen3_5_flash"
    case_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(deep_play_dir, case_root)
    (variant_root / "author_summary.json").write_text(
        json.dumps(
            {
                "config": {"play_v2_narration_profile": "npc_texture_v2"},
                "benchmark_results": [],
                "cases": [
                    {
                        "case_id": case.case_id,
                        "shell": case.expected_shell,
                        "template_id": case.expected_template_id,
                        "passed": True,
                        "content_score": 1.0,
                        "live_depth_score": 0,
                        "failure_category": None,
                        "seed_preservation_failures": [],
                        "sibling_divergence_flags": [],
                    }
                ],
                "failing_assertions": {},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    (variant_root / "token_usage_summary.json").write_text(json.dumps({"per_stage": {}}, ensure_ascii=False, indent=2))

    result = recompute_v1_topic_play_eval(root, case_catalog=[case], max_workers=2)

    assert Path(result["artifacts_dir"]) == root
    assert (root / "npc_texture_v2" / "play_eval_summary.json").exists()
    assert (root / "play_eval_ab_summary.json").exists()
    assert (root / "play_eval_effect_report.md").exists()
