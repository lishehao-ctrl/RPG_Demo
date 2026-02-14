def eval_expr(expr: dict, ctx: dict) -> bool:
    if not expr:
        return False
    op = expr.get("op")

    if op == "and":
        return all(eval_expr(e, ctx) for e in expr.get("args", []))
    if op == "or":
        return any(eval_expr(e, ctx) for e in expr.get("args", []))

    if op == "flag":
        return ctx.get("flags", {}).get(expr.get("key")) == expr.get("value")

    left_path = expr.get("left")
    left = _resolve(ctx, left_path)
    right = expr.get("right")

    if op == "gte":
        return left is not None and left >= right
    if op == "lte":
        return left is not None and left <= right
    if op == "eq":
        return left == right
    if op == "contains":
        if left is None:
            return False
        return right in left
    if op == "between":
        lo, hi = expr.get("range", [None, None])
        return left is not None and lo <= left <= hi

    return False


def _resolve(ctx: dict, path: str):
    if not path:
        return None
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur
