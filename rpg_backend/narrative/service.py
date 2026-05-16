from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor

from rpg_backend.config import Settings, get_settings
from rpg_backend.narrative.contracts import (
    AdvanceTurnRequest,
    AdvanceTurnResponse,
    AdvisorAskRequest,
    AdvisorAskResponse,
    AdvisorHistoryResponse,
    AdvisorMessage,
    CreateTemplateRequest,
    CreateTemplateResponse,
    EndingDistributionEntry,
    EndingDistributionResponse,
    NarrativeEnding,
    NarrativeSession,
    NarrativeSessionSummary,
    NarrativeTemplate,
    NarrativeTemplateSummary,
    PlayerRole,
    PublicReplayResponse,
    SessionListResponse,
    StartSessionResponse,
    StoryHistoryResponse,
    StoryMessage,
    TemplateListResponse,
    UpdateTemplateVisibilityRequest,
)
from rpg_backend.narrative.engine import (
    advance_turn,
    ask_advisor,
    ask_advisor_oracle,
    compute_current_inventory,
    generate_opening,
    judge_failure,
    synthesize_branches,
    synthesize_early_ending,
    synthesize_ending,
    synthesize_highlights,
    tier_for_label,
)
from rpg_backend.narrative.gateway import (
    NarrativeGatewayError,
    NarrativeLLMGateway,
    get_narrative_gateway,
)
from rpg_backend.narrative.repository import NarrativeNotFoundError, NarrativeRepository


def _emit_metric(event: str, **fields: object) -> None:
    """Tag-only metric emission. Format is grep-friendly and parses as
    one event per line:
        [narrative.metric] event=template_created template_id=tmpl_xxx ...

    No external dependency — production deployment can pipe these
    through stdout to a log shipper (cloudwatch / loki / fluent) and
    aggregate later. We don't try to maintain a counter in-process
    (multi-worker would lie); just emit one line per event."""
    parts = [f"{k}={v}" for k, v in fields.items()]
    print(f"[narrative.metric] event={event} {' '.join(parts)}", flush=True)


class NarrativeServiceError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_CONTENT_MODERATION_FALLBACK = (
    "唉，刚才那段我没法接——咱俩说的事好像踩到红线了。换个角度问我？"
    "或者你想跟我聊点别的，我都在。"
)
_CONTENT_MODERATION_MARKERS = (
    "DataInspectionFailed",
    "inappropriate content",
    "data inspection failed",
)


def _is_content_moderation_failure(exc: NarrativeGatewayError) -> bool:
    if exc.status_code != 400:
        return False
    msg_lower = (exc.message or "").lower()
    return any(marker.lower() in msg_lower for marker in _CONTENT_MODERATION_MARKERS)


def _generate_template_id() -> str:
    return f"tmpl_{secrets.token_hex(6)}"


def _generate_session_id() -> str:
    return f"sess_{secrets.token_hex(6)}"


class NarrativeService:
    def __init__(
        self,
        *,
        repository: NarrativeRepository,
        gateway: NarrativeLLMGateway | None,
    ) -> None:
        self._repo = repository
        self._gateway = gateway

    @property
    def gateway(self) -> NarrativeLLMGateway:
        if self._gateway is None:
            raise NarrativeServiceError(
                code="llm_unavailable",
                message="Narrative LLM gateway is not configured.",
                status_code=500,
            )
        return self._gateway

    # ------------------------------------------------------------------
    # Template authoring
    # ------------------------------------------------------------------

    def create_template(
        self,
        request: CreateTemplateRequest,
        *,
        owner_user_id: str,
    ) -> CreateTemplateResponse:
        seed = request.seed.strip()
        if not seed:
            raise NarrativeServiceError(
                code="seed_required", message="Seed must not be empty.", status_code=422
            )
        try:
            opening = generate_opening(gateway=self.gateway, seed=seed, language=request.language)
        except NarrativeGatewayError as exc:
            raise NarrativeServiceError(
                code=exc.code, message=exc.message, status_code=exc.status_code
            ) from exc
        except ValueError as exc:
            raise NarrativeServiceError(
                code="opening_invalid",
                message=f"LLM returned an unusable opening: {exc}",
                status_code=502,
            ) from exc

        template_id = _generate_template_id()
        template = self._repo.create_template(
            template_id=template_id,
            owner_user_id=owner_user_id,
            seed=seed,
            title=opening.title,
            cast=opening.cast,
            advisor_persona=opening.advisor_persona,
            opening_passage=opening.opening_message.content,
            opening_options=opening.opening_message.options,
            player_goals=opening.player_goals,
            failure_conditions=opening.failure_conditions,
            player_role_options=opening.player_role_options,
            visibility=request.visibility,
            language=request.language,
        )

        # Auto-create the creator's session with the requested difficulty.
        # First role becomes the default — the create page doesn't pick yet.
        session, opening_message = self._spawn_session(
            template, owner_user_id, request.turn_budget, request.difficulty,
            player_role_index=0 if template.player_role_options else None,
        )

        _emit_metric(
            "template_created",
            template_id=template_id,
            owner=owner_user_id,
            visibility=request.visibility,
            language=request.language,
            turn_budget=request.turn_budget,
            difficulty=request.difficulty,
            seed_chars=len(seed),
            num_goals=len(opening.player_goals),
            num_failure_conds=len(opening.failure_conditions),
            num_player_roles=len(opening.player_role_options),
        )
        return CreateTemplateResponse(
            template=_summarize_template(template, viewer_user_id=owner_user_id),
            session=_summarize_session(session, template),
            opening=opening_message,
        )

    def list_public_templates(self, *, viewer_user_id: str) -> TemplateListResponse:
        templates = self._repo.list_public_templates()
        return TemplateListResponse(
            items=[_summarize_template(t, viewer_user_id=viewer_user_id) for t in templates]
        )

    def list_my_templates(self, *, owner_user_id: str) -> TemplateListResponse:
        templates = self._repo.list_templates_for_owner(owner_user_id)
        return TemplateListResponse(
            items=[_summarize_template(t, viewer_user_id=owner_user_id) for t in templates]
        )

    def get_template(
        self, template_id: str, *, viewer_user_id: str
    ) -> NarrativeTemplateSummary:
        template = self._load_template_for_viewer(template_id, viewer_user_id)
        return _summarize_template(template, viewer_user_id=viewer_user_id)

    def update_visibility(
        self,
        template_id: str,
        request: UpdateTemplateVisibilityRequest,
        *,
        owner_user_id: str,
    ) -> NarrativeTemplateSummary:
        template = self._load_template_for_owner(template_id, owner_user_id)
        self._repo.update_template_visibility(template_id, request.visibility)
        updated = self._repo.get_template(template_id)
        return _summarize_template(updated, viewer_user_id=owner_user_id)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(
        self,
        template_id: str,
        *,
        player_user_id: str,
        turn_budget: int = 12,
        difficulty: str = "story",
        player_role_index: int | None = None,
    ) -> StartSessionResponse:
        template = self._load_template_for_viewer(template_id, player_user_id)
        # Resolve the picked role index against template options. If the
        # template has roles but the caller didn't pick, default to 0
        # (preserves the legacy "everyone is the same default" behavior
        # while letting clients opt in per call).
        resolved_index: int | None
        if template.player_role_options:
            resolved_index = (
                player_role_index
                if player_role_index is not None
                and 0 <= player_role_index < len(template.player_role_options)
                else 0
            )
        else:
            resolved_index = None
        session, opening_message = self._spawn_session(
            template, player_user_id, turn_budget, difficulty,
            player_role_index=resolved_index,
        )
        _emit_metric(
            "session_started",
            template_id=template_id,
            session_id=session.session_id,
            player=player_user_id,
            is_owner=int(template.owner_user_id == player_user_id),
            turn_budget=turn_budget,
            difficulty=difficulty,
            player_role_index=resolved_index if resolved_index is not None else -1,
        )
        return StartSessionResponse(
            template=_summarize_template(template, viewer_user_id=player_user_id),
            session=_summarize_session(session, template),
            opening=opening_message,
        )

    def list_my_sessions(self, *, player_user_id: str) -> SessionListResponse:
        sessions = self._repo.list_sessions_for_player(player_user_id)
        # Pull templates in batch (small N expected; keep it simple).
        items: list[NarrativeSessionSummary] = []
        for s in sessions:
            try:
                template = self._repo.get_template(s.template_id)
            except NarrativeNotFoundError:
                continue
            items.append(_summarize_session(s, template))
        return SessionListResponse(items=items)

    def get_story_history(
        self, session_id: str, *, player_user_id: str
    ) -> StoryHistoryResponse:
        session = self._load_session_for_player(session_id, player_user_id)
        template = self._repo.get_template(session.template_id)
        messages = self._repo.list_story_messages(session_id)
        # turn_count derived from message stream (narrator/player pairs)
        return StoryHistoryResponse(
            template=_summarize_template(template, viewer_user_id=player_user_id),
            session=_summarize_session(session, template),
            messages=messages,
        )

    # ------------------------------------------------------------------
    # Advance a turn
    # ------------------------------------------------------------------

    def advance(
        self,
        session_id: str,
        request: AdvanceTurnRequest,
        *,
        player_user_id: str,
    ) -> AdvanceTurnResponse:
        session = self._load_session_for_player(session_id, player_user_id)
        if session.ending_label is not None:
            raise NarrativeServiceError(
                code="session_complete",
                message="这一局故事已经走完了——去看你的结局吧。",
                status_code=409,
            )
        template = self._repo.get_template(session.template_id)
        history = self._repo.list_story_messages(session_id)
        if not history:
            raise NarrativeServiceError(
                code="no_opening", message="Story has no opening yet.", status_code=409
            )
        last_narrator = next((m for m in reversed(history) if m.role == "narrator"), None)
        if last_narrator is None:
            raise NarrativeServiceError(
                code="no_narrator", message="No narrator message in history.", status_code=409
            )
        if last_narrator.chosen_option_index is not None and history[-1].role == "player":
            raise NarrativeServiceError(
                code="turn_already_advanced",
                message="The last narrator beat already has a player choice; refresh and continue.",
                status_code=409,
            )
        player_action_text, chosen_index = self._resolve_player_action(
            request, last_narrator
        )
        # Optional inner monologue. Trimmed by the contract's max_length;
        # we still defensively strip whitespace and skip empty.
        diary_text: str | None = None
        if request.diary and request.diary.strip():
            diary_text = request.diary.strip()[:600]

        # Build the player message in memory; do NOT persist until the
        # narrator beat succeeds. Avoids orphan player messages.
        next_ord = self._repo.next_story_ord(session_id)
        player_message = StoryMessage(
            ord=next_ord,
            role="player",
            content=player_action_text,
            options=[],
            chosen_option_index=chosen_index,
            diary=diary_text,
        )

        # turn_index = the index of the new narrator beat we're about to write.
        # turn_count is the number of completed narrator/player pairs so far.
        # The opening counts as turn 0; this advance produces turn_count+1.
        upcoming_turn_index = session.turn_count + 1
        is_final_turn = upcoming_turn_index >= session.turn_budget

        active_role = _resolve_player_role(template, session.selected_player_role_id)
        # Walk history to derive the sticky inventory the LLM should see
        # this turn. Source of truth = role.starting_assets + Σ(narrator
        # inventory deltas). Walk-on-read so we never desync from the
        # persisted message stream.
        starting_assets = active_role.starting_assets if active_role else []
        current_inventory = compute_current_inventory(starting_assets, history)

        try:
            turn = advance_turn(
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=history + [player_message],
                player_action=player_action_text,
                next_ord=next_ord + 1,
                turn_index=upcoming_turn_index,
                turn_budget=session.turn_budget,
                difficulty=session.difficulty,
                player_goals=template.player_goals or None,
                player_role=active_role,
                current_inventory=current_inventory or None,
                player_diary=diary_text,
                language=template.language,
            )
        except NarrativeGatewayError as exc:
            raise NarrativeServiceError(
                code=exc.code, message=exc.message, status_code=exc.status_code
            ) from exc
        except ValueError as exc:
            raise NarrativeServiceError(
                code="turn_invalid",
                message=(
                    "故事一时接不上你那一步。请稍等片刻再试一次，"
                    "或者换一个稍微贴近当前情境的动作。"
                ),
                status_code=502,
            ) from exc

        # Atomic-ish persistence: player message + chosen-option update + narrator.
        self._repo.append_story_message(session_id, player_message)
        if chosen_index is not None and last_narrator.chosen_option_index is None:
            self._repo.update_story_message_choice(
                session_id, last_narrator.ord, chosen_index
            )
        self._repo.append_story_message(session_id, turn.narrator_message)
        self._repo.touch_session(session_id, increment_turns=1)

        ending_payload: NarrativeEnding | None = None

        # Gauntlet mode: judge whether the player just tripped a failure
        # condition. If so, skip the standard finale and synthesize an
        # early collapse instead. We only run this BEFORE the natural
        # final turn — if we're already at the budget, the regular
        # finalize will handle it (and tier may end up collapsed anyway
        # via the label-tier table).
        if (
            session.difficulty == "gauntlet"
            and not is_final_turn
            and template.failure_conditions
        ):
            try:
                full_history = self._repo.list_story_messages(session_id)
                judgement = judge_failure(
                    gateway=self.gateway,
                    failure_conditions=template.failure_conditions,
                    history=full_history,
                )
            except (NarrativeGatewayError, ValueError) as exc:
                # Failure judge errors are non-fatal — log and proceed.
                print(
                    f"[narrative.service] judge_failure errored for session={session_id}: {exc}",
                    flush=True,
                )
                judgement = None
            if judgement is not None and judgement.triggered:
                ending_payload = self._finalize_session_early(
                    session_id,
                    template,
                    failure_trigger=judgement.matched_condition_label,
                    failure_reason=judgement.reason,
                    player_role=active_role,
                )

        if ending_payload is None and is_final_turn:
            ending_payload = self._finalize_session(session_id, template, player_role=active_role)

        return AdvanceTurnResponse(
            player_message=player_message,
            narrator_message=turn.narrator_message,
            ending=ending_payload,
            is_complete=ending_payload is not None,
        )

    def _finalize_session(
        self,
        session_id: str,
        template: NarrativeTemplate,
        *,
        player_role: PlayerRole | None = None,
    ) -> NarrativeEnding | None:
        """Synthesize the ending and persist it. Logs and silently no-ops on
        LLM failure — the player can still read the final narrator beat;
        the frontend will show 'ending generation failed, refresh' if it
        sees is_complete=False on a budget-reached turn."""
        full_history = self._repo.list_story_messages(session_id)
        try:
            result = synthesize_ending(
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=full_history,
                turn_count=len([m for m in full_history if m.role == "narrator"]) - 1,
                player_role=player_role,
                language=template.language,
            )
        except (NarrativeGatewayError, ValueError) as exc:
            print(
                f"[narrative.service] ending synthesis failed for session={session_id}: {exc}",
                flush=True,
            )
            return None
        tier = tier_for_label(result.label)
        # Synthesize highlights + branches AFTER ending exists. Both
        # non-fatal — return [] on any failure. Run in parallel since
        # they're independent LLM calls — cuts post-game wait from
        # ~9s sequential to ~5s.
        with ThreadPoolExecutor(max_workers=2) as pool:
            hl_future = pool.submit(
                synthesize_highlights,
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=full_history,
                ending_label=result.label,
                ending_subtitle=result.subtitle,
                player_role=player_role,
                language=template.language,
            )
            br_future = pool.submit(
                synthesize_branches,
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=full_history,
                ending_label=result.label,
                ending_tier=tier,
                ending_passage=result.passage,
                player_role=player_role,
                language=template.language,
            )
            highlights = hl_future.result()
            branches = br_future.result()
        self._repo.record_session_ending(
            session_id,
            label=result.label,
            subtitle=result.subtitle,
            passage=result.passage,
            tier=tier,  # type: ignore[arg-type]
            early_terminated=False,
            failure_trigger=None,
            highlights=highlights or None,
            branches=branches or None,
        )
        completed_session = self._repo.get_session(session_id)
        _emit_metric(
            "session_completed",
            session_id=session_id,
            template_id=template.template_id,
            ending_label=result.label,
            tier=tier,
            early=0,
            turn_count=completed_session.turn_count,
            turn_budget=completed_session.turn_budget,
            num_highlights=len(highlights),
            num_branches=len(branches),
        )
        return NarrativeEnding(
            label=result.label,
            subtitle=result.subtitle,
            passage=result.passage,
            tier=tier,  # type: ignore[arg-type]
            early_terminated=False,
            failure_trigger=None,
            highlights=highlights,
            branches=branches,
        )

    def _finalize_session_early(
        self,
        session_id: str,
        template: NarrativeTemplate,
        *,
        failure_trigger: str,
        failure_reason: str,
        player_role: PlayerRole | None = None,
    ) -> NarrativeEnding | None:
        """Gauntlet-mode collapse: judge_failure flagged a trigger this
        turn. Generate a 'collapsed' ending right now, regardless of
        turn_budget."""
        full_history = self._repo.list_story_messages(session_id)
        try:
            result = synthesize_early_ending(
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=full_history,
                failure_trigger=failure_trigger,
                failure_reason=failure_reason,
                player_role=player_role,
                language=template.language,
            )
        except (NarrativeGatewayError, ValueError) as exc:
            print(
                f"[narrative.service] early-ending synthesis failed for session={session_id}: {exc}",
                flush=True,
            )
            return None
        # Early endings are always tier=collapsed by design.
        tier = "collapsed"
        # Highlights + branches for the early collapse. Branches
        # especially valuable here — "you'd have hit a non-collapse
        # ending if you'd done X earlier" is core replay incentive.
        # Parallelize for the same latency win as the full ending path.
        with ThreadPoolExecutor(max_workers=2) as pool:
            hl_future = pool.submit(
                synthesize_highlights,
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=full_history,
                ending_label=result.label,
                ending_subtitle=result.subtitle,
                player_role=player_role,
                language=template.language,
            )
            br_future = pool.submit(
                synthesize_branches,
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=full_history,
                ending_label=result.label,
                ending_tier=tier,
                ending_passage=result.passage,
                player_role=player_role,
                language=template.language,
            )
            highlights = hl_future.result()
            branches = br_future.result()
        self._repo.record_session_ending(
            session_id,
            label=result.label,
            subtitle=result.subtitle,
            passage=result.passage,
            tier=tier,  # type: ignore[arg-type]
            early_terminated=True,
            failure_trigger=failure_trigger,
            highlights=highlights or None,
            branches=branches or None,
        )
        _emit_metric(
            "session_completed",
            session_id=session_id,
            template_id=template.template_id,
            ending_label=result.label,
            tier=tier,
            early=1,
            trigger=failure_trigger,
            turn_count=len([m for m in full_history if m.role == "narrator"]),
            turn_budget=0,
            num_highlights=len(highlights),
            num_branches=len(branches),
        )
        return NarrativeEnding(
            label=result.label,
            subtitle=result.subtitle,
            passage=result.passage,
            tier=tier,  # type: ignore[arg-type]
            early_terminated=True,
            failure_trigger=failure_trigger,
            highlights=highlights,
            branches=branches,
        )

    # ------------------------------------------------------------------
    # Ending / replay / distribution reads
    # ------------------------------------------------------------------

    def get_session_ending(
        self, session_id: str, *, player_user_id: str
    ) -> NarrativeEnding | None:
        session = self._load_session_for_player(session_id, player_user_id)
        if session.ending_label is None:
            return None
        tier = session.ending_tier or tier_for_label(session.ending_label)
        highlights = self._repo.get_session_highlights(session_id)
        branches = self._repo.get_session_branches(session_id)
        return NarrativeEnding(
            label=session.ending_label,
            subtitle=session.ending_subtitle or "",
            passage=session.ending_passage or "",
            tier=tier,  # type: ignore[arg-type]
            early_terminated=session.early_terminated,
            failure_trigger=session.failure_trigger,
            highlights=highlights,
            branches=branches,
        )

    def get_ending_distribution(
        self, template_id: str, *, viewer_user_id: str
    ) -> EndingDistributionResponse:
        # Distribution is readable for any viewer who can see the template.
        self._load_template_for_viewer(template_id, viewer_user_id)
        rows = self._repo.list_completed_endings_for_template(template_id)
        total = sum(n for _, n in rows)
        return EndingDistributionResponse(
            template_id=template_id,
            total_completed=total,
            entries=[EndingDistributionEntry(label=lbl, count=n) for lbl, n in rows],
        )

    def get_public_replay(self, session_id: str) -> PublicReplayResponse:
        """Public, auth-free read of a completed (or in-progress) session.

        Anyone with the session_id URL can see the full playthrough — that's
        the point: shareable replay URLs."""
        try:
            session = self._repo.get_session(session_id)
        except NarrativeNotFoundError as exc:
            raise NarrativeServiceError(
                code="session_not_found",
                message=f"Narrative session not found: {session_id}",
                status_code=404,
            ) from exc
        _emit_metric(
            "replay_viewed",
            session_id=session_id,
            template_id=session.template_id,
            completed=int(session.ending_label is not None),
        )
        try:
            template = self._repo.get_template(session.template_id)
        except NarrativeNotFoundError as exc:
            raise NarrativeServiceError(
                code="template_not_found",
                message=f"Template not found: {session.template_id}",
                status_code=404,
            ) from exc
        messages = self._repo.list_story_messages(session_id)
        advisor_messages = self._repo.list_advisor_messages(session_id)
        ending_payload: NarrativeEnding | None = None
        if session.ending_label is not None:
            tier = session.ending_tier or tier_for_label(session.ending_label)
            highlights = self._repo.get_session_highlights(session_id)
            branches = self._repo.get_session_branches(session_id)
            ending_payload = NarrativeEnding(
                label=session.ending_label,
                subtitle=session.ending_subtitle or "",
                passage=session.ending_passage or "",
                tier=tier,  # type: ignore[arg-type]
                early_terminated=session.early_terminated,
                failure_trigger=session.failure_trigger,
                highlights=highlights,
                branches=branches,
            )
        return PublicReplayResponse(
            session_id=session.session_id,
            template_id=session.template_id,
            template_title=template.title,
            template_seed=template.seed,
            cast=template.cast,
            advisor_persona=template.advisor_persona,
            player_goals=template.player_goals,
            player_role=_resolve_player_role(template, session.selected_player_role_id),
            turn_budget=session.turn_budget,
            turn_count=session.turn_count,
            difficulty=session.difficulty,
            completed=ending_payload is not None,
            ending=ending_payload,
            messages=messages,
            advisor_messages=advisor_messages,
            created_at=session.created_at,
        )

    # ------------------------------------------------------------------
    # Advisor side-chat
    # ------------------------------------------------------------------

    def ask_advisor(
        self,
        session_id: str,
        request: AdvisorAskRequest,
        *,
        player_user_id: str,
    ) -> AdvisorAskResponse:
        session = self._load_session_for_player(session_id, player_user_id)
        template = self._repo.get_template(session.template_id)
        question = request.question.strip()
        if not question:
            raise NarrativeServiceError(
                code="question_required",
                message="Question must not be empty.",
                status_code=422,
            )
        story_history = self._repo.list_story_messages(session_id)
        advisor_history = self._repo.list_advisor_messages(session_id)

        # Oracle mode: charge 1 turn from session.turn_budget, then call
        # the privileged-info variant of advisor. Cap-floor at 1 inside
        # the repo so we don't bottom out a session mid-asking.
        # If session is already complete, oracle is rejected.
        is_oracle = bool(request.oracle_mode)
        if is_oracle and session.ending_label is not None:
            raise NarrativeServiceError(
                code="session_complete",
                message="这一局已经走完了，不能再消耗回合换情报。",
                status_code=409,
            )

        reply_text: str | None = None
        try:
            if is_oracle:
                # Resolve the active player_role for privileged context.
                active_role = _resolve_player_role(template, session.selected_player_role_id)
                starting_assets = active_role.starting_assets if active_role else []
                current_inventory = compute_current_inventory(starting_assets, story_history)
                reply = ask_advisor_oracle(
                    gateway=self.gateway,
                    seed=template.seed,
                    title=template.title,
                    cast=template.cast,
                    advisor_persona=template.advisor_persona,
                    story_history=story_history,
                    advisor_history=advisor_history,
                    question=question,
                    player_role=active_role,
                    failure_conditions=template.failure_conditions or None,
                    current_inventory=current_inventory or None,
                    language=template.language,
                )
            else:
                reply = ask_advisor(
                    gateway=self.gateway,
                    seed=template.seed,
                    title=template.title,
                    cast=template.cast,
                    advisor_persona=template.advisor_persona,
                    story_history=story_history,
                    advisor_history=advisor_history,
                    question=question,
                    language=template.language,
                )
            reply_text = reply.reply_text
        except NarrativeGatewayError as exc:
            if _is_content_moderation_failure(exc):
                reply_text = _CONTENT_MODERATION_FALLBACK
            else:
                raise NarrativeServiceError(
                    code=exc.code, message=exc.message, status_code=exc.status_code
                ) from exc
        except ValueError as exc:
            raise NarrativeServiceError(
                code="advisor_invalid",
                message=f"LLM returned an unusable advisor reply: {exc}",
                status_code=502,
            ) from exc

        assert reply_text is not None
        next_ord = self._repo.next_advisor_ord(session_id)
        player_message = AdvisorMessage(ord=next_ord, role="player", content=question)
        advisor_message = AdvisorMessage(
            ord=next_ord + 1, role="advisor", content=reply_text
        )
        self._repo.append_advisor_message(session_id, player_message)
        self._repo.append_advisor_message(session_id, advisor_message)
        self._repo.touch_session(session_id)

        # Charge the oracle cost AFTER the LLM call succeeds — don't
        # decrement budget if the call failed.
        new_budget: int | None = None
        if is_oracle:
            new_budget = self._repo.decrement_turn_budget(session_id, by=1)
            _emit_metric(
                "advisor_oracle_used",
                session_id=session_id,
                template_id=template.template_id,
                new_budget=new_budget,
            )
        _emit_metric(
            "advisor_used",
            session_id=session_id,
            template_id=template.template_id,
            oracle=int(is_oracle),
        )

        return AdvisorAskResponse(
            player_message=player_message,
            advisor_message=advisor_message,
            turn_budget_after=new_budget,
            oracle_used=is_oracle,
        )

    def get_advisor_history(
        self, session_id: str, *, player_user_id: str
    ) -> AdvisorHistoryResponse:
        session = self._load_session_for_player(session_id, player_user_id)
        template = self._repo.get_template(session.template_id)
        messages = self._repo.list_advisor_messages(session_id)
        return AdvisorHistoryResponse(
            persona=template.advisor_persona,
            messages=messages,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _spawn_session(
        self,
        template: NarrativeTemplate,
        player_user_id: str,
        turn_budget: int = 12,
        difficulty: str = "story",
        *,
        player_role_index: int | None = None,
    ) -> tuple[NarrativeSession, StoryMessage]:
        session_id = _generate_session_id()
        # Cast difficulty into the typed Literal — defensive; service-layer
        # callers may pass anything, but only the two values are valid.
        norm_difficulty: str = "gauntlet" if difficulty == "gauntlet" else "story"
        # Resolve which role_id this session is locked to. None when the
        # template was created before player roles existed (legacy).
        selected_role_id: str | None = None
        if (
            player_role_index is not None
            and 0 <= player_role_index < len(template.player_role_options)
        ):
            selected_role_id = template.player_role_options[player_role_index].role_id
        session = self._repo.create_session(
            session_id=session_id,
            template_id=template.template_id,
            player_user_id=player_user_id,
            turn_budget=turn_budget,
            difficulty=norm_difficulty,  # type: ignore[arg-type]
            selected_player_role_id=selected_role_id,
        )
        opening_message = StoryMessage(
            ord=0,
            role="narrator",
            content=template.opening_passage,
            options=template.opening_options,
            chosen_option_index=None,
        )
        self._repo.append_story_message(session_id, opening_message)
        self._repo.increment_play_count(template.template_id)
        return session, opening_message

    def _load_template_for_viewer(
        self, template_id: str, viewer_user_id: str
    ) -> NarrativeTemplate:
        try:
            template = self._repo.get_template(template_id)
        except NarrativeNotFoundError as exc:
            raise NarrativeServiceError(
                code="template_not_found",
                message=f"Narrative template not found: {template_id}",
                status_code=404,
            ) from exc
        if template.visibility == "private" and template.owner_user_id != viewer_user_id:
            raise NarrativeServiceError(
                code="template_forbidden",
                message="This template is private.",
                status_code=403,
            )
        return template

    def _load_template_for_owner(
        self, template_id: str, owner_user_id: str
    ) -> NarrativeTemplate:
        template = self._load_template_for_viewer(template_id, owner_user_id)
        if template.owner_user_id != owner_user_id:
            raise NarrativeServiceError(
                code="template_forbidden",
                message="Only the template creator can do this.",
                status_code=403,
            )
        return template

    def _load_session_for_player(
        self, session_id: str, player_user_id: str
    ) -> NarrativeSession:
        try:
            session = self._repo.get_session(session_id)
        except NarrativeNotFoundError as exc:
            raise NarrativeServiceError(
                code="session_not_found",
                message=f"Narrative session not found: {session_id}",
                status_code=404,
            ) from exc
        if session.player_user_id != player_user_id:
            raise NarrativeServiceError(
                code="session_forbidden",
                message="You do not own this play session.",
                status_code=403,
            )
        return session

    @staticmethod
    def _resolve_player_action(
        request: AdvanceTurnRequest, last_narrator: StoryMessage
    ) -> tuple[str, int | None]:
        if request.free_input and request.free_input.strip():
            return request.free_input.strip(), None
        idx = request.chosen_option_index
        if idx is None:
            raise NarrativeServiceError(
                code="action_required",
                message="Provide either chosen_option_index or free_input.",
                status_code=422,
            )
        if idx < 0 or idx >= len(last_narrator.options):
            raise NarrativeServiceError(
                code="option_out_of_range",
                message=f"chosen_option_index {idx} is out of range.",
                status_code=422,
            )
        option = last_narrator.options[idx]
        return option.label, idx


def _resolve_player_role(
    template: NarrativeTemplate, role_id: str | None
) -> PlayerRole | None:
    """Find the PlayerRole for a session's selected_player_role_id.

    Returns None if the session has no role pinned (legacy) or the role
    no longer exists on the template (defensive — shouldn't happen in
    practice).
    """
    if role_id is None or not template.player_role_options:
        return None
    for role in template.player_role_options:
        if role.role_id == role_id:
            return role
    return None


def _summarize_template(
    template: NarrativeTemplate, *, viewer_user_id: str
) -> NarrativeTemplateSummary:
    return NarrativeTemplateSummary(
        template_id=template.template_id,
        owner_user_id=template.owner_user_id,
        seed=template.seed,
        title=template.title,
        cast=template.cast,
        advisor_persona=template.advisor_persona,
        player_goals=template.player_goals,
        failure_conditions=template.failure_conditions,
        player_role_options=template.player_role_options,
        visibility=template.visibility,
        language=template.language,
        play_count=template.play_count,
        created_at=template.created_at,
        is_owner=(template.owner_user_id == viewer_user_id),
    )


def _summarize_session(
    session: NarrativeSession, template: NarrativeTemplate
) -> NarrativeSessionSummary:
    return NarrativeSessionSummary(
        session_id=session.session_id,
        template_id=session.template_id,
        template_title=template.title,
        template_seed=template.seed,
        player_user_id=session.player_user_id,
        turn_count=session.turn_count,
        turn_budget=session.turn_budget,
        difficulty=session.difficulty,
        player_role=_resolve_player_role(template, session.selected_player_role_id),
        ending_label=session.ending_label,
        ending_subtitle=session.ending_subtitle,
        ending_tier=session.ending_tier,
        early_terminated=session.early_terminated,
        created_at=session.created_at,
        last_active_at=session.last_active_at,
    )


def get_narrative_service(settings: Settings | None = None) -> NarrativeService:
    resolved = settings or get_settings()
    repo = NarrativeRepository(resolved.runtime_state_db_path)
    gateway = get_narrative_gateway(resolved)
    return NarrativeService(repository=repo, gateway=gateway)
