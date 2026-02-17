import uuid

from app.modules.session.action_compiler import ActionCompiler


def test_action_compiler_invalid_input_uses_deterministic_fallback() -> None:
    compiler = ActionCompiler(confidence_threshold=0.7)
    session_state = {
        'active_characters': [str(uuid.uuid4())],
        'character_lookup': {},
        'route_flags': {},
    }

    out = compiler.compile('??? random gibberish', session_state)

    assert out.proposed_action is None
    assert out.fallback_used is True
    assert out.final_action['action_id'] == 'clarify'
    assert out.reasons == ['UNMAPPED_INPUT']
    assert out.confidence == 0.0


def test_action_compiler_date_target_locked_falls_back_with_reason() -> None:
    compiler = ActionCompiler(confidence_threshold=0.7)
    unlocked = str(uuid.uuid4())
    locked = str(uuid.uuid4())
    session_state = {
        'active_characters': [unlocked],
        'character_lookup': {'alice': locked},
        'route_flags': {},
    }

    out = compiler.compile('date alice', session_state)

    assert out.proposed_action == {'action_id': 'date', 'params': {'target': locked}}
    assert out.fallback_used is True
    assert out.final_action == {'action_id': 'rest', 'params': {}}
    assert 'TARGET_LOCKED' in out.reasons
