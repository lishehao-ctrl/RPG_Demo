from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from rpg_backend.author.compiler.beats import build_default_beat_plan_draft
from rpg_backend.author.compiler.brief import focus_brief
from rpg_backend.author.compiler.cast import build_cast_draft_from_overview, derive_cast_overview_draft, plan_cast_topology
from rpg_backend.author.compiler.router import plan_brief_theme
from rpg_backend.author.compiler.story import build_default_story_frame_draft, sanitize_story_sentence
from rpg_backend.author.normalize import normalize_whitespace, trim_ellipsis
from rpg_backend.author.contracts import (
    AuthorPreviewBeatSummary,
    AuthorPreviewCastSlotSummary,
    AuthorPreviewResponse,
    AuthorPreviewStory,
    AuthorPreviewStrategies,
    AuthorPreviewStructure,
    AuthorPreviewTheme,
    AuthorStorySummary,
    DesignBundle,
    NormalizedSeedPacket,
)
from rpg_backend.author.seed_normalization import normalize_seed_packet, relationship_drama_shell_defaults
from rpg_backend.author.display import build_preview_flashcards, theme_label
from rpg_backend.product_text import (
    build_product_premise_fallback,
    sanitize_product_one_liner,
    sanitize_product_story_sentence,
)


_PREVIEW_TONE_BY_THEME = {
    "legitimacy_crisis": "Tense civic thriller",
    "logistics_quarantine_crisis": "Tense bureaucratic thriller",
    "truth_record_crisis": "Procedural suspense",
    "public_order_crisis": "Urgent civic suspense",
    "generic_civic_crisis": "Tense civic drama",
}

_PREVIEW_ROLE_PATTERN = re.compile(
    r"^(?P<subject>(?:a|an|the)\s+(?:[a-z0-9-]+\s+){0,5}"
    r"(?:mediator|envoy|engineer|inspector|archivist|keeper|priest|councilor|guard|messenger|scholar|mayor|agent|negotiator|"
    r"auditor|superintendent|liaison|ombudsman|clerk|marshal|officer|delegate|steward))\s+"
    r"(?P<verb>discovers|finds|uncovers|learns|realizes|spots|proves|reveals|exposes)\s+"
    r"(?P<rest>.+)$",
    flags=re.IGNORECASE,
)


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = {token for token in re.findall(r"[a-z0-9']+", left.casefold()) if len(token) >= 3}
    right_tokens = {token for token in re.findall(r"[a-z0-9']+", right.casefold()) if len(token) >= 3}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(right_tokens), 1)


def _looks_like_seed_echo(candidate: str, prompt_seed: str) -> bool:
    normalized_candidate = normalize_whitespace(candidate)
    normalized_seed = normalize_whitespace(prompt_seed)
    if not normalized_candidate or not normalized_seed:
        return False
    if normalized_seed.casefold() in normalized_candidate.casefold():
        return True
    return _token_overlap_ratio(normalized_candidate, normalized_seed) >= 0.72


def _preview_setting_frame(*, primary_theme: str, prompt_seed: str, focused_brief) -> str:
    lowered = f"{prompt_seed} {focused_brief.setting_signal} {focused_brief.core_conflict}".casefold()
    if primary_theme == "logistics_quarantine_crisis":
        if any(keyword in lowered for keyword in ("bridge", "flood", "ration", "ward", "district", "convoy", "infrastructure")):
            return "a city under ration strain and infrastructure pressure"
        if any(keyword in lowered for keyword in ("harbor", "port", "quarantine", "dock", "shipping")):
            return "a harbor city strained by quarantine politics and supply fear"
        return "a city where scarcity and emergency logistics keep turning relief into leverage"
    if primary_theme == "truth_record_crisis":
        return "a civic archive where public trust depends on records that can still be falsified"
    if primary_theme == "public_order_crisis":
        return "a city under blackout strain and escalating public panic"
    if primary_theme == "legitimacy_crisis":
        return "a civic system where emergency authority is starting to outrun public legitimacy"
    return normalize_whitespace(focused_brief.setting_signal)


def _preview_mandate(*, prompt_seed: str, focused_brief) -> str:
    normalized_kernel = normalize_whitespace(focused_brief.story_kernel or prompt_seed)
    match = _PREVIEW_ROLE_PATTERN.match(normalized_kernel)
    if match:
        subject = normalize_whitespace(match.group("subject"))
        verb = match.group("verb").casefold()
        rest = normalize_whitespace(match.group("rest")).rstrip(".")
        if rest:
            if verb in {"discovers", "finds", "uncovers", "learns", "realizes", "spots"}:
                connector = "must prove" if rest.casefold().startswith("that ") else "must prove that"
            elif verb == "proves":
                connector = "must prove"
            else:
                connector = "must force into the open" if rest.casefold().startswith("that ") else "must force into the open that"
            return trim_ellipsis(f"{subject} {connector} {rest}".strip(), 220)
    lowered = normalized_kernel.casefold()
    if "archivist" in lowered or "clerk" in lowered or "auditor" in lowered:
        return "an archivist must verify one binding public record before the official story hardens"
    if "superintendent" in lowered or "engineer" in lowered:
        return "a superintendent must expose the staged logistics failure before emergency rule hardens into habit"
    if "inspector" in lowered or "officer" in lowered:
        return "an inspector must expose the hidden breach before emergency authority becomes private leverage"
    if "mediator" in lowered or "liaison" in lowered or "ombudsman" in lowered:
        return "a mediator must hold rival institutions in one room long enough to force a binding answer"
    return trim_ellipsis(normalized_kernel, 220)


def _preview_opposition_force(*, primary_theme: str, prompt_seed: str, focused_brief) -> str:
    lowered = f"{prompt_seed} {focused_brief.setting_signal} {focused_brief.core_conflict}".casefold()
    if primary_theme == "logistics_quarantine_crisis":
        if any(keyword in lowered for keyword in ("bridge", "flood", "ration", "ward", "district", "convoy", "infrastructure")):
            return "scarcity politics and emergency command keep turning logistics into political leverage"
        return "trade pressure and quarantine politics keep turning relief into factional leverage"
    if primary_theme == "truth_record_crisis":
        return "forged records and procedural denial keep reshaping the public story"
    if primary_theme == "public_order_crisis":
        return "panic, rumor, and emergency messaging keep pushing the city toward open disorder"
    if primary_theme == "legitimacy_crisis":
        return "institutional panic and mandate politics turn every delay into leverage"
    return "public pressure keeps turning delay into civic fracture"


def _preview_tone(*, prompt_seed: str, primary_theme: str, focused_brief) -> str:
    candidate = normalize_whitespace(focused_brief.tone_signal)
    if not candidate or _looks_like_seed_echo(candidate, prompt_seed) or len(candidate.split()) > 8:
        return _PREVIEW_TONE_BY_THEME.get(primary_theme, "Tense civic drama")
    return trim_ellipsis(candidate, 120)


def build_author_preview_from_seed(prompt_seed: str) -> AuthorPreviewResponse:
    # Deterministic fallback for tests and offline fixtures only.
    # Product preview traffic goes through AuthorJobService._run_preview_workflow()
    # and build_author_preview_from_state() so preview data always comes from the
    # real author checkpoint state rather than a parallel preview-only path.
    normalized_seed = normalize_seed_packet(prompt_seed)
    shell_defaults = relationship_drama_shell_defaults(normalized_seed.accepted_shell)
    route_fantasy = shell_defaults.route_fantasy if normalized_seed.fit_mode != "out_of_range" else None
    surface_signal_summary = normalized_seed.surface_signal_summary if normalized_seed.fit_mode != "out_of_range" else None
    target_visibility_summary = shell_defaults.target_visibility_summary if normalized_seed.fit_mode != "out_of_range" else None
    focused_brief = focus_brief(normalized_seed.rewritten_seed)
    brief_theme = plan_brief_theme(focused_brief)
    preview_story = build_default_story_frame_draft(focused_brief)
    preview_premise = preview_story.premise
    if _looks_like_seed_echo(preview_premise, prompt_seed):
        preview_premise = build_product_premise_fallback(
            primary_theme=brief_theme.primary_theme,
            focused_brief=focused_brief,
            prompt_seed=prompt_seed,
            limit=320,
        )
    preview_premise = sanitize_product_story_sentence(
        preview_premise,
        fallback=build_product_premise_fallback(
            primary_theme=brief_theme.primary_theme,
            focused_brief=focused_brief,
            prompt_seed=prompt_seed,
            limit=320,
        ),
        limit=320,
        echo_reference=prompt_seed,
    )
    preview_tone = _preview_tone(
        prompt_seed=prompt_seed,
        primary_theme=brief_theme.primary_theme,
        focused_brief=focused_brief,
    )
    topology = plan_cast_topology(focused_brief, preview_story)
    cast_overview = derive_cast_overview_draft(focused_brief, preview_story)
    cast_draft = build_cast_draft_from_overview(cast_overview, focused_brief)
    beat_plan = build_default_beat_plan_draft(
        focused_brief,
        story_frame=preview_story,
        cast_draft=cast_draft,
    )
    expected_npc_count = len(cast_overview.cast_slots)
    expected_beat_count = len(beat_plan.beats)
    return AuthorPreviewResponse(
        preview_id=str(uuid4()),
        prompt_seed=prompt_seed,
        focused_brief=focused_brief,
        theme=AuthorPreviewTheme(
            primary_theme=brief_theme.primary_theme,
            modifiers=list(brief_theme.modifiers),
            router_reason=brief_theme.router_reason,
        ),
        strategies=AuthorPreviewStrategies(
            story_frame_strategy=brief_theme.story_frame_strategy,
            cast_strategy=brief_theme.cast_strategy,
            beat_plan_strategy=brief_theme.beat_plan_strategy,
        ),
        structure=AuthorPreviewStructure(
            cast_topology=topology.topology,
            expected_npc_count=expected_npc_count,
            expected_beat_count=expected_beat_count,
        ),
        story=AuthorPreviewStory(
            title=preview_story.title,
            premise=preview_premise,
            tone=preview_tone,
            stakes=preview_story.stakes,
            route_fantasy=route_fantasy,
        ),
        normalized_seed=normalized_seed,
        story_shell_id=normalized_seed.accepted_shell if normalized_seed.fit_mode != "out_of_range" else None,
        surface_signal_summary=surface_signal_summary,
        target_visibility_summary=target_visibility_summary,
        cast_slots=[
            AuthorPreviewCastSlotSummary(
                slot_label=item.slot_label,
                public_role=item.public_role,
            )
            for item in cast_overview.cast_slots
        ],
        beats=[
            AuthorPreviewBeatSummary(
                title=item.title,
                goal=item.goal,
                milestone_kind=item.milestone_kind,
            )
            for item in beat_plan.beats
        ],
        flashcards=build_preview_flashcards(
            theme=brief_theme.primary_theme,
            tone=preview_tone,
            cast_topology=topology.topology,
            expected_npc_count=expected_npc_count,
            expected_beat_count=expected_beat_count,
            title=preview_story.title,
            conflict=_preview_opposition_force(
                primary_theme=brief_theme.primary_theme,
                prompt_seed=prompt_seed,
                focused_brief=focused_brief,
            ),
        ),
        stage="brief_parsed",
    )


def _state_preview_stage(state: dict[str, Any]) -> str:
    if state.get("design_bundle") is not None:
        return "completed"
    if state.get("ending_rules_draft") is not None:
        return "ending_ready"
    if state.get("route_affordance_pack_draft") is not None:
        return "route_ready"
    if state.get("beat_plan_draft") is not None:
        return "beat_plan_ready"
    if state.get("cast_draft") is not None:
        return "cast_ready"
    if state.get("cast_overview_draft") is not None:
        return "cast_planned"
    if state.get("theme_router_reason") is not None or state.get("primary_theme") is not None:
        return "theme_confirmed"
    if state.get("story_frame_draft") is not None:
        return "story_frame_ready"
    if state.get("brief_primary_theme") is not None:
        return "brief_classified"
    if state.get("focused_brief") is not None:
        return "brief_parsed"
    return "queued"


def _state_expected_beat_count(state: dict[str, Any], existing_preview: AuthorPreviewResponse | None) -> int:
    beat_plan = state.get("beat_plan_draft")
    if beat_plan is not None and getattr(beat_plan, "beats", None):
        return len(beat_plan.beats)
    if existing_preview is not None:
        return max(int(existing_preview.structure.expected_beat_count), 1)
    return 3


def build_author_preview_from_state(
    *,
    preview_id: str,
    prompt_seed: str,
    state: dict[str, Any],
    existing_preview: AuthorPreviewResponse | None = None,
) -> AuthorPreviewResponse:
    normalized_seed = state.get("normalized_seed")
    if isinstance(normalized_seed, dict):
        normalized_seed = NormalizedSeedPacket.model_validate(normalized_seed)
    if normalized_seed is None:
        normalized_seed = (
            existing_preview.normalized_seed
            if existing_preview is not None and existing_preview.normalized_seed is not None
            else normalize_seed_packet(prompt_seed)
        )
    shell_defaults = relationship_drama_shell_defaults(normalized_seed.accepted_shell)
    route_fantasy = shell_defaults.route_fantasy if normalized_seed.fit_mode != "out_of_range" else None
    surface_signal_summary = normalized_seed.surface_signal_summary if normalized_seed.fit_mode != "out_of_range" else None
    target_visibility_summary = shell_defaults.target_visibility_summary if normalized_seed.fit_mode != "out_of_range" else None
    focused_brief = state.get("focused_brief") or (
        existing_preview.focused_brief if existing_preview is not None else focus_brief(normalized_seed.rewritten_seed)
    )
    primary_theme = (
        state.get("primary_theme")
        or state.get("brief_primary_theme")
        or (existing_preview.theme.primary_theme if existing_preview is not None else plan_brief_theme(focused_brief).primary_theme)
    )
    theme_modifiers = list(
        state.get("theme_modifiers")
        or state.get("brief_theme_modifiers")
        or (existing_preview.theme.modifiers if existing_preview is not None else [])
    )
    theme_router_reason = str(
        state.get("theme_router_reason")
        or state.get("brief_theme_router_reason")
        or (existing_preview.theme.router_reason if existing_preview is not None else "preview_state")
    )
    story_frame = state.get("story_frame_draft") or (
        existing_preview.story if existing_preview is not None else build_default_story_frame_draft(focused_brief)
    )
    if isinstance(story_frame, AuthorPreviewStory):
        story = story_frame
    else:
        story = AuthorPreviewStory(
            title=getattr(story_frame, "title", existing_preview.story.title if existing_preview is not None else "Untitled Preview"),
            premise=getattr(story_frame, "premise", existing_preview.story.premise if existing_preview is not None else prompt_seed),
            tone=getattr(story_frame, "tone", existing_preview.story.tone if existing_preview is not None else "Tense civic drama"),
            stakes=getattr(
                story_frame,
                "stakes",
                existing_preview.story.stakes if existing_preview is not None else "If the crisis is mishandled, civic order and public trust can fail at the same time.",
            ),
            route_fantasy=getattr(
                story_frame,
                "route_fantasy",
                existing_preview.story.route_fantasy if existing_preview is not None else route_fantasy,
            ),
        )
    cast_overview = state.get("cast_overview_draft")
    cast_slots = [
        AuthorPreviewCastSlotSummary(
            slot_label=item.slot_label,
            public_role=item.public_role,
        )
        for item in getattr(cast_overview, "cast_slots", [])[:5]
    ]
    if not cast_slots and existing_preview is not None:
        cast_slots = list(existing_preview.cast_slots)
    cast_draft = state.get("cast_draft")
    if cast_draft is None and cast_overview is not None:
        try:
            cast_draft = build_cast_draft_from_overview(cast_overview, focused_brief)
        except Exception:
            cast_draft = None
    expected_npc_count = len(getattr(cast_draft, "cast", []) or cast_slots or (existing_preview.cast_slots if existing_preview is not None else []))
    expected_npc_count = max(expected_npc_count, existing_preview.structure.expected_npc_count if existing_preview is not None else 1)
    beat_plan = state.get("beat_plan_draft")
    if beat_plan is None and cast_draft is not None and not existing_preview:
        try:
            beat_plan = build_default_beat_plan_draft(
                focused_brief,
                story_frame=story_frame,
                cast_draft=cast_draft,
            )
        except Exception:
            beat_plan = None
    beat_summaries = [
        AuthorPreviewBeatSummary(
            title=item.title,
            goal=item.goal,
            milestone_kind=item.milestone_kind,
        )
        for item in getattr(beat_plan, "beats", [])[:4]
    ]
    if not beat_summaries and existing_preview is not None:
        beat_summaries = list(existing_preview.beats)
    cast_topology = str(
        state.get("cast_topology")
        or (existing_preview.structure.cast_topology if existing_preview is not None else "four_slot")
    )
    expected_beat_count = _state_expected_beat_count(state, existing_preview)
    tone = _preview_tone(
        prompt_seed=prompt_seed,
        primary_theme=primary_theme,
        focused_brief=focused_brief,
    )
    if not story.tone or _looks_like_seed_echo(story.tone, prompt_seed):
        story = story.model_copy(update={"tone": tone})
    fallback_story = build_default_story_frame_draft(focused_brief)
    fallback_premise = build_product_premise_fallback(
        primary_theme=primary_theme,
        focused_brief=focused_brief,
        prompt_seed=prompt_seed,
        limit=320,
    )
    story = story.model_copy(
        update={
            "premise": sanitize_product_story_sentence(
                story.premise,
                fallback=fallback_premise or fallback_story.premise,
                limit=320,
                echo_reference=prompt_seed,
            ),
            "stakes": sanitize_story_sentence(
                story.stakes,
                fallback=fallback_story.stakes,
                limit=240,
            ),
        }
    )
    return AuthorPreviewResponse(
        preview_id=preview_id,
        prompt_seed=prompt_seed,
        normalized_seed=normalized_seed,
        story_shell_id=normalized_seed.accepted_shell if normalized_seed.fit_mode != "out_of_range" else None,
        surface_signal_summary=surface_signal_summary,
        target_visibility_summary=target_visibility_summary,
        focused_brief=focused_brief,
        theme=AuthorPreviewTheme(
            primary_theme=primary_theme,
            modifiers=theme_modifiers[:8],
            router_reason=theme_router_reason,
        ),
        strategies=AuthorPreviewStrategies(
            story_frame_strategy=str(state.get("story_frame_strategy") or (existing_preview.strategies.story_frame_strategy if existing_preview is not None else "generic_civic_story")),
            cast_strategy=str(state.get("cast_strategy") or (existing_preview.strategies.cast_strategy if existing_preview is not None else "generic_civic_cast")),
            beat_plan_strategy=str(state.get("beat_plan_strategy") or (existing_preview.strategies.beat_plan_strategy if existing_preview is not None else "conservative_direct_draft")),
        ),
        structure=AuthorPreviewStructure(
            cast_topology=cast_topology,
            expected_npc_count=expected_npc_count,
            expected_beat_count=expected_beat_count,
        ),
        story=story,
        cast_slots=cast_slots[:5],
        beats=beat_summaries[:4],
        flashcards=build_preview_flashcards(
            theme=primary_theme,
            tone=story.tone,
            cast_topology=cast_topology,
            expected_npc_count=expected_npc_count,
            expected_beat_count=expected_beat_count,
            title=story.title,
            conflict=_preview_opposition_force(
                primary_theme=primary_theme,
                prompt_seed=prompt_seed,
                focused_brief=focused_brief,
            ),
        ),
        stage=_state_preview_stage(state),
    )
def build_author_story_summary(bundle: DesignBundle, *, primary_theme: str) -> AuthorStorySummary:
    fallback_story = build_default_story_frame_draft(bundle.focused_brief)
    fallback_premise = build_product_premise_fallback(
        primary_theme=primary_theme,
        focused_brief=bundle.focused_brief,
        prompt_seed=bundle.focused_brief.story_kernel,
        limit=320,
    )
    premise = sanitize_product_story_sentence(
        bundle.story_bible.premise,
        fallback=fallback_premise or fallback_story.premise,
        limit=320,
    )
    one_liner = sanitize_product_one_liner(
        premise=premise,
        title=bundle.story_bible.title,
        limit=220,
    )
    return AuthorStorySummary(
        title=bundle.story_bible.title,
        one_liner=one_liner,
        premise=premise,
        tone=bundle.story_bible.tone,
        theme=theme_label(primary_theme),
        npc_count=len(bundle.story_bible.cast),
        beat_count=len(bundle.beat_spine),
    )
