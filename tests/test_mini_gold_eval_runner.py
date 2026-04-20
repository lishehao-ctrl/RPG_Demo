from __future__ import annotations

import pytest

from tools.urban_author_play_benchmarks import mini_gold_eval_runner


def test_mini_gold_eval_runner_is_deprecated() -> None:
    with pytest.raises(RuntimeError, match="已下线"):
        mini_gold_eval_runner.run_merged_mini_gold_eval(output_dir=None)  # type: ignore[arg-type]
