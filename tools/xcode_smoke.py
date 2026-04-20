from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import traceback
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rpg_backend.author.seed_normalization import normalize_seed_packet
from rpg_backend.author_v3.workflow import run_author_v3_pipeline
from rpg_backend.config import get_settings
from rpg_backend.play_v2.runtime import build_initial_world_state, build_suggested_actions, run_turn


_AUTHOR_SEED = "办公室权力斗争"
_AUTHOR_REQUESTED_RUN_MODE = "live"
_AUTHOR_FALLBACK_RUN_MODE = "live_gpt_5_4_mini"


def _count_chinese_characters(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _pick_token_summary(diagnostics: dict[str, Any]) -> tuple[int, int, str]:
    candidates = (
        ("compose", "compose_input_tokens", "compose_output_tokens"),
        ("intent_llm", "intent_llm_input_tokens", "intent_llm_output_tokens"),
        ("micro_sim", "micro_sim_input_tokens", "micro_sim_output_tokens"),
        ("intent_stage", "intent_stage_input_tokens", "intent_stage_output_tokens"),
    )
    for source, input_key, output_key in candidates:
        input_tokens = int(diagnostics.get(input_key) or 0)
        output_tokens = int(diagnostics.get(output_key) or 0)
        if input_tokens > 0 or output_tokens > 0:
            return input_tokens, output_tokens, source
    return 0, 0, "none"


def _run_smoke1() -> tuple[bool, str, Any, str]:
    used_seed_retry = False
    effective_run_mode = _AUTHOR_REQUESTED_RUN_MODE
    try:
        result = run_author_v3_pipeline(_AUTHOR_SEED, run_mode=_AUTHOR_REQUESTED_RUN_MODE)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "live gateway does not support mode=live" not in message:
            raise
        effective_run_mode = _AUTHOR_FALLBACK_RUN_MODE
        try:
            result = run_author_v3_pipeline(_AUTHOR_SEED, run_mode=effective_run_mode)
        except Exception as retry_exc:  # noqa: BLE001
            retry_message = str(retry_exc)
            if "detected_shell" not in retry_message:
                raise
            normalized_seed = normalize_seed_packet(_AUTHOR_SEED).rewritten_seed
            used_seed_retry = True
            result = run_author_v3_pipeline(normalized_seed, run_mode=effective_run_mode)
    plan = result["plan"]
    if int(plan.delta_pack_contract_version) != 5:
        return False, f"delta_pack_contract_version={plan.delta_pack_contract_version}", plan, effective_run_mode
    if str(plan.author_version) != "v3":
        return False, f"author_version={plan.author_version}", plan, effective_run_mode
    if not list(plan.cast):
        return False, "cast is empty", plan, effective_run_mode
    if not list(plan.segments):
        return False, "segments is empty", plan, effective_run_mode
    if not list(plan.hooks or []):
        return False, "hooks is empty", plan, effective_run_mode
    reason = "validated plan structure"
    if effective_run_mode != _AUTHOR_REQUESTED_RUN_MODE:
        reason = (
            f"{reason}; requested run_mode={_AUTHOR_REQUESTED_RUN_MODE} is unsupported in current code, "
            f"used {effective_run_mode}"
        )
    if used_seed_retry:
        reason = f"{reason}; retried with normalized office_power seed after invalid detected_shell from live response"
    return True, reason, plan, effective_run_mode


def _run_smoke2(plan: Any) -> tuple[bool, str, Any]:
    state = build_initial_world_state(plan, session_id="xcode_smoke_play")
    suggestions = build_suggested_actions(plan, state)
    if not suggestions:
        raise RuntimeError("no suggested actions available for initial state")
    action = suggestions[0]
    # run_turn is the public path that applies turn resolution and then renders narration.
    result = run_turn(
        plan,
        state,
        action.prompt,
        selected_suggestion_id=action.suggestion_id,
    )
    narration = str(result.narration or "")
    diagnostics = dict(result.intent_stage_diagnostics or {})
    if not narration.strip():
        return False, "narration is empty", result
    if _count_chinese_characters(narration) < 30:
        return False, f"narration has fewer than 30 Chinese characters: {_count_chinese_characters(narration)}", result
    required_keys = ("storylet_matches_count", "memory_context_active_hooks")
    missing = [key for key in required_keys if key not in diagnostics]
    if missing:
        return False, f"missing diagnostics keys: {', '.join(missing)}", result
    return True, "validated narration and diagnostics", result


def main() -> int:
    os.environ["APP_PLAY_V2_DRAMATIC_REWRITE_USE_LLM"] = "true"
    get_settings.cache_clear()

    smoke1_ok = False
    smoke2_ok = False
    plan = None
    turn_result = None

    try:
        smoke1_ok, smoke1_reason, plan, effective_run_mode = _run_smoke1()
        if smoke1_ok:
            print(
                "SMOKE1 PASS",
                smoke1_reason,
                f"story_id={plan.story_id}",
                f"cast_count={len(plan.cast)}",
                f"segments_count={len(plan.segments)}",
                f"hooks_count={len(plan.hooks or [])}",
                f"author_version={plan.author_version}",
                f"effective_run_mode={effective_run_mode}",
            )
        else:
            print(
                "SMOKE1 FAIL",
                smoke1_reason,
                f"story_id={getattr(plan, 'story_id', '')}",
                f"cast_count={len(getattr(plan, 'cast', []) or [])}",
                f"segments_count={len(getattr(plan, 'segments', []) or [])}",
                f"hooks_count={len(getattr(plan, 'hooks', []) or [])}",
                f"author_version={getattr(plan, 'author_version', '')}",
                f"effective_run_mode={effective_run_mode}",
            )
    except Exception as exc:  # noqa: BLE001
        print("SMOKE1 FAIL", f"{type(exc).__name__}: {exc}")
        print(traceback.format_exc().rstrip())

    if smoke1_ok and plan is not None:
        try:
            smoke2_ok, smoke2_reason, turn_result = _run_smoke2(plan)
            diagnostics = dict(turn_result.intent_stage_diagnostics or {})
            if smoke2_ok:
                print(
                    "SMOKE2 PASS",
                    smoke2_reason,
                    f"narration_chars={_count_chinese_characters(turn_result.narration)}",
                    f"storylet_matches_count={diagnostics.get('storylet_matches_count')}",
                    f"memory_context_active_hooks={diagnostics.get('memory_context_active_hooks')}",
                )
            else:
                print(
                    "SMOKE2 FAIL",
                    smoke2_reason,
                    f"storylet_matches_count={diagnostics.get('storylet_matches_count')}",
                    f"memory_context_active_hooks={diagnostics.get('memory_context_active_hooks')}",
                )
            print("NARRATION")
            print(turn_result.narration)
            input_tokens, output_tokens, source = _pick_token_summary(diagnostics)
            print(
                "TOKEN_SUMMARY",
                f"source={source}",
                f"input_tokens={input_tokens}",
                f"output_tokens={output_tokens}",
            )
        except Exception as exc:  # noqa: BLE001
            print("SMOKE2 FAIL", f"{type(exc).__name__}: {exc}")
            print(traceback.format_exc().rstrip())
    else:
        print("SMOKE2 FAIL", "blocked: smoke1 did not produce a valid live author plan")

    return 0 if smoke1_ok and smoke2_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
