from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import ValidationError

from rpg_backend.author_v2.product_package import RelationshipDramaV2Package
from rpg_backend.author_v2.quality_gates import evaluate_seed_preservation_gate
from rpg_backend.author_v2.contracts import UrbanPipelineResult
from rpg_backend.author_v2.gateway import AuthorV2RunMode
from rpg_backend.author_v2.preview import apply_blueprint_edits, run_preview_blueprint_graph
from rpg_backend.author_v2.workflow import run_author_play_graph, select_arc_template
from rpg_backend.config import get_settings
from rpg_backend.play_v2.runtime import run_smoke_playthrough
from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase, burst_pressure_set, mini_gold_set

BENCHMARK_MODES: tuple[AuthorV2RunMode, ...] = ("deterministic", "pure_gpt", "mainline_live")
SUPPORTED_BENCHMARK_MODES: tuple[AuthorV2RunMode, ...] = (
    "deterministic",
    "pure_gpt",
    "mainline_live",
    "live_priority",
    "live_qwen3_5_plus",
    "live_qwen3_5_flash",
    "live_gpt_5_4_mini",
)
LIVE_BENCHMARK_MODES: tuple[AuthorV2RunMode, ...] = ("pure_gpt", "mainline_live", "live_priority", "live_qwen3_5_plus", "live_qwen3_5_flash", "live_gpt_5_4_mini")
PLAY_LENGTH_PRESETS: tuple[str, ...] = ("5_8", "10_12", "12_15", "15_20", "20_25", "30_45")
AUTHOR_LIVE_STAGES: tuple[str, ...] = (
    "synthesize_preview_blueprint",
    "plan_cast_slots",
    "allocate_segment_contracts",
    "compile_segment_playbooks",
)
FORBIDDEN_CIVIC_TERMS = (
    "harbor",
    "council",
    "ledger",
    "civic",
    "archive",
    "coalition",
    "mandate",
    "public panic",
    "resource strain",
)
EXPLOSIVE_SECRET_TERMS = ("录音", "遗嘱", "黑账", "黑料", "绯闻", "录像", "偷拍视频", "契约", "旧案", "证据", "私生", "身份真相")
PUBLIC_FAILURE_TERMS = ("当众", "公开", "直播", "镜头", "家宴", "董事会", "发布会", "热搜")
SOCIAL_ARENA_TERMS = ("婚礼", "订婚", "家宴", "董事会", "发布会", "直播", "酒会", "晚会", "会所", "夜宴", "答辩")
ROUTE_TEMPTATION_TERMS = ("站谁", "护谁", "护住", "拆谁", "骗谁", "选谁", "选边", "逼谁", "逼那个", "先救谁", "翻盘", "失控前")
NO_RETURN_TERMS = ("说破", "回不去", "失控", "公开", "代价", "翻车")
NO_RETURN_STYLE_TERMS = (
    "style:public_drop:enabled",
    "style:bomb:public_drop",
    "style:cost:landed",
    "style:bomb:short_hard_drop",
    "style:choice:force_alignment",
)
MATERIAL_COST_TERMS = ("体面", "位置", "名声", "前途", "退路", "关系", "婚约", "资源")

STRUCTURE_ASSERTION_NAMES = {
    "shell_match",
    "template_match",
    "play_length_preset_match",
    "experience_band_match",
    "cast_count_within_target",
    "segment_allocation_coherent",
    "play_plan_caps_active_cast",
    "no_civic_domain_leakage",
}


def _resolve_author_v3_run_mode(mode: AuthorV2RunMode) -> str:
    if mode in {"mainline_live", "live_qwen3_5_plus", "live_qwen3_5_flash"}:
        return "live_gpt_5_4_mini"
    return mode


def _to_jsonable(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json")
    if isinstance(payload, list):
        return [_to_jsonable(item) for item in payload]
    if isinstance(payload, tuple):
        return [_to_jsonable(item) for item in payload]
    if isinstance(payload, dict):
        return {key: _to_jsonable(value) for key, value in payload.items()}
    return payload


def _write_json(path: Path, payload: Any) -> None:
    serializable = _to_jsonable(payload)
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2, sort_keys=True))


def _stage_quality_records(quality_trace: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(record.get("stage")): record
        for record in quality_trace
        if isinstance(record, dict) and str(record.get("stage")) in AUTHOR_LIVE_STAGES
    }


def _stage_mode_token(record: dict[str, Any] | None) -> str:
    if not record:
        return "deterministic"
    actual_mode = str(record.get("actual_mode") or record.get("source") or "deterministic")
    actual_modes = [str(mode) for mode in list(record.get("actual_modes") or []) if str(mode)]
    if actual_mode == "mixed" and actual_modes:
        return "+".join(actual_modes)
    return actual_mode


def _live_depth_metrics(quality_trace: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage = _stage_quality_records(quality_trace)
    live_depth_score = sum(1 for stage in AUTHOR_LIVE_STAGES if bool(by_stage.get(stage, {}).get("used_live_output")))
    final_mode_path = "->".join(_stage_mode_token(by_stage.get(stage)) for stage in AUTHOR_LIVE_STAGES)
    return {
        "live_depth_score": live_depth_score,
        "final_mode_path": final_mode_path,
        "stage_live_attempt_count": {stage: int(by_stage.get(stage, {}).get("live_attempt_count", 0)) for stage in AUTHOR_LIVE_STAGES},
        "stage_live_success_count": {stage: int(by_stage.get(stage, {}).get("live_success_count", 0)) for stage in AUTHOR_LIVE_STAGES},
        "stage_provider_failure_count": {stage: int(by_stage.get(stage, {}).get("provider_failure_count", 0)) for stage in AUTHOR_LIVE_STAGES},
    }


def _classify_failure(stage: str, error: Exception | None = None) -> str:
    if isinstance(error, ValidationError):
        return "schema invalid"
    if error is not None and "prompt" in str(error).casefold():
        return "prompt overload"
    if stage == "allocate_segment_contracts":
        return "allocation drift"
    if stage == "compile_segment_playbooks":
        return "segment incoherence"
    if stage == "bind_ip_cast":
        return "IP binding mismatch"
    if stage in {"play_runtime", "smoke_playthrough"}:
        return "play-state incoherence"
    return "schema invalid"


def _evaluate_assertions(case: UrbanGoldCase, artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    preview = artifacts["preview_blueprint"]
    bundle = artifacts["urban_bundle"]
    play_plan = artifacts["compiled_play_plan"]
    smoke_results = artifacts["smoke_results"]
    bundle_text = " ".join(
        [
            preview.hook,
            preview.route_promise,
            preview.bomb_moment,
            preview.cost_of_truth,
            bundle.opening_narration,
            " ".join(member.charisma_hook for member in play_plan.cast),
            " ".join(member.danger_hook for member in play_plan.cast),
            " ".join(
                " ".join([segment.scene_goal, segment.emotional_goal, segment.progression_rule_summary, *segment.render_cues])
                for segment in play_plan.segments
            ),
            " ".join(ending.summary for ending in play_plan.ending_matrix.endings),
        ]
    ).casefold()
    route_targets = [member for member in play_plan.cast if member.is_route_target]
    reveal_or_terminal_text = " ".join(
        [
            segment.scene_goal + " " + segment.emotional_goal
            for segment in play_plan.segments
            if segment.segment_role in {"reveal", "terminal"}
        ]
    )
    reveal_or_terminal_style = {
        cue
        for segment in play_plan.segments
        if segment.segment_role in {"reveal", "terminal"}
        for cue in segment.render_cues
    }
    route_target_risk = all(
        bool(member.charisma_hook.strip()) and bool(member.danger_hook.strip())
        for member in route_targets[: max(2, len(route_targets[:2]))]
    )
    assertions = [
        {"name": "worldly_desire_explicit", "category": "content", "passed": bool(preview.worldly_desire_type), "reason": "worldly desire missing"},
        {"name": "public_social_arena_exists", "category": "content", "passed": len(preview.social_arena) >= 3 or any(term in preview.social_arena for term in SOCIAL_ARENA_TERMS), "reason": "social arena is too weak"},
        {"name": "taboo_secret_socially_explosive", "category": "content", "passed": any(term in preview.taboo_secret for term in EXPLOSIVE_SECRET_TERMS), "reason": "taboo secret lacks public explosiveness"},
        {"name": "bomb_moment_public_failure", "category": "content", "passed": any(term in preview.bomb_moment for term in PUBLIC_FAILURE_TERMS), "reason": "bomb moment is not a public failure scene"},
        {"name": "route_promise_has_temptation", "category": "content", "passed": any(term in preview.route_promise for term in ROUTE_TEMPTATION_TERMS), "reason": "route promise lacks choice temptation"},
        {"name": "route_targets_differentiated", "category": "content", "passed": len({member.danger_hook for member in route_targets[:2]}) >= min(2, len(route_targets[:2])), "reason": "route targets feel too similar"},
        {"name": "route_targets_have_charm_and_danger", "category": "content", "passed": route_target_risk, "reason": "route targets are missing charm or danger hooks"},
        {
            "name": "reveal_terminal_no_return",
            "category": "content",
            "passed": any(term in reveal_or_terminal_text for term in NO_RETURN_TERMS)
            or any(cue in NO_RETURN_STYLE_TERMS for cue in reveal_or_terminal_style),
            "reason": "reveal/terminal segments do not feel irreversible",
        },
        {"name": "cost_of_truth_materialized", "category": "content", "passed": any(term in preview.cost_of_truth for term in MATERIAL_COST_TERMS) and any(term in bundle.opening_narration + " ".join(ending.summary for ending in bundle.ending_matrix.endings) for term in MATERIAL_COST_TERMS), "reason": "cost of truth is not materialized enough"},
        {"name": "shell_match", "category": "structure", "passed": preview.story_shell_id == case.expected_shell, "reason": f"expected shell {case.expected_shell}, got {preview.story_shell_id}"},
        {
            "name": "template_match",
            "category": "structure",
            "passed": case.expected_template_id is None or play_plan.template_id == case.expected_template_id,
            "reason": (
                f"expected template {case.expected_template_id}, got {play_plan.template_id}"
                if case.expected_template_id is not None
                else "template not asserted"
            ),
        },
        {
            "name": "play_length_preset_match",
            "category": "structure",
            "passed": (
                case.expected_play_length_preset is None
                or preview.play_length_preset == case.expected_play_length_preset
            ),
            "reason": (
                f"expected play_length_preset {case.expected_play_length_preset}, got {preview.play_length_preset}"
                if case.expected_play_length_preset is not None
                else "play length preset not asserted"
            ),
        },
        {"name": "experience_band_match", "category": "structure", "passed": preview.experience_band == case.expected_band, "reason": f"expected band {case.expected_band}, got {preview.experience_band}"},
        {"name": "cast_count_within_target", "category": "structure", "passed": case.min_cast <= len(play_plan.cast) <= case.max_cast, "reason": f"cast count {len(play_plan.cast)} not in target band"},
        {"name": "segment_allocation_coherent", "category": "structure", "passed": sum(1 for segment in play_plan.segments if segment.is_terminal) == 1 and len({segment.segment_id for segment in play_plan.segments}) == len(play_plan.segments), "reason": "segment allocation is incoherent"},
        {"name": "play_plan_caps_active_cast", "category": "structure", "passed": all(segment.scene_active_cap <= 3 for segment in play_plan.segments) and all(len(result.state.active_character_ids) <= 3 for result in smoke_results), "reason": "scene-active cast exceeded cap"},
        {"name": "no_civic_domain_leakage", "category": "structure", "passed": not any(term in bundle_text for term in FORBIDDEN_CIVIC_TERMS), "reason": "civic-domain leakage detected"},
    ]
    return assertions


def _score_assertions(assertions: list[dict[str, Any]], *, category: str) -> dict[str, Any]:
    selected = [assertion for assertion in assertions if assertion["category"] == category]
    total = len(selected)
    passed = sum(1 for assertion in selected if assertion["passed"])
    return {
        "passed": passed,
        "total": total,
        "score": round(passed / total, 4) if total else 0.0,
    }


def _write_failure_report(
    *,
    case_dir: Path,
    case: UrbanGoldCase,
    stage: str,
    category: str,
    detail: str,
    assertions: list[dict[str, Any]] | None = None,
) -> None:
    lines = [
        f"# Failure Report: {case.case_id}",
        "",
        f"- stage: `{stage}`",
        f"- category: `{category}`",
        f"- detail: {detail}",
    ]
    if assertions:
        lines.append("")
        lines.append("## Failed Assertions")
        for assertion in assertions:
            if not assertion["passed"]:
                lines.append(f"- `{assertion['name']}`: {assertion['reason']}")
    (case_dir / "failure_report.md").write_text("\n".join(lines))


def _apply_sibling_divergence_flags(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        shell = str(result.get("shell_id") or "")
        template_id = str(result.get("template_id") or "")
        if shell and template_id:
            grouped[(shell, template_id)].append(result)
    for (_, _), grouped_results in grouped.items():
        signatures = Counter(
            (
                str(result.get("route_promise_signature") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("arena_type") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("secret_class") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("cost_class") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("public_bomb_family") or ""),
            )
            for result in grouped_results
        )
        for result in grouped_results:
            signature = (
                str(result.get("route_promise_signature") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("arena_type") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("secret_class") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("cost_class") or ""),
                str(dict(result.get("seed_fingerprint_summary") or {}).get("public_bomb_family") or ""),
            )
            result["sibling_divergence_flags"] = ["seed_collapse"] if signatures[signature] > 1 else []
    return results


def run_case(
    case: UrbanGoldCase,
    output_dir: Path,
    *,
    mode: AuthorV2RunMode,
    suite_name: str = "smoke",
    run_label: str | None = None,
    play_length_preset: str | None = None,
) -> dict[str, Any]:
    base_case_dir = output_dir / suite_name / case.case_id / mode
    case_dir = base_case_dir / run_label if run_label else base_case_dir
    case_dir.mkdir(parents=True, exist_ok=True)
    _write_json(case_dir / "seed.json", case)
    quality_trace: list[dict[str, Any]] = []
    llm_call_trace: list[dict[str, Any]] = []
    stage = "preview_blueprint_graph"
    try:
        preview, preview_state = run_preview_blueprint_graph(case.seed, live_mode=mode)
        _write_json(case_dir / "preview_blueprint.json", preview)
        quality_trace.extend(preview_state.get("quality_trace", []))
        llm_call_trace.extend(preview_state.get("llm_call_trace", []))

        stage = "accepted_blueprint"
        accepted = apply_blueprint_edits(
            preview,
            {"play_length_preset": play_length_preset} if play_length_preset is not None else None,
        )
        _write_json(case_dir / "accepted_blueprint.json", accepted)

        settings = get_settings()
        stage = "author_play_graph"
        if settings.author_v3_enabled:
            from rpg_backend.author_v3.plan_bridge import package_from_v3_pipeline
            from rpg_backend.author_v3.workflow import run_author_v3_pipeline

            v3_result = run_author_v3_pipeline(
                case.seed,
                run_mode=_resolve_author_v3_run_mode(mode),
                settings=settings,
                arc_template_id=select_arc_template(accepted),
            )
            quality_report = v3_result["quality_report"]
            package = package_from_v3_pipeline(
                preview_blueprint=preview,
                accepted_blueprint=accepted,
                plan=v3_result["plan"],
            )
            quality_trace_v3 = list(package.quality_trace)
            quality_trace_v3.append({
                "stage": "author_v3_quality_report",
                "source": "author_v3",
                "outcome": "accepted" if quality_report.passed else "failed",
                "overall_score": quality_report.overall_score,
                "weakest_dimension": quality_report.weakest_dimension,
            })
            result = UrbanPipelineResult(
                bundle=package.urban_bundle,
                play_plan=package.compiled_play_plan,
                state={"quality_trace": quality_trace_v3, "llm_call_trace": list(package.llm_call_trace)},
            )
        else:
            result = run_author_play_graph(accepted, live_mode=mode)
        _write_json(case_dir / "cast_slots.json", result.bundle.cast_slots)
        _write_json(case_dir / "bound_cast.json", result.bundle.bound_cast)
        _write_json(case_dir / "segment_contracts.json", result.bundle.segment_contracts)
        _write_json(case_dir / "segment_playbooks.json", result.bundle.segment_playbooks)
        _write_json(case_dir / "ending_matrix.json", result.bundle.ending_matrix)
        _write_json(case_dir / "urban_bundle.json", result.bundle)
        _write_json(case_dir / "compiled_play_plan.json", result.play_plan)
        quality_trace.extend(result.state.get("quality_trace", []))
        llm_call_trace.extend(result.state.get("llm_call_trace", []))

        stage = "smoke_playthrough"
        smoke_results = run_smoke_playthrough(result.play_plan)
        _write_json(case_dir / "llm_call_trace.json", llm_call_trace)
        _write_json(case_dir / "quality_trace.json", quality_trace)
        _write_json(case_dir / "smoke_results.json", smoke_results)

        artifacts = {
            "preview_blueprint": preview,
            "accepted_blueprint": accepted,
            "urban_bundle": result.bundle,
            "compiled_play_plan": result.play_plan,
            "smoke_results": smoke_results,
        }
        package = RelationshipDramaV2Package(
            preview_blueprint=preview,
            accepted_blueprint=accepted,
            urban_bundle=result.bundle,
            compiled_play_plan=result.play_plan,
            quality_trace=quality_trace,
            llm_call_trace=llm_call_trace,
        )
        seed_preservation_failures = evaluate_seed_preservation_gate(package)
        assertions = _evaluate_assertions(case, artifacts)
        structure_score = _score_assertions(assertions, category="structure")
        content_score = _score_assertions(assertions, category="content")
        structure_passed = all(
            assertion["passed"] for assertion in assertions if assertion["name"] in STRUCTURE_ASSERTION_NAMES
        )
        passed = all(assertion["passed"] for assertion in assertions)
        if not passed:
            _write_failure_report(
                case_dir=case_dir,
                case=case,
                stage="gold_assertions",
                category=_classify_failure("compile_segment_playbooks"),
                detail="One or more gold assertions failed.",
                assertions=assertions,
            )
        return {
            "case_id": case.case_id,
            "mode": mode,
            "passed": passed,
            "structure_passed": structure_passed,
            "stage": "completed" if passed else "gold_assertions",
            "failure_category": None if passed else _classify_failure("compile_segment_playbooks"),
            "assertions": assertions,
            "structure_score": structure_score["score"],
            "content_score": content_score["score"],
            "llm_call_count": len(llm_call_trace),
            "llm_call_trace": llm_call_trace,
            "quality_trace": quality_trace,
            "active_cast_cap_ok": all(segment.scene_active_cap <= 3 for segment in result.play_plan.segments),
            "play_length_preset": result.play_plan.play_length_preset,
            "arc_template_id": result.play_plan.arc_template_id,
            "template_id": result.play_plan.template_id,
            "expected_template_id": case.expected_template_id,
            "fit_mode": result.play_plan.fit_mode,
            "shell_id": result.play_plan.story_shell_id,
            "seed_fingerprint_summary": result.play_plan.seed_fingerprint.model_dump(mode="json"),
            "seed_preservation_failures": seed_preservation_failures,
            "route_promise_signature": preview.route_promise.split("，")[0],
            "segment_count": len(result.play_plan.segments),
            "progress_required_by_segment": [segment.progress_required for segment in result.play_plan.segments],
            "max_turns": result.play_plan.max_turns,
            "ending_id": smoke_results[-1].state.ending_id if smoke_results and smoke_results[-1].state.ending_id else None,
            **_live_depth_metrics(quality_trace),
        }
    except Exception as exc:  # noqa: BLE001
        _write_json(case_dir / "llm_call_trace.json", llm_call_trace)
        _write_json(case_dir / "quality_trace.json", quality_trace)
        category = _classify_failure(stage, exc)
        _write_failure_report(
            case_dir=case_dir,
            case=case,
            stage=stage,
            category=category,
            detail=str(exc),
        )
        return {
            "case_id": case.case_id,
            "mode": mode,
            "passed": False,
            "structure_passed": False,
            "stage": stage,
            "failure_category": category,
            "assertions": [],
            "structure_score": 0.0,
            "content_score": 0.0,
            "llm_call_count": len(llm_call_trace),
            "llm_call_trace": llm_call_trace,
            "quality_trace": quality_trace,
            "expected_template_id": case.expected_template_id,
            "play_length_preset": play_length_preset,
            **_live_depth_metrics(quality_trace),
        }


def _run_case_with_timeout(
    case: UrbanGoldCase,
    output_dir: Path,
    *,
    mode: AuthorV2RunMode,
    suite_name: str,
    run_label: str | None,
    play_length_preset: str | None,
    case_timeout_seconds: float | None,
) -> dict[str, Any]:
    if case_timeout_seconds is None or float(case_timeout_seconds) <= 0:
        return run_case(
            case,
            output_dir,
            mode=mode,
            suite_name=suite_name,
            run_label=run_label,
            play_length_preset=play_length_preset,
        )
    timeout_seconds = max(1.0, float(case_timeout_seconds))
    timeout_error = TimeoutError(f"case_timeout:{timeout_seconds:.1f}s")
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        run_case,
        case,
        output_dir,
        mode=mode,
        suite_name=suite_name,
        run_label=run_label,
        play_length_preset=play_length_preset,
    )
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        base_case_dir = output_dir / suite_name / case.case_id / mode
        case_dir = base_case_dir / run_label if run_label else base_case_dir
        case_dir.mkdir(parents=True, exist_ok=True)
        _write_failure_report(
            case_dir=case_dir,
            case=case,
            stage="play_runtime",
            category=_classify_failure("play_runtime", timeout_error),
            detail=f"case timed out after {timeout_seconds:.1f}s and was skipped",
        )
        return {
            "case_id": case.case_id,
            "mode": mode,
            "passed": False,
            "structure_passed": False,
            "stage": "play_runtime",
            "failure_category": _classify_failure("play_runtime", timeout_error),
            "assertions": [],
            "structure_score": 0.0,
            "content_score": 0.0,
            "llm_call_count": 0,
            "llm_call_trace": [],
            "quality_trace": [],
            "expected_template_id": case.expected_template_id,
            "play_length_preset": play_length_preset,
            **_live_depth_metrics([]),
        }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    results = _apply_sibling_divergence_flags(results)
    failure_stage_counter: Counter[str] = Counter()
    failure_category_counter: Counter[str] = Counter()
    assertion_counter: Counter[str] = Counter()
    fallback_counter: Counter[str] = Counter()
    retry_counter: Counter[int] = Counter()
    usage_totals: Counter[str] = Counter()
    durations: list[float] = []
    stage_live_attempt_count: Counter[str] = Counter()
    stage_live_success_count: Counter[str] = Counter()
    stage_provider_failure_count: Counter[str] = Counter()
    passed_cases = 0
    structure_passed_cases = 0
    content_scores: list[float] = []
    structure_scores: list[float] = []
    live_depth_scores: list[float] = []
    content_failure_case_count = 0
    provider_hit_depth_case_count = 0
    for result in results:
        if result["passed"]:
            passed_cases += 1
        else:
            failure_stage_counter[result["stage"]] += 1
            if result.get("failure_category"):
                failure_category_counter[result["failure_category"]] += 1
            if result.get("stage") == "gold_assertions":
                content_failure_case_count += 1
        if result.get("structure_passed"):
            structure_passed_cases += 1
        content_scores.append(float(result.get("content_score", 0.0)))
        structure_scores.append(float(result.get("structure_score", 0.0)))
        live_depth_scores.append(float(result.get("live_depth_score", 0.0)))
        for assertion in result.get("assertions", []):
            if not assertion["passed"]:
                assertion_counter[assertion["name"]] += 1
        for quality in result.get("quality_trace", []):
            if quality.get("outcome") in {"fallback", "repaired"}:
                fallback_counter[f"{quality['stage']}:{quality['outcome']}"] += 1
        for trace in result.get("llm_call_trace", []):
            retry_counter[int(trace.get("retry_count", 0))] += 1
            durations.append(float(trace.get("duration_seconds", 0.0)))
            for key, value in dict(trace.get("usage", {})).items():
                if isinstance(value, (int, float)):
                    usage_totals[key] += int(value)
        for stage, value in dict(result.get("stage_live_attempt_count") or {}).items():
            stage_live_attempt_count[str(stage)] += int(value)
        for stage, value in dict(result.get("stage_live_success_count") or {}).items():
            stage_live_success_count[str(stage)] += int(value)
        for stage, value in dict(result.get("stage_provider_failure_count") or {}).items():
            stage_provider_failure_count[str(stage)] += int(value)
        if any(int(value) > 0 for value in dict(result.get("stage_provider_failure_count") or {}).values()):
            provider_hit_depth_case_count += 1
    return {
        "total_cases": len(results),
        "passed_cases": passed_cases,
        "structure_passed_cases": structure_passed_cases,
        "pass_rate": round(passed_cases / len(results), 4) if results else 0.0,
        "structure_pass_rate": round(structure_passed_cases / len(results), 4) if results else 0.0,
        "avg_content_score": round(mean(content_scores), 4) if content_scores else 0.0,
        "avg_structure_score": round(mean(structure_scores), 4) if structure_scores else 0.0,
        "avg_live_depth_score": round(mean(live_depth_scores), 4) if live_depth_scores else 0.0,
        "content_failure_case_count": content_failure_case_count,
        "provider_hit_depth_case_count": provider_hit_depth_case_count,
        "failure_stage_distribution": dict(failure_stage_counter),
        "failure_category_distribution": dict(failure_category_counter),
        "failing_assertions": dict(assertion_counter),
        "llm_call_count_total": sum(result.get("llm_call_count", 0) for result in results),
        "llm_usage_totals": dict(usage_totals),
        "llm_latency": {
            "avg_seconds": round(mean(durations), 4) if durations else 0.0,
            "max_seconds": round(max(durations), 4) if durations else 0.0,
        },
        "fallback_distribution": dict(fallback_counter),
        "stage_live_attempt_count": dict(stage_live_attempt_count),
        "stage_live_success_count": dict(stage_live_success_count),
        "stage_provider_failure_count": dict(stage_provider_failure_count),
        "retry_distribution": {str(key): value for key, value in retry_counter.items()},
        "results": results,
    }


def _mode_summaries(mode_results: dict[AuthorV2RunMode, list[dict[str, Any]]]) -> dict[str, Any]:
    deterministic_content = summarize_results(mode_results.get("deterministic", []))["avg_content_score"] if mode_results.get("deterministic") else 0.0
    summaries: dict[str, Any] = {}
    for mode, results in mode_results.items():
        summary = summarize_results(results)
        if mode != "deterministic":
            summary["content_gain_vs_deterministic"] = round(summary["avg_content_score"] - deterministic_content, 4)
        summaries[mode] = summary
    return summaries


def _select_repeat_cases(
    *,
    burst_cases: list[UrbanGoldCase],
    burst_results_by_mode: dict[AuthorV2RunMode, list[dict[str, Any]]],
    top_n: int,
) -> list[UrbanGoldCase]:
    if top_n <= 0:
        return []
    best_scores: dict[str, float] = defaultdict(float)
    for mode in LIVE_BENCHMARK_MODES:
        for result in burst_results_by_mode.get(mode, []):
            best_scores[result["case_id"]] = max(best_scores[result["case_id"]], float(result.get("content_score", 0.0)))
    ordered_case_ids = [case_id for case_id, _ in sorted(best_scores.items(), key=lambda item: (-item[1], item[0]))[:top_n]]
    by_id = {case.case_id: case for case in burst_cases}
    return [by_id[case_id] for case_id in ordered_case_ids if case_id in by_id]


def run_benchmark(
    output_dir: Path,
    mini_cases: list[UrbanGoldCase] | None = None,
    *,
    modes: tuple[AuthorV2RunMode, ...] = BENCHMARK_MODES,
    include_burst: bool = False,
    burst_cases: list[UrbanGoldCase] | None = None,
    repeat_top: int = 20,
    repeat_count: int = 3,
    play_length_preset: str | None = None,
    case_timeout_seconds: float | None = None,
    case_max_workers: int | None = None,
) -> dict[str, Any]:
    resolved_output_dir = output_dir.resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    smoke_cases = mini_cases or mini_gold_set()

    def _run_case_batch(
        *,
        cases: list[UrbanGoldCase],
        mode: AuthorV2RunMode,
        suite_name: str,
    ) -> list[dict[str, Any]]:
        if not cases:
            return []
        workers = max(1, int(case_max_workers)) if case_max_workers is not None else 1
        workers = min(workers, len(cases))
        if workers <= 1:
            return [
                _run_case_with_timeout(
                    case,
                    resolved_output_dir,
                    mode=mode,
                    suite_name=suite_name,
                    run_label=None,
                    play_length_preset=play_length_preset,
                    case_timeout_seconds=case_timeout_seconds,
                )
                for case in cases
            ]
        ordered: list[dict[str, Any] | None] = [None] * len(cases)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    _run_case_with_timeout,
                    case,
                    resolved_output_dir,
                    mode=mode,
                    suite_name=suite_name,
                    run_label=None,
                    play_length_preset=play_length_preset,
                    case_timeout_seconds=case_timeout_seconds,
                ): idx
                for idx, case in enumerate(cases)
            }
            for future in as_completed(future_map):
                idx = future_map[future]
                ordered[idx] = future.result()
        return [row for row in ordered if row is not None]

    smoke_results_by_mode = {
        mode: _run_case_batch(cases=smoke_cases, mode=mode, suite_name="smoke")
        for mode in modes
    }
    summary: dict[str, Any] = {
        "smoke": {
            "total_cases": len(smoke_cases),
            "mode_summaries": _mode_summaries(smoke_results_by_mode),
        }
    }
    if play_length_preset is not None:
        summary["play_length_preset"] = play_length_preset
    if include_burst:
        resolved_burst_cases = burst_cases or burst_pressure_set()
        burst_results_by_mode = {
            mode: [
                _run_case_with_timeout(
                    case,
                    resolved_output_dir,
                    mode=mode,
                    suite_name="burst",
                    run_label=None,
                    play_length_preset=play_length_preset,
                    case_timeout_seconds=case_timeout_seconds,
                )
                for case in resolved_burst_cases
            ]
            for mode in modes
        }
        summary["burst"] = {
            "total_cases": len(resolved_burst_cases),
            "mode_summaries": _mode_summaries(burst_results_by_mode),
        }
        repeat_cases = _select_repeat_cases(
            burst_cases=resolved_burst_cases,
            burst_results_by_mode=burst_results_by_mode,
            top_n=repeat_top,
        )
        if repeat_cases and repeat_count > 0:
            repeat_results_by_mode: dict[AuthorV2RunMode, list[dict[str, Any]]] = {mode: [] for mode in LIVE_BENCHMARK_MODES if mode in modes}
            for mode in tuple(repeat_results_by_mode):
                for case in repeat_cases:
                    for repeat_index in range(1, repeat_count + 1):
                        repeat_results_by_mode[mode].append(
                            _run_case_with_timeout(
                                case,
                                resolved_output_dir,
                                mode=mode,
                                suite_name="repeat",
                                run_label=f"repeat_{repeat_index}",
                                play_length_preset=play_length_preset,
                                case_timeout_seconds=case_timeout_seconds,
                            )
                        )
            summary["repeat"] = {
                "total_cases": len(repeat_cases),
                "repeat_count": repeat_count,
                "mode_summaries": _mode_summaries(repeat_results_by_mode),
            }
    _write_json(resolved_output_dir / "summary.json", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the internal urban author->play sidecar benchmark.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--mode",
        dest="modes",
        action="append",
        choices=SUPPORTED_BENCHMARK_MODES,
        help="Optional benchmark mode. Repeat to run multiple modes. Defaults to the baseline three-mode set.",
    )
    parser.add_argument("--include-burst", action="store_true", help="Run the 40-case burst pressure suite.")
    parser.add_argument("--repeat-top", type=int, default=20, help="Repeat the top N burst cases for live modes.")
    parser.add_argument("--repeat-count", type=int, default=3, help="How many times to rerun each repeated case.")
    parser.add_argument("--play-length-preset", choices=PLAY_LENGTH_PRESETS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    modes = tuple(args.modes) if args.modes else BENCHMARK_MODES
    summary = run_benchmark(
        args.output_dir,
        modes=modes,
        include_burst=bool(args.include_burst),
        repeat_top=int(args.repeat_top),
        repeat_count=int(args.repeat_count),
        play_length_preset=args.play_length_preset,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
