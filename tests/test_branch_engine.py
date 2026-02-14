from types import SimpleNamespace

from app.modules.branch.engine import build_branch_context, resolve_branch


class BranchObj(SimpleNamespace):
    pass


def test_branch_threshold_boundary() -> None:
    sess = SimpleNamespace(global_flags={}, route_flags={})
    cs = [SimpleNamespace(character_id="char1", score_visible=60, relation_vector={"trust": 0.5})]
    ctx = build_branch_context(sess, cs)
    b = BranchObj(id="b1", rule_expr={"op": "gte", "left": "characters.char1.score_visible", "right": 60}, priority=1, is_exclusive=False, is_default=False)
    chosen, _ = resolve_branch([b], ctx)
    assert chosen.id == "b1"


def test_branch_priority_and_exclusive() -> None:
    sess = SimpleNamespace(global_flags={}, route_flags={})
    cs = [SimpleNamespace(character_id="c", score_visible=80, relation_vector={"fear": 0.2})]
    ctx = build_branch_context(sess, cs)
    b1 = BranchObj(id="low", rule_expr={"op": "gte", "left": "characters.c.score_visible", "right": 50}, priority=10, is_exclusive=False, is_default=False)
    b2 = BranchObj(id="high", rule_expr={"op": "gte", "left": "characters.c.score_visible", "right": 70}, priority=20, is_exclusive=True, is_default=False)
    chosen, _ = resolve_branch([b1, b2], ctx)
    assert chosen.id == "high"


def test_branch_default_path() -> None:
    sess = SimpleNamespace(global_flags={"x": False}, route_flags={})
    cs = [SimpleNamespace(character_id="c", score_visible=10, relation_vector={})]
    ctx = build_branch_context(sess, cs)
    nohit = BranchObj(id="n", rule_expr={"op": "flag", "key": "x", "value": True}, priority=10, is_exclusive=True, is_default=False)
    default = BranchObj(id="d", rule_expr={"op": "eq", "left": "flags.x", "right": True}, priority=0, is_exclusive=False, is_default=True)
    chosen, _ = resolve_branch([nohit, default], ctx)
    assert chosen.id == "d"
