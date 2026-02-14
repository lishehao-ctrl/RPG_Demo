from app.modules.affection.engine import apply_affection


def test_affection_saturation_boundaries() -> None:
    out = apply_affection(
        current_score_visible=50,
        relation_vector={"trust": 0.95, "attraction": 0.95, "fear": -0.95, "respect": 0.95},
        drift={"trust": 0.5, "attraction": 0.5, "fear": -0.5, "respect": 0.5},
        behavior_tags=["kind", "flirt", "respectful"],
    )
    assert all(-1.0 <= v <= 1.0 for v in out["new_relation_vector"].values())
    assert all(-1.0 <= v <= 1.0 for v in out["new_drift"].values())
    assert 0 <= out["new_score_visible"] <= 100


def test_affection_drift_decay() -> None:
    out = apply_affection(
        current_score_visible=50,
        relation_vector={"trust": 0.0, "attraction": 0.0, "fear": 0.0, "respect": 0.0},
        drift={"trust": 1.0, "attraction": 1.0, "fear": 1.0, "respect": 1.0},
        behavior_tags=[],
    )
    assert out["new_drift"]["trust"] == 0.9
    assert out["new_drift"]["fear"] == 0.9


def test_affection_deterministic() -> None:
    kwargs = dict(
        current_score_visible=40,
        relation_vector={"trust": 0.1, "attraction": 0.0, "fear": 0.1, "respect": 0.2},
        drift={"trust": 0.1, "attraction": 0.0, "fear": 0.0, "respect": 0.1},
        behavior_tags=["kind", "respectful"],
    )
    a = apply_affection(**kwargs)
    b = apply_affection(**kwargs)
    assert a == b


def test_affection_score_mapping_boundaries() -> None:
    high = apply_affection(
        current_score_visible=50,
        relation_vector={"trust": 1.0, "attraction": 1.0, "fear": -1.0, "respect": 1.0},
        drift={"trust": 0.0, "attraction": 0.0, "fear": 0.0, "respect": 0.0},
        behavior_tags=[],
    )
    low = apply_affection(
        current_score_visible=50,
        relation_vector={"trust": -1.0, "attraction": -1.0, "fear": 1.0, "respect": -1.0},
        drift={"trust": 0.0, "attraction": 0.0, "fear": 0.0, "respect": 0.0},
        behavior_tags=[],
    )
    assert high["new_score_visible"] >= 90
    assert low["new_score_visible"] <= 10
