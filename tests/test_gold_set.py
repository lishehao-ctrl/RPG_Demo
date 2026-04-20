from __future__ import annotations

from collections import Counter

from tools.urban_author_play_benchmarks.gold_set import (
    LONG_ARC_REQUIRED_SHELLS,
    LONG_ARC_SHORT_SEED_KEYWORDS,
    burst_pressure_realistic_20,
    mini_gold_realistic_6,
    v1_topic_gold_realistic_10,
)


def _band_distribution(cases) -> dict[str, int]:  # noqa: ANN001
    counter = Counter(str(case.expected_band) for case in cases)
    return {
        "5_8": int(counter.get("5_8", 0)),
        "8_15": int(counter.get("8_15", 0)),
        "15_25": int(counter.get("15_25", 0)),
    }


def _preset_distribution(cases) -> dict[str, int]:  # noqa: ANN001
    counter = Counter(str(case.expected_play_length_preset or "") for case in cases)
    return {
        "15_20": int(counter.get("15_20", 0)),
        "20_25": int(counter.get("20_25", 0)),
        "30_45": int(counter.get("30_45", 0)),
    }


def _assert_no_short_arc_seed_keywords(cases) -> None:  # noqa: ANN001
    for case in cases:
        compact_seed = str(case.seed).replace(" ", "")
        for keyword in LONG_ARC_SHORT_SEED_KEYWORDS:
            assert keyword not in compact_seed, f"unexpected short-arc keyword `{keyword}` in `{case.case_id}`"


def _assert_shell_coverage(cases) -> None:  # noqa: ANN001
    shell_set = {str(case.expected_shell) for case in cases}
    assert set(LONG_ARC_REQUIRED_SHELLS).issubset(shell_set)


def test_mini_gold_realistic_6_long_arc_distribution_and_seed_language() -> None:
    cases = mini_gold_realistic_6()
    assert len(cases) == 6
    assert _band_distribution(cases) == {"5_8": 0, "8_15": 0, "15_25": 6}
    assert _preset_distribution(cases) == {"15_20": 1, "20_25": 2, "30_45": 3}
    assert len({case.case_id for case in cases}) == 6
    _assert_shell_coverage(cases)
    _assert_no_short_arc_seed_keywords(cases)


def test_v1_topic_gold_realistic_10_long_arc_distribution_and_seed_language() -> None:
    cases = v1_topic_gold_realistic_10()
    assert len(cases) == 10
    assert _band_distribution(cases) == {"5_8": 0, "8_15": 0, "15_25": 10}
    assert _preset_distribution(cases) == {"15_20": 2, "20_25": 3, "30_45": 5}
    assert len({case.case_id for case in cases}) == 10
    _assert_shell_coverage(cases)
    _assert_no_short_arc_seed_keywords(cases)


def test_burst_pressure_realistic_20_long_arc_distribution_and_seed_language() -> None:
    cases = burst_pressure_realistic_20()
    assert len(cases) == 20
    assert _band_distribution(cases) == {"5_8": 0, "8_15": 0, "15_25": 20}
    assert _preset_distribution(cases) == {"15_20": 4, "20_25": 6, "30_45": 10}
    assert len({case.case_id for case in cases}) == 20
    _assert_shell_coverage(cases)
    _assert_no_short_arc_seed_keywords(cases)
