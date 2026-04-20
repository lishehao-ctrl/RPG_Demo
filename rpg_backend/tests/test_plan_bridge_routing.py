from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rpg_backend.author.contracts import RelationshipMoveFamily
from rpg_backend.author_v3.plan_bridge import _build_semantic_strategy_pack


def test_plan_bridge_cost_routing_matrix_covers_all_move_families() -> None:
    strategy_pack = _build_semantic_strategy_pack("office_power", [])
    rules_by_family = {rule.move_family: rule for rule in strategy_pack.cost_routing_matrix.rules}
    expected_families = set(get_args(RelationshipMoveFamily))

    assert set(rules_by_family) == expected_families
    assert rules_by_family["accuse"].rule_id == "default_cost_route"
    assert rules_by_family["accuse"].route_kind == "immediate_cost"
