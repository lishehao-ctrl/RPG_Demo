def _resolve(ctx: dict, path: str):
    if not path:
        return None
    cur = ctx
    for part in path.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _eval_leaf(op: str, expr: dict, ctx: dict) -> tuple[bool, dict]:
    if op == 'flag':
        actual = ctx.get('flags', {}).get(expr.get('key'))
        expected = expr.get('value')
        result = actual == expected
        return result, {
            'op': op,
            'key': expr.get('key'),
            'expected': expected,
            'actual_value': actual,
            'result': result,
        }

    left_path = expr.get('left')
    actual = _resolve(ctx, left_path)
    right = expr.get('right')

    if op == 'gte':
        result = actual is not None and actual >= right
    elif op == 'lte':
        result = actual is not None and actual <= right
    elif op == 'eq':
        result = actual == right
    elif op == 'contains':
        result = actual is not None and right in actual
    elif op == 'between':
        lo, hi = expr.get('range', [None, None])
        right = {'min': lo, 'max': hi}
        result = actual is not None and lo <= actual <= hi
    else:
        result = False

    trace = {
        'op': op,
        'left': left_path,
        'right': right,
        'actual_value': actual,
        'result': result,
    }
    return result, trace


def eval_expr_trace(expr: dict, ctx: dict) -> tuple[bool, dict]:
    if not expr:
        return False, {'op': 'invalid', 'result': False}

    op = expr.get('op')
    if op in {'and', 'or'}:
        children = []
        child_results = []
        for child in expr.get('args', []):
            child_result, child_trace = eval_expr_trace(child, ctx)
            child_results.append(child_result)
            children.append(child_trace)
        result = all(child_results) if op == 'and' else any(child_results)
        return result, {'op': op, 'children': children, 'result': result}

    return _eval_leaf(op, expr, ctx)


def eval_expr(expr: dict, ctx: dict) -> bool:
    result, _ = eval_expr_trace(expr, ctx)
    return result
