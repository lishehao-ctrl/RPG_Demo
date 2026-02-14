from app.modules.branch.dsl import eval_expr


def build_branch_context(session_obj, char_states: list) -> dict:
    flags = {}
    flags.update(session_obj.global_flags or {})
    flags.update(session_obj.route_flags or {})

    characters = {}
    for cs in char_states:
        key = str(cs.character_id)
        characters[key] = {
            "score_visible": cs.score_visible,
            "relation": cs.relation_vector or {},
        }

    return {"flags": flags, "characters": characters}


def resolve_branch(branches: list, ctx: dict):
    if not branches:
        return None, []

    hits = []
    for b in branches:
        matched = eval_expr(b.rule_expr, ctx)
        hits.append({"branch_id": str(b.id), "matched": matched, "priority": b.priority})

    matched = [b for b in branches if eval_expr(b.rule_expr, ctx)]
    matched.sort(key=lambda x: x.priority, reverse=True)

    if matched:
        top = matched[0]
        if top.is_exclusive:
            return top, hits
        return top, hits

    defaults = [b for b in branches if b.is_default]
    defaults.sort(key=lambda x: x.priority, reverse=True)
    return (defaults[0] if defaults else None), hits
