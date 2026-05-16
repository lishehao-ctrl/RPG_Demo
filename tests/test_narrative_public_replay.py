from __future__ import annotations

from rpg_backend.narrative.contracts import (
    CastMember,
    PlayerGoal,
    PlayerRole,
    StoryMessage,
    StoryOption,
)
from rpg_backend.narrative.repository import NarrativeRepository
from rpg_backend.narrative.service import NarrativeService


def test_public_replay_includes_template_id_for_fork_cta(tmp_path) -> None:
    repo = NarrativeRepository(str(tmp_path / "runtime.sqlite3"))
    service = NarrativeService(repository=repo, gateway=None)
    template_id = "tmpl_replay_fork"
    session_id = "sess_replay_fork"
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
        failure_conditions=[],
        player_role_options=[
            PlayerRole(
                role_id="founder",
                label="Founder",
                public_persona="Cofounder under pressure",
                hidden_objective="Keep the audit from becoming a cover-up.",
            )
        ],
        visibility="public",
        language="en",
    )
    repo.create_session(
        session_id=session_id,
        template_id=template_id,
        player_user_id="local-dev",
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

    replay = service.get_public_replay(session_id)

    assert replay.session_id == session_id
    assert replay.template_id == template_id
    assert replay.template_title == "Merger Test"
    assert replay.messages[0].chosen_option_index == 0
