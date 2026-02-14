from app.modules.affection.rules import RULE_MAP, VECTOR_DIMS


VECTOR_WEIGHTS = {
    "trust": 18.0,
    "respect": 12.0,
    "attraction": 10.0,
    "fear": -14.0,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _normalize_vector(vector: dict) -> dict:
    return {k: float(_clamp(vector.get(k, 0.0), -1.0, 1.0)) for k in VECTOR_DIMS}


def _map_vector_to_score(vector: dict, score_bias: float = 0.0) -> int:
    # deterministic mapping centered at 50
    raw = 50.0 + sum(vector[k] * VECTOR_WEIGHTS[k] for k in VECTOR_DIMS) + score_bias
    return int(round(_clamp(raw, 0.0, 100.0)))


def apply_affection(current_score_visible: int, relation_vector: dict, drift: dict, behavior_tags: list[str]):
    relation_vector = _normalize_vector(relation_vector)
    drift = _normalize_vector(drift or {})

    vector_delta = {k: 0.0 for k in VECTOR_DIMS}
    score_bias = 0.0
    rule_hits: list[dict] = []

    for tag in behavior_tags:
        rule = RULE_MAP.get(tag)
        if not rule:
            continue
        per_rule_delta = {k: 0.0 for k in VECTOR_DIMS}
        for dim, d in rule["vector_delta"].items():
            per_rule_delta[dim] += d
            vector_delta[dim] += d
        score_bias += float(rule.get("score_bias", 0.0))
        rule_hits.append(
            {
                "rule_id": rule["rule_id"],
                "tag": tag,
                "vector_delta": per_rule_delta,
                "score_bias": float(rule.get("score_bias", 0.0)),
            }
        )

    # apply saturation
    new_vector = {}
    for dim in VECTOR_DIMS:
        new_vector[dim] = _clamp(relation_vector[dim] + vector_delta[dim], -1.0, 1.0)

    # drift decay + tiny update from this step delta
    new_drift = {}
    for dim in VECTOR_DIMS:
        new_drift[dim] = _clamp((drift[dim] * 0.9) + (vector_delta[dim] * 0.1), -1.0, 1.0)

    effective_vector = {dim: _clamp(new_vector[dim] + new_drift[dim], -1.0, 1.0) for dim in VECTOR_DIMS}
    new_score = _map_vector_to_score(effective_vector, score_bias=score_bias)
    new_score = int(_clamp(new_score, 0, 100))
    score_delta = new_score - int(current_score_visible)

    return {
        "new_score_visible": new_score,
        "new_relation_vector": new_vector,
        "new_drift": new_drift,
        "rule_hits": rule_hits,
        "vector_delta": vector_delta,
        "score_delta": score_delta,
    }
