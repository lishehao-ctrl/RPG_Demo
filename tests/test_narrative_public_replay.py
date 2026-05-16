from __future__ import annotations

from rpg_backend.narrative.contracts import (
    CastMember,
    FailureCondition,
    PlayerGoal,
    PlayerRole,
    StoryMessage,
    StoryOption,
)
from rpg_backend.narrative.repository import NarrativeRepository
from rpg_backend.narrative.service import NarrativeService


def _create_template_and_session(
    repo: NarrativeRepository,
    *,
    template_id: str,
    session_id: str,
    visibility: str = "public",
    difficulty: str = "story",
    turn_budget: int = 12,
    failure_conditions: list[FailureCondition] | None = None,
) -> None:
    options = [
        StoryOption(label="Let the witness speak", hint="Trade control for trust", handle="witness")
    ]
    repo.create_template(
        template_id=template_id,
        owner_user_id="usr_owner",
        seed="A cofounder announces the secret merger before the audit is ready.",
        title="Merger Test",
        cast=[
            CastMember(
                character_id="mira",
                display_name="Mira",
                role="Cofounder",
                relation_to_protagonist="Player role",
            ),
            CastMember(
                character_id="evan",
                display_name="Evan",
                role="Witness",
                relation_to_protagonist="Former partner with leverage",
            )
        ],
        advisor_persona="A calm strategy coach.",
        opening_passage="The control room goes quiet.",
        opening_options=options,
        player_goals=[
            PlayerGoal(goal="Keep the vote alive", stakes="The company may collapse.")
        ],
        player_role_options=[
            PlayerRole(
                role_id="founder",
                label="Founder",
                public_persona="Cofounder under pressure",
                hidden_objective="Keep the audit from becoming a cover-up.",
            )
        ],
        failure_conditions=failure_conditions or [],
        visibility=visibility,  # type: ignore[arg-type]
        language="en",
    )
    repo.create_session(
        session_id=session_id,
        template_id=template_id,
        player_user_id="local-dev",
        turn_budget=turn_budget,
        difficulty=difficulty,  # type: ignore[arg-type]
        selected_player_role_id="founder",
    )
    repo.append_story_message(
        session_id,
        StoryMessage(
            ord=0,
            role="narrator",
            content="The control room goes quiet.",
            options=options,
            chosen_option_index=0,
        ),
    )


def test_public_replay_includes_template_id_for_fork_cta(tmp_path) -> None:
    repo = NarrativeRepository(str(tmp_path / "runtime.sqlite3"))
    service = NarrativeService(repository=repo, gateway=None)
    template_id = "tmpl_replay_fork"
    session_id = "sess_replay_fork"
    _create_template_and_session(repo, template_id=template_id, session_id=session_id)

    replay = service.get_public_replay(session_id)

    assert replay.session_id == session_id
    assert replay.template_id == template_id
    assert replay.template_forkable is True
    assert replay.template_title == "Merger Test"
    assert replay.messages[0].chosen_option_index == 0


def test_public_replay_marks_private_templates_as_not_forkable(tmp_path) -> None:
    repo = NarrativeRepository(str(tmp_path / "runtime.sqlite3"))
    service = NarrativeService(repository=repo, gateway=None)
    _create_template_and_session(
        repo,
        template_id="tmpl_private_replay",
        session_id="sess_private_replay",
        visibility="private",
    )

    replay = service.get_public_replay("sess_private_replay")

    assert replay.template_id == "tmpl_private_replay"
    assert replay.template_forkable is False


def test_advance_quota_estimate_reserves_finalization_operations(tmp_path) -> None:
    repo = NarrativeRepository(str(tmp_path / "runtime.sqlite3"))
    service = NarrativeService(repository=repo, gateway=None)
    _create_template_and_session(
        repo,
        template_id="tmpl_final_cost",
        session_id="sess_final_cost",
        turn_budget=4,
    )
    repo.touch_session("sess_final_cost", increment_turns=3)

    assert service.estimate_advance_llm_operation_cost(
        "sess_final_cost",
        player_user_id="local-dev",
    ) == 4


def test_advance_quota_estimate_reserves_gauntlet_failure_path(tmp_path) -> None:
    repo = NarrativeRepository(str(tmp_path / "runtime.sqlite3"))
    service = NarrativeService(repository=repo, gateway=None)
    _create_template_and_session(
        repo,
        template_id="tmpl_gauntlet_cost",
        session_id="sess_gauntlet_cost",
        difficulty="gauntlet",
        turn_budget=8,
        failure_conditions=[
            FailureCondition(
                label="Public Threat",
                description="The player threatens violence in public.",
            )
        ],
    )
    repo.touch_session("sess_gauntlet_cost", increment_turns=2)

    assert service.estimate_advance_llm_operation_cost(
        "sess_gauntlet_cost",
        player_user_id="local-dev",
    ) == 5
