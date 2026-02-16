from app.modules.branch.dsl import eval_expr_trace


def build_branch_context(session_obj, char_states: list) -> dict:
    flags = {}
    flags.update(session_obj.global_flags or {})
    flags.update(session_obj.route_flags or {})

    characters = {}
    for cs in sorted(char_states, key=lambda c: str(c.character_id)):
        char_id = str(cs.character_id)
        relation = cs.relation_vector or {}
        characters[char_id] = {
            'score_visible': cs.score_visible,
            'relation': relation,
            'trust': relation.get('trust', 0.0),
            'attraction': relation.get('attraction', 0.0),
            'fear': relation.get('fear', 0.0),
            'respect': relation.get('respect', 0.0),
        }

    return {'flags': flags, 'characters': characters}


def resolve_branch(branches: list, ctx: dict):
    if not branches:
        return None, []

    evaluations = []
    for branch in sorted(branches, key=lambda b: (b.priority, str(b.id)), reverse=True):
        matched, trace = eval_expr_trace(branch.rule_expr, ctx)
        evaluations.append(
            {
                'branch_id': str(branch.id),
                'route_type': branch.route_type,
                'priority': branch.priority,
                'is_exclusive': bool(branch.is_exclusive),
                'is_default': bool(branch.is_default),
                'matched': matched,
                'trace': trace,
            }
        )

    matched = [b for b in evaluations if b['matched']]
    chosen_eval = None
    if matched:
        chosen_eval = sorted(matched, key=lambda x: (x['priority'], x['branch_id']), reverse=True)[0]
    else:
        defaults = [b for b in evaluations if b['is_default']]
        if defaults:
            chosen_eval = sorted(defaults, key=lambda x: (x['priority'], x['branch_id']), reverse=True)[0]

    chosen_branch = None
    if chosen_eval:
        chosen_id = chosen_eval['branch_id']
        for branch in branches:
            if str(branch.id) == chosen_id:
                chosen_branch = branch
                break

    return chosen_branch, evaluations
