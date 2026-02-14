RULE_MAP = {
    "kind": {
        "rule_id": "R_KIND",
        "vector_delta": {"trust": 0.08, "respect": 0.05, "fear": -0.03, "attraction": 0.03},
        "score_bias": 1,
    },
    "flirt": {
        "rule_id": "R_FLIRT",
        "vector_delta": {"attraction": 0.12, "trust": 0.03},
        "score_bias": 1,
    },
    "aggressive": {
        "rule_id": "R_AGGR",
        "vector_delta": {"fear": 0.14, "trust": -0.1, "respect": -0.04},
        "score_bias": -2,
    },
    "respectful": {
        "rule_id": "R_RESPECT",
        "vector_delta": {"respect": 0.1, "trust": 0.04},
        "score_bias": 1,
    },
    "deceptive": {
        "rule_id": "R_DECEPTIVE",
        "vector_delta": {"trust": -0.12, "respect": -0.08},
        "score_bias": -2,
    },
}

VECTOR_DIMS = ["trust", "attraction", "fear", "respect"]
