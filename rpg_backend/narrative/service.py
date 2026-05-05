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
    CreateNarrativeWorldRequest,
    CreateNarrativeWorldResponse,
    NarrativeWorldSummary,
    StoryHistoryResponse,
    StoryMessage,
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


def _generate_world_id() -> str:
    return f"world_{secrets.token_hex(6)}"


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
    # World creation
    # ------------------------------------------------------------------

    def create_world(
        self,
        request: CreateNarrativeWorldRequest,
        *,
        owner_user_id: str,
    ) -> CreateNarrativeWorldResponse:
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

        world_id = _generate_world_id()
        world = self._repo.create_world(
            world_id=world_id,
            owner_user_id=owner_user_id,
            seed=seed,
            title=opening.title,
            cast=opening.cast,
            advisor_persona=opening.advisor_persona,
        )
        self._repo.append_story_message(world_id, opening.opening_message)
        return CreateNarrativeWorldResponse(
            world=_summarize_world(world, turn_count=1),
            opening=opening.opening_message,
        )

    # ------------------------------------------------------------------
    # Story history
    # ------------------------------------------------------------------

    def get_story_history(
        self, world_id: str, *, owner_user_id: str
    ) -> StoryHistoryResponse:
        world = self._load_world(world_id, owner_user_id=owner_user_id)
        messages = self._repo.list_story_messages(world_id)
        return StoryHistoryResponse(
            world=_summarize_world(world, turn_count=len(messages)),
            messages=messages,
        )

    # ------------------------------------------------------------------
    # Advance a turn
    # ------------------------------------------------------------------

    def advance(
        self,
        world_id: str,
        request: AdvanceTurnRequest,
        *,
        owner_user_id: str,
    ) -> AdvanceTurnResponse:
        world = self._load_world(world_id, owner_user_id=owner_user_id)
        history = self._repo.list_story_messages(world_id)
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

        # Build the player message in memory, but DO NOT persist it yet.
        # If the narrator generation fails (LLM JSON corrupt, retries
        # exhausted, etc.) we don't want the user's choice sitting in the
        # database as an orphan with no narrator response — they should be
        # able to retry the same turn cleanly.
        next_ord = self._repo.next_story_ord(world_id)
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
                seed=world.seed,
                title=world.title,
                cast=world.cast,
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

        # Narrator succeeded — now persist both messages atomically.
        self._repo.append_story_message(world_id, player_message)
        if chosen_index is not None and last_narrator.chosen_option_index is None:
            updated = last_narrator.model_copy(
                update={"chosen_option_index": chosen_index}
            )
            self._update_story_message(world_id, updated)
        self._repo.append_story_message(world_id, turn.narrator_message)

        return AdvanceTurnResponse(
            player_message=player_message,
            narrator_message=turn.narrator_message,
        )

    # ------------------------------------------------------------------
    # Advisor side-chat
    # ------------------------------------------------------------------

    def ask_advisor(
        self,
        world_id: str,
        request: AdvisorAskRequest,
        *,
        owner_user_id: str,
    ) -> AdvisorAskResponse:
        world = self._load_world(world_id, owner_user_id=owner_user_id)
        question = request.question.strip()
        if not question:
            raise NarrativeServiceError(
                code="question_required",
                message="Question must not be empty.",
                status_code=422,
            )
        story_history = self._repo.list_story_messages(world_id)
        advisor_history = self._repo.list_advisor_messages(world_id)

        reply_text: str | None = None
        try:
            reply = ask_advisor(
                gateway=self.gateway,
                seed=world.seed,
                title=world.title,
                cast=world.cast,
                advisor_persona=world.advisor_persona,
                story_history=story_history,
                advisor_history=advisor_history,
                question=question,
            )
            reply_text = reply.reply_text
        except NarrativeGatewayError as exc:
            # Provider-side content moderation (Aliyun's
            # InternalError.Algo.DataInspectionFailed) trips when the
            # accumulated story context contains terms the moderator
            # flags as sensitive — even though the question itself is
            # innocuous. Rather than 500 the chat, fall back to an
            # in-character "I can't go there" message and persist it so
            # the conversation flow stays intact.
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
        next_ord = self._repo.next_advisor_ord(world_id)
        player_message = AdvisorMessage(ord=next_ord, role="player", content=question)
        advisor_message = AdvisorMessage(
            ord=next_ord + 1, role="advisor", content=reply_text
        )
        self._repo.append_advisor_message(world_id, player_message)
        self._repo.append_advisor_message(world_id, advisor_message)
        return AdvisorAskResponse(
            player_message=player_message,
            advisor_message=advisor_message,
        )

    def get_advisor_history(
        self, world_id: str, *, owner_user_id: str
    ) -> AdvisorHistoryResponse:
        world = self._load_world(world_id, owner_user_id=owner_user_id)
        messages = self._repo.list_advisor_messages(world_id)
        return AdvisorHistoryResponse(
            persona=world.advisor_persona,
            messages=messages,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_world(self, world_id: str, *, owner_user_id: str):
        try:
            world = self._repo.get_world(world_id)
        except NarrativeNotFoundError as exc:
            raise NarrativeServiceError(
                code="world_not_found",
                message=f"Narrative world not found: {world_id}",
                status_code=404,
            ) from exc
        if world.owner_user_id != owner_user_id:
            raise NarrativeServiceError(
                code="world_forbidden",
                message="You do not own this narrative world.",
                status_code=403,
            )
        return world

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

    def _update_story_message(self, world_id: str, message: StoryMessage) -> None:
        # Hot-fix: rewrite chosen_option_index on the matching narrator message.
        with self._repo._connect() as conn:  # noqa: SLF001  (intentional)
            conn.execute(
                """
                UPDATE narrative_story_messages
                SET chosen_option_index = ?
                WHERE world_id = ? AND ord = ?
                """,
                (message.chosen_option_index, world_id, message.ord),
            )
            conn.commit()


def _summarize_world(world, *, turn_count: int) -> NarrativeWorldSummary:
    return NarrativeWorldSummary(
        world_id=world.world_id,
        seed=world.seed,
        title=world.title,
        cast=world.cast,
        advisor_persona=world.advisor_persona,
        turn_count=turn_count,
        created_at=world.created_at,
    )


def get_narrative_service(settings: Settings | None = None) -> NarrativeService:
    resolved = settings or get_settings()
    repo = NarrativeRepository(resolved.runtime_state_db_path)
    gateway = get_narrative_gateway(resolved)
    return NarrativeService(repository=repo, gateway=gateway)
