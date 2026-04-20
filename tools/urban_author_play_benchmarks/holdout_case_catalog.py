from __future__ import annotations

import random

from tools.urban_author_play_benchmarks.gold_set import UrbanGoldCase


def _replace_terms(text: str, replacements: tuple[tuple[str, str], ...]) -> str:
    updated = text
    for source, target in replacements:
        updated = updated.replace(source, target)
    return updated


def _shell_seed_rewrite(seed: str, shell_id: str) -> str:
    shell_replacements: dict[str, tuple[tuple[str, str], ...]] = {
        "wealth_families": (
            ("豪门", "家族核心圈"),
            ("站队", "认边"),
            ("当众", "在人前"),
        ),
        "office_power": (
            ("董事会", "会议桌"),
            ("背锅", "扛责"),
            ("站队", "认边"),
        ),
        "entertainment_scandal": (
            ("热搜", "榜单风向"),
            ("直播", "公屏直播"),
            ("翻车", "失手"),
        ),
        "campus_romance": (
            ("校园", "校内熟人圈"),
            ("评审", "评审席"),
            ("站队", "选边"),
        ),
    }
    replacements = shell_replacements.get(shell_id, ())
    if not replacements:
        return seed
    return _replace_terms(seed, replacements)


def _relationship_wording_rewrite(seed: str) -> str:
    replacements = (
        ("女主", "主角"),
        ("前任", "旧暧昧对象"),
        ("旧爱", "旧关系对象"),
        ("最体面的", "最会撑场面的"),
    )
    return _replace_terms(seed, replacements)


def _frame_wording_rewrite(seed: str) -> str:
    replacements = (
        ("当众", "在人前"),
        ("公开", "在场面里"),
        ("私下", "背着人"),
        ("标准局", "常规局"),
    )
    return _replace_terms(seed, replacements)


def _perturb_seed(seed: str, *, shell_id: str, rng: random.Random) -> str:
    transforms = [
        lambda text: _shell_seed_rewrite(text, shell_id),
        _relationship_wording_rewrite,
        _frame_wording_rewrite,
    ]
    rng.shuffle(transforms)
    updated = seed
    for transform in transforms:
        updated = transform(updated)
    return updated


def build_holdout_case_catalog(
    base_cases: list[UrbanGoldCase],
    *,
    seed: int = 20260401,
    variants_per_case: int = 2,
) -> list[UrbanGoldCase]:
    holdout_cases: list[UrbanGoldCase] = []
    for case_index, case in enumerate(base_cases):
        for variant_index in range(variants_per_case):
            rng = random.Random(seed + case_index * 97 + variant_index * 11)
            perturbed_seed = _perturb_seed(case.seed, shell_id=case.expected_shell, rng=rng)
            holdout_cases.append(
                case.model_copy(
                    update={
                        "case_id": f"{case.case_id}_holdout_{variant_index + 1}",
                        "seed": perturbed_seed,
                    }
                )
            )
    return holdout_cases
