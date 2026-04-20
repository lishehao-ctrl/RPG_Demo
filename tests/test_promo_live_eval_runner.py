from __future__ import annotations

import pytest

from tools.urban_author_play_benchmarks.promo_live_eval_runner import run_promo_live_eval


def test_promo_live_eval_runner_is_deprecated() -> None:
    with pytest.raises(RuntimeError, match="已下线"):
        run_promo_live_eval(output_dir=None)  # type: ignore[arg-type]
