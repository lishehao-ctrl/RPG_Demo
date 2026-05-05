from __future__ import annotations

import secrets

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
    NarrativeSession,
    NarrativeSessionSummary,
    NarrativeTemplate,
    NarrativeTemplateSummary,
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
    generate_opening,
)
from rpg_backend.narrative.gateway import (
    NarrativeGatewayError,
    NarrativeLLMGateway,
    get_narrative_gateway,
)
from rpg_backend.narrative.repository import NarrativeNotFoundError, NarrativeRepository


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
            opening = generate_opening(gateway=self.gateway, seed=seed)
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
            visibility=request.visibility,
        )

        # Auto-create the creator's session.
        session, opening_message = self._spawn_session(template, owner_user_id)

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
        self, template_id: str, *, player_user_id: str
    ) -> StartSessionResponse:
        template = self._load_template_for_viewer(template_id, player_user_id)
        session, opening_message = self._spawn_session(template, player_user_id)
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

        # Build the player message in memory; do NOT persist until the
        # narrator beat succeeds. Avoids orphan player messages.
        next_ord = self._repo.next_story_ord(session_id)
        player_message = StoryMessage(
            ord=next_ord,
            role="player",
            content=player_action_text,
            options=[],
            chosen_option_index=chosen_index,
        )

        try:
            turn = advance_turn(
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                history=history + [player_message],
                player_action=player_action_text,
                next_ord=next_ord + 1,
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

        return AdvanceTurnResponse(
            player_message=player_message,
            narrator_message=turn.narrator_message,
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

        reply_text: str | None = None
        try:
            reply = ask_advisor(
                gateway=self.gateway,
                seed=template.seed,
                title=template.title,
                cast=template.cast,
                advisor_persona=template.advisor_persona,
                story_history=story_history,
                advisor_history=advisor_history,
                question=question,
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
        return AdvisorAskResponse(
            player_message=player_message,
            advisor_message=advisor_message,
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
        self, template: NarrativeTemplate, player_user_id: str
    ) -> tuple[NarrativeSession, StoryMessage]:
        session_id = _generate_session_id()
        session = self._repo.create_session(
            session_id=session_id,
            template_id=template.template_id,
            player_user_id=player_user_id,
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
        visibility=template.visibility,
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
        created_at=session.created_at,
        last_active_at=session.last_active_at,
    )


def get_narrative_service(settings: Settings | None = None) -> NarrativeService:
    resolved = settings or get_settings()
    repo = NarrativeRepository(resolved.runtime_state_db_path)
    gateway = get_narrative_gateway(resolved)
    return NarrativeService(repository=repo, gateway=gateway)
