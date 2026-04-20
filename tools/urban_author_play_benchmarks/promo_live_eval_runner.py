from __future__ import annotations

import argparse
from pathlib import Path

DEPRECATION_MESSAGE = (
    "promo_live_eval_runner 已下线。请改用 mini/full 统一入口: "
    "python -m tools.urban_author_play_benchmarks.gold_eval_mini_runner 或 "
    "python -m tools.urban_author_play_benchmarks.gold_eval_full_runner"
)


def run_promo_live_eval(*args, **kwargs):  # noqa: ANN002, ANN003, ANN201
    raise RuntimeError(DEPRECATION_MESSAGE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=DEPRECATION_MESSAGE)
    parser.add_argument("--output-dir", required=False, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _ = parse_args(argv)
    raise SystemExit(DEPRECATION_MESSAGE)


if __name__ == "__main__":
    raise SystemExit(main())
