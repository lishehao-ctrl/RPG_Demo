import pytest

from rpg_backend.play_v2.contracts import HookState, UrbanWorldState


def test_hook_state_defaults():
    h = HookState(hook_id="a__b__s1", holder_id="a", target_id="b", source_secret_id="s1", leverage_type="blackmail")
    assert h.status == "dormant"
    assert h.leverage_value == 0.0


def test_hook_state_status_enum():
    for status in ["dormant", "suspected", "active", "leveraged", "detonated"]:
        h = HookState(hook_id="x__y__s", holder_id="x", target_id="y", source_secret_id="s", leverage_type="t", status=status)
        assert h.status == status


def test_hook_state_invalid_status():
    with pytest.raises(Exception):
        HookState(hook_id="x__y__s", holder_id="x", target_id="y", source_secret_id="s", leverage_type="t", status="invalid")


def test_urban_world_state_default_hook_states():
    state = UrbanWorldState.model_construct(hook_states={})
    assert state.hook_states == {}


def test_urban_world_state_custom_hook_states():
    h = HookState(hook_id="a__b__s1", holder_id="a", target_id="b", source_secret_id="s1", leverage_type="leverage")
    state = UrbanWorldState.model_construct(hook_states={"a__b__s1": h})
    assert "a__b__s1" in state.hook_states
