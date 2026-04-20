from __future__ import annotations

import re

from rpg_backend.author.compiler.endings import build_default_ending_rules, normalize_ending_rules_draft
from rpg_backend.author.compiler.routes import (
    build_default_route_affordance_pack,
    build_deterministic_affordance_profiles,
    bundle_affordance_tags,
    normalize_route_affordance_pack,
)
from rpg_backend.author.compiler.story import build_default_story_frame_draft, sanitize_story_sentence
from rpg_backend.author.contracts import (
    AffordanceEffectProfile,
    AxisDefinition,
    BeatSpec,
    DesignBundle,
    EndingItem,
    EndingRulesDraft,
    RouteAffordancePackDraft,
)
from rpg_backend.author.normalize import normalize_whitespace, trim_ellipsis, unique_preserve
from rpg_backend.play.contracts import PlayPlan, PlayProtagonist
from rpg_backend.product_text import (
    build_product_premise_fallback,
    sanitize_product_identity_summary,
    sanitize_product_opening_narration,
    sanitize_product_story_sentence,
)
from rpg_backend.story_profiles import (
    author_theme_from_bundle,
    play_closeout_profile_from_bundle,
    play_runtime_profile_from_bundle,
)


_PLAY_AXIS_FALLBACK_LABELS = {
    "external_pressure": "External Pressure",
    "public_panic": "Public Panic",
    "political_leverage": "Political Leverage",
    "resource_strain": "Resource Strain",
    "system_integrity": "Institutional Strain",
    "ally_trust": "Ally Trust",
    "exposure_risk": "Exposure Risk",
    "time_window": "Time Window",
}

_GENERIC_AXIS_LABELS = {
    "state axis",
    "axis",
    "pressure axis",
    "relationship axis",
    "resource axis",
    "time axis",
    "meter",
}

_MANDATE_GERUND_MAP = {
    "preserving": "preserve",
    "preventing": "prevent",
    "keeping": "keep",
    "restoring": "restore",
    "proving": "prove",
    "holding": "hold",
    "stabilizing": "stabilize",
    "securing": "secure",
    "containing": "contain",
    "binding": "bind",
    "forcing": "force",
}

_MANDATE_TAIL_MARKERS = (
    " triggers ",
    " trigger ",
    " reshapes ",
    " reshape ",
    " driven by ",
)

_MANDATE_NOISE_MARKERS = (
    " while ",
    " when ",
    " during ",
    " amid ",
    " under ",
    " across ",
    " throughout ",
    " against ",
)

_MANDATE_START_VERBS = (
    "prove",
    "protect",
    "prevent",
    "preserve",
    "keep",
    "hold",
    "restore",
    "stabilize",
    "secure",
    "contain",
    "bind",
    "force",
    "trace",
    "understand",
    "verify",
    "maintain",
    "reopen",
    "expose",
)

_OPENING_TEMPLATE_SEEDS = (
    "pressure",
    "hook",
    "stakes",
)

_ROLE_PHRASE_STOPWORDS = {
    "when",
    "during",
    "while",
    "after",
    "before",
    "if",
    "in",
    "amid",
    "under",
}

_ROLE_PREFIX_TRIM_TOKENS = {
    "city",
    "civic",
    "royal",
    "public",
    "neutral",
    "ward",
}

_ROLE_ARTICLES = {"a", "an", "the"}
_MANDATE_MAX_WORDS = 16
_TITLE_PREFIX_STOPWORDS = _ROLE_PHRASE_STOPWORDS | {"before", "after"}

_ROLE_DISCOVERY_PATTERN = re.compile(
    r"^(?:an?|the)\s+[^,]{0,80}\s+"
    r"(?P<verb>discovers|finds|uncovers|learns|realizes|spots|proves|reveals|exposes)\s+"
    r"(?P<rest>.+)$",
    flags=re.IGNORECASE,
)


def _merge_affordance_profiles(bundle: DesignBundle) -> list[AffordanceEffectProfile]:
    authored_pack = normalize_route_affordance_pack(
        RouteAffordancePackDraft(
            route_unlock_rules=bundle.rule_pack.route_unlock_rules,
            affordance_effect_profiles=bundle.rule_pack.affordance_effect_profiles,
        ),
        bundle,
    )
    authored_profiles = {profile.affordance_tag: profile for profile in authored_pack.affordance_effect_profiles}
    deterministic_profiles = {
        profile.affordance_tag: profile for profile in build_deterministic_affordance_profiles(bundle)
    }
    merged_profiles: list[AffordanceEffectProfile] = []
    ordered_tags = unique_preserve(
        [*bundle_affordance_tags(bundle), *list(authored_profiles.keys()), *list(deterministic_profiles.keys())]
    )
    for tag in ordered_tags:
        authored = authored_profiles.get(tag)
        fallback = deterministic_profiles.get(tag)
        if authored is None and fallback is None:
            continue
        if authored is None:
            merged_profiles.append(fallback)
            continue
        if fallback is None:
            merged_profiles.append(authored)
            continue
        merged_profiles.append(
            AffordanceEffectProfile(
                affordance_tag=authored.affordance_tag,
                default_story_function=authored.default_story_function or fallback.default_story_function,
                axis_deltas=authored.axis_deltas or fallback.axis_deltas,
                stance_deltas=authored.stance_deltas or fallback.stance_deltas,
                can_add_truth=bool(authored.can_add_truth or fallback.can_add_truth),
                can_add_event=bool(authored.can_add_event or fallback.can_add_event),
            )
        )
    return merged_profiles


def _compiled_route_pack(bundle: DesignBundle) -> RouteAffordancePackDraft:
    authored_pack = normalize_route_affordance_pack(
        RouteAffordancePackDraft(
            route_unlock_rules=bundle.rule_pack.route_unlock_rules,
            affordance_effect_profiles=bundle.rule_pack.affordance_effect_profiles,
        ),
        bundle,
    )
    default_pack = build_default_route_affordance_pack(bundle)
    return RouteAffordancePackDraft(
        route_unlock_rules=authored_pack.route_unlock_rules or default_pack.route_unlock_rules,
        affordance_effect_profiles=_merge_affordance_profiles(bundle),
    )


def _compiled_ending_rules(bundle: DesignBundle):
    authored = normalize_ending_rules_draft(
        EndingRulesDraft(ending_rules=bundle.rule_pack.ending_rules),
        bundle,
    )
    defaults = build_default_ending_rules(bundle)
    merged_by_id = {rule.ending_id: rule for rule in defaults.ending_rules}
    for rule in authored.ending_rules:
        merged_by_id[rule.ending_id] = rule
    return sorted(merged_by_id.values(), key=lambda item: (item.priority, item.ending_id))


def _resolved_axis_label(axis: AxisDefinition) -> str:
    raw = trim_ellipsis(axis.label or "", 80)
    if axis.axis_id == "system_integrity" and axis.kind == "pressure":
        return _PLAY_AXIS_FALLBACK_LABELS["system_integrity"]
    if raw and raw.casefold() not in _GENERIC_AXIS_LABELS:
        return raw
    return _PLAY_AXIS_FALLBACK_LABELS.get(axis.axis_id, axis.axis_id.replace("_", " ").title())


def _compiled_axes(bundle: DesignBundle) -> list[AxisDefinition]:
    return [
        axis.model_copy(update={"label": _resolved_axis_label(axis)})
        for axis in bundle.state_schema.axes
    ]


def _normalized_sentence_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _clean_opening_line(raw: str, *, fallback: str | None = None, limit: int = 220) -> str:
    raw_text = normalize_whitespace(raw)
    if _ROLE_DISCOVERY_PATTERN.match(raw_text):
        cleaned = trim_ellipsis(raw_text, limit).rstrip(".")
    else:
        cleaned = sanitize_story_sentence(raw_text, fallback=fallback or raw_text, limit=limit).rstrip(".")
    cleaned = re.sub(r"^(?:in|during|amid|under)\s+[^,]{0,120},\s*", "", cleaned, count=1, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:.")
    return trim_ellipsis(cleaned, limit)


def _rewrite_role_discovery_clause(text: str, *, limit: int = 220) -> str:
    match = _ROLE_DISCOVERY_PATTERN.match(text)
    if match is None:
        return text
    rest = normalize_whitespace(match.group("rest")).strip(" ,;:.")
    if not rest:
        return ""
    if rest.casefold().startswith("that "):
        rest = rest[5:].strip()
    if not rest:
        return ""
    return trim_ellipsis(rest[0].upper() + rest[1:], limit)


def _opening_stakes_line(bundle: DesignBundle, *, protagonist: PlayProtagonist) -> str:
    candidates = [
        bundle.story_bible.stakes,
        bundle.story_bible.premise,
        bundle.focused_brief.core_conflict,
    ]
    mandate_key = _normalized_sentence_key(protagonist.mandate)
    title_key = protagonist.title.casefold()
    for raw in candidates:
        if not raw or not raw.strip():
            continue
        cleaned = _clean_opening_line(
            raw,
            limit=220,
        )
        cleaned = _rewrite_role_discovery_clause(cleaned, limit=220)
        if not cleaned:
            continue
        cleaned_key = _normalized_sentence_key(cleaned)
        if cleaned_key == mandate_key:
            continue
        lowered = cleaned.casefold()
        if lowered.startswith(("when ", "during ", "while ")):
            continue
        gerund_pattern = "|".join(_MANDATE_GERUND_MAP)
        if re.match(
            rf"^(?:an?|the)\s+[^,]{{0,80}}\b(?:must|{gerund_pattern})\b",
            lowered,
            flags=re.IGNORECASE,
        ):
            continue
        if protagonist.title.casefold() in lowered and mandate_key in cleaned_key:
            continue
        if lowered.startswith(f"you are the {title_key}"):
            continue
        if lowered.startswith(f"you are {title_key}"):
            continue
        return cleaned
    return ""


def _opening_hook_line(bundle: DesignBundle, *, protagonist: PlayProtagonist) -> str:
    first_beat = bundle.beat_spine[0]
    beat_title = trim_ellipsis(first_beat.title.rstrip("."), 120)
    beat_goal = _clean_opening_line(first_beat.goal, fallback=beat_title, limit=220)
    beat_goal = _rewrite_role_discovery_clause(beat_goal, limit=220)
    beat_key = _normalized_sentence_key(beat_title)
    goal_key = _normalized_sentence_key(beat_goal)
    mandate_key = _normalized_sentence_key(protagonist.mandate)
    template_seed = f"{bundle.story_bible.title}|{beat_title}|{protagonist.title}"
    template_index = sum(ord(char) for char in template_seed) % len(_OPENING_TEMPLATE_SEEDS)
    if not beat_goal or goal_key in {beat_key, mandate_key}:
        templates = (
            f"Tonight it starts with {beat_title.lower()}.",
            f"The room is already turning around {beat_title.lower()}.",
            f"You step in with {beat_title.lower()} already underway.",
        )
        return templates[template_index]
    templates = (
        f"Tonight it starts with {beat_title.lower()}: {beat_goal}.",
        f"The room is already turning around {beat_title.lower()}: {beat_goal}.",
        f"You step in with {beat_title.lower()} already underway: {beat_goal}.",
    )
    return templates[template_index]


def _opening_narration(bundle: DesignBundle, *, protagonist: PlayProtagonist) -> str:
    title = protagonist.title.lower()
    identity = protagonist.identity_summary.rstrip(".")
    stakes_line = _opening_stakes_line(bundle, protagonist=protagonist)
    hook_line = _opening_hook_line(bundle, protagonist=protagonist)
    identity_seed = sum(ord(char) for char in f"{bundle.story_bible.title}|{protagonist.title}|{bundle.focused_brief.story_kernel}") % 3
    if identity_seed == 0:
        lead_line = identity.split(". ", 1)[0]
    elif identity_seed == 1:
        if protagonist_name := getattr(protagonist, "identity_summary", None):
            if protagonist_name.startswith("You are ") and ", the " in protagonist_name:
                name_part = protagonist_name[len("You are "):].split(", the ", 1)[0]
                lead_line = f"You are {name_part}, carrying the city's burden as {title}"
            else:
                lead_line = f"You carry the city's burden as {title}, and your mandate is to {protagonist.mandate.rstrip('.')}"
        else:
            lead_line = f"You carry the city's burden as {title}, and your mandate is to {protagonist.mandate.rstrip('.')}"
    else:
        if protagonist_name := getattr(protagonist, "identity_summary", None):
            if protagonist_name.startswith("You are ") and ", the " in protagonist_name:
                name_part = protagonist_name[len("You are "):].split(", the ", 1)[0]
                lead_line = f"As {name_part}, the {title}, you step into this crisis with one job: {protagonist.mandate.rstrip('.')}"
            else:
                lead_line = f"As the {title}, you step into this crisis with one job: {protagonist.mandate.rstrip('.')}"
        else:
            lead_line = f"As the {title}, you step into this crisis with one job: {protagonist.mandate.rstrip('.')}"
    parts = [f"{lead_line}."]
    if stakes_line:
        parts.append(f"{stakes_line}.")
    if hook_line:
        parts.append(hook_line)
    return sanitize_product_opening_narration(" ".join(part.strip() for part in parts if part.strip()), limit=4000)


def _extract_protagonist_title(bundle: DesignBundle) -> str:
    kernel = " ".join(
        part.strip()
        for part in (
            bundle.focused_brief.story_kernel or "",
            bundle.focused_brief.core_conflict or "",
            bundle.story_bible.premise or "",
            bundle.story_bible.stakes or "",
        )
        if part and part.strip()
    )
    lowered = kernel.casefold()
    role_patterns = [
        ("archivist", "Archivist"),
        ("harbor inspector", "Harbor Inspector"),
        ("inspector", "Inspector"),
        ("bridge engineer", "Bridge Engineer"),
        ("engineer", "Engineer"),
        ("ombudsman", "Ombudsman"),
        ("mediator", "Mediator"),
        ("market steward", "Market Steward"),
        ("steward", "Steward"),
    ]
    for needle, title in role_patterns:
        if needle in lowered:
            return title

    protagonist_member = bundle.story_bible.cast[0] if bundle.story_bible.cast else None
    role = normalize_whitespace((protagonist_member.role if protagonist_member is not None else "") or "").strip()
    if role and role.casefold() not in {"protagonist", "lead", "player", "mediator"} and len(role.split()) <= 4:
        return trim_ellipsis(role if any(char.isupper() for char in role) else role.title(), 120)

    role_phrase_sources = [
        bundle.focused_brief.story_kernel or "",
        bundle.focused_brief.core_conflict or "",
        bundle.focused_brief.setting_signal or "",
        bundle.story_bible.premise or "",
    ]
    role_phrase_pattern = re.compile(
        r"(?:^|[,.;:]\s*)(?:a|an)\s+([a-z][a-z -]{2,60}?)(?=\s+(?:must|tries|works|seeks|needs|has to|tasked|protects|prevents|keeps|holds|restores|proves|stabilizes|secures|contains|binds|forces)\b)",
        flags=re.IGNORECASE,
    )
    for source in role_phrase_sources:
        for match in role_phrase_pattern.finditer(source):
            phrase = normalize_whitespace(match.group(1)).strip(" ,.;:-")
            if not phrase:
                continue
            tokens = [token for token in phrase.split() if token]
            if not tokens:
                continue
            if tokens[0].casefold() in _ROLE_PREFIX_TRIM_TOKENS and len(tokens) >= 2:
                tokens = tokens[1:]
            if not tokens or tokens[0].casefold() in _ROLE_PHRASE_STOPWORDS:
                continue
            candidate = " ".join(tokens[:4]).title()
            if candidate and candidate.split()[0].casefold() not in _ROLE_PHRASE_STOPWORDS:
                return trim_ellipsis(candidate, 120)
    words = [word for word in kernel.split() if word][:3]
    return trim_ellipsis(" ".join(words).title() or "Civic Lead", 120)


def _normalize_protagonist_title(title: str) -> str:
    normalized = normalize_whitespace(title).strip(" ,.;:-")
    if not normalized:
        return normalized
    tokens = [token for token in normalized.split() if token]
    while tokens and tokens[0].casefold() in _ROLE_ARTICLES:
        tokens = tokens[1:]
    normalized = " ".join(tokens)
    if not normalized:
        return ""
    return trim_ellipsis(normalized.title(), 120)


def _is_malformed_protagonist_title(title: str) -> bool:
    normalized = normalize_whitespace(title).strip()
    if not normalized:
        return True
    tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z'-]*", normalized.casefold()) if token]
    if not tokens:
        return True
    return tokens[0] in _TITLE_PREFIX_STOPWORDS


def _fallback_protagonist_mandate(title: str, bundle: DesignBundle) -> str:
    lowered = f"{title} {bundle.focused_brief.story_kernel} {bundle.focused_brief.core_conflict}".casefold()
    if "archivist" in lowered and "warning" in lowered:
        return "prove the warning is real before the record is buried"
    if "archivist" in lowered and any(keyword in lowered for keyword in ("ration", "roll", "ledger", "blackout")):
        return "verify altered ration rolls before blackout panic turns scarcity into punishment"
    if "archivist" in lowered:
        return "protect the public record before trust hardens into panic"
    if "bridge engineer" in lowered or ("engineer" in lowered and "flood" in lowered):
        return "keep the flood defense coalition intact before the wards break apart"
    if "ombudsman" in lowered:
        return "keep the neighborhood councils from breaking apart before panic hardens into street control"
    if "harbor inspector" in lowered:
        return "keep the harbor open under public oversight before scarcity turns quarantine into factional rule"
    if "inspector" in lowered:
        return "keep emergency authority legitimate before pressure turns civic order into private rule"
    if "mediator" in lowered:
        return "keep the coalition negotiating before the crisis hardens into public fracture"
    if "steward" in lowered:
        return "hold the civic line before scarcity turns into leverage"
    return "keep civic order legitimate before the crisis hardens into fracture"


def _clean_mandate_candidate(raw: str) -> str:
    text = normalize_whitespace(raw or "").strip().rstrip(".")
    if not text:
        return ""
    for pattern in (
        r".*?\bmust\s+",
        r".*?\btasked with\s+",
        r".*?\btasked to\s+",
        r".*?\btrying to\s+",
        r".*?\bseeks to\s+",
        r".*?\bworks to\s+",
    ):
        if re.match(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
            break
    text = re.sub(
        r"^(?:an?|the)\s+[^,]{0,80}\s+(?=(?:preserving|preventing|keeping|restoring|proving|holding|stabilizing|securing|containing|binding|forcing)\b)",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(r"^must\s+", "", text, count=1, flags=re.IGNORECASE).strip()
    lowered = text.casefold()
    for gerund, base in _MANDATE_GERUND_MAP.items():
        if lowered.startswith(f"{gerund} "):
            text = f"{base} {text[len(gerund) + 1:]}"
            lowered = text.casefold()
            break
    for marker in _MANDATE_TAIL_MARKERS:
        index = lowered.find(marker)
        if index > 0:
            text = text[:index].rstrip(" ,;:.")
            lowered = text.casefold()
            break
    if lowered.startswith(("in ", "during ", "when ", "while ", "if ")):
        return ""
    if lowered.startswith(("a ", "an ", "the ")):
        return ""
    tokens = [token for token in text.split() if token]
    if tokens:
        last_token = tokens[-1].strip(" ,;:.")
        if len(last_token) == 1:
            for connector in (" before ", " to ", " while ", " after "):
                index = lowered.rfind(connector)
                if index > 0:
                    text = text[:index].rstrip(" ,;:.")
                    break
            else:
                text = " ".join(tokens[:-1]).rstrip(" ,;:.")
    return trim_ellipsis(text, 220)


def _protagonist_mandate(bundle: DesignBundle, *, title: str) -> str:
    default = _fallback_protagonist_mandate(title, bundle)
    candidates = [
        bundle.focused_brief.story_kernel,
        bundle.focused_brief.core_conflict,
        bundle.story_bible.premise,
    ]
    for raw in candidates:
        text = _clean_mandate_candidate(raw or "")
        lowered = text.casefold()
        if not text:
            continue
        if len(text.split()) > _MANDATE_MAX_WORDS:
            continue
        if any(char in text for char in ",;:"):
            continue
        if any(marker in lowered for marker in _MANDATE_NOISE_MARKERS):
            continue
        if any(lowered.startswith(f"{verb} ") or lowered == verb for verb in _MANDATE_START_VERBS):
            return text
    return default


def _compile_protagonist(bundle: DesignBundle) -> tuple[PlayProtagonist, str | None, str | None]:
    protagonist_member = bundle.story_bible.cast[0] if bundle.story_bible.cast else None
    protagonist_npc_id = protagonist_member.npc_id if protagonist_member is not None else None
    protagonist_name = protagonist_member.name if protagonist_member is not None else None
    title = _normalize_protagonist_title(_extract_protagonist_title(bundle))
    role_fallback = normalize_whitespace((protagonist_member.role if protagonist_member is not None else "") or "").strip()
    if _is_malformed_protagonist_title(title) and role_fallback:
        title = _normalize_protagonist_title(role_fallback)
    title = title or "Civic Lead"
    mandate = _protagonist_mandate(bundle, title=title)
    overlap = any(
        member is not protagonist_member and title.casefold() in member.role.casefold()
        for member in bundle.story_bible.cast
    )
    if protagonist_name:
        identity_summary = (
            f"You are {protagonist_name}, the {title.lower()}. "
            f"Your mandate is to {mandate.rstrip('.')}"
        )
    else:
        identity_summary = (
            f"You are the {title.lower()}. "
            f"Your mandate is to {mandate.rstrip('.')}"
        )
    if overlap:
        identity_summary += ". The named NPCs are rival authorities and witnesses around you, not alternate player avatars"
    identity_summary = sanitize_product_identity_summary(identity_summary, limit=320)
    return PlayProtagonist(
        title=title,
        mandate=mandate,
        identity_summary=identity_summary,
    ), protagonist_npc_id, protagonist_name


def _compress_runtime_beats(bundle: DesignBundle) -> list[BeatSpec]:
    beats = list(bundle.beat_spine)
    if len(beats) <= 1:
        return beats

    compressed_progress = [max(1, beat.progress_required) for beat in beats]
    compressed_progress[-1] = 1
    target_total_progress = max(4, len(beats) + 1)
    reduction_order = [*range(1, len(beats) - 1), 0]

    while sum(compressed_progress) > target_total_progress:
        changed = False
        for index in reduction_order:
            if compressed_progress[index] <= 1:
                continue
            compressed_progress[index] -= 1
            changed = True
            if sum(compressed_progress) <= target_total_progress:
                break
        if not changed:
            break

    return [
        beat.model_copy(update={"progress_required": compressed_progress[index]})
        for index, beat in enumerate(beats)
    ]


def compile_play_plan(*, story_id: str, bundle: DesignBundle) -> PlayPlan:
    is_relationship_drama = bundle.story_shell_id is not None
    route_pack = _compiled_route_pack(bundle)
    closeout = play_closeout_profile_from_bundle(bundle)
    runtime_policy = play_runtime_profile_from_bundle(bundle)
    author_theme = author_theme_from_bundle(bundle)
    fallback_story = build_default_story_frame_draft(bundle.focused_brief)
    protagonist, protagonist_npc_id, protagonist_name = _compile_protagonist(bundle)
    premise = sanitize_product_story_sentence(
        bundle.story_bible.premise,
        fallback=build_product_premise_fallback(
            primary_theme=author_theme.primary_theme,
            focused_brief=bundle.focused_brief,
            prompt_seed=bundle.focused_brief.story_kernel,
            limit=320,
        )
        or fallback_story.premise,
        limit=320,
    )
    axes = _compiled_axes(bundle)
    beats = _compress_runtime_beats(bundle)
    max_turns = max(4, sum(beat.progress_required for beat in beats))
    stances = [stance for stance in bundle.state_schema.stances if stance.npc_id != protagonist_npc_id]
    return PlayPlan(
        story_id=story_id,
        story_mode="relationship_drama" if is_relationship_drama else "legacy_civic",
        story_shell_id=bundle.story_shell_id,
        story_title=bundle.story_bible.title,
        protagonist=protagonist,
        protagonist_name=protagonist_name,
        protagonist_npc_id=protagonist_npc_id,
        closeout_profile="relationship_drama_default" if is_relationship_drama else closeout.play_closeout_profile,
        closeout_router_reason="normalized_seed_shell" if is_relationship_drama else closeout.router_reason,
        runtime_policy_profile="relationship_drama_default" if is_relationship_drama else runtime_policy.runtime_policy_profile,
        runtime_router_reason="normalized_seed_shell" if is_relationship_drama else runtime_policy.router_reason,
        premise=premise,
        tone=bundle.story_bible.tone,
        style_guard=bundle.story_bible.style_guard,
        cast=bundle.story_bible.cast,
        truths=bundle.story_bible.truth_catalog,
        endings=(
            [
                EndingItem(ending_id="route_lock", label="路线锁定", summary="你终于把这段关系推到了无法退回的地方。"),
                EndingItem(ending_id="bittersweet", label="苦涩成局", summary="你得到了想要的人，但代价被所有人看见。"),
                EndingItem(ending_id="breakdown", label="关系翻车", summary="秘密和关系一起爆炸，谁都没能体面退场。"),
                EndingItem(ending_id="open_loop", label="悬而未决", summary="没人真正离开，但真正的结局还没有发生。"),
            ]
            if is_relationship_drama
            else bundle.story_bible.ending_catalog
        ),
        axes=axes,
        stances=stances,
        flags=bundle.state_schema.flags,
        beats=beats,
        route_unlock_rules=route_pack.route_unlock_rules,
        ending_rules=_compiled_ending_rules(bundle),
        affordance_effect_profiles=route_pack.affordance_effect_profiles,
        available_affordance_tags=[profile.affordance_tag for profile in route_pack.affordance_effect_profiles],
        max_turns=max_turns,
        opening_narration=_opening_narration(bundle, protagonist=protagonist),
        relationship_hook=bundle.relationship_hook,
        secret_hook=bundle.secret_hook,
        route_target_ids=list(bundle.route_target_ids),
    )
