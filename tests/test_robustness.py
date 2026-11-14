from __future__ import annotations

import pandas as pd

from suprr.robustness.bootstrap import match_level_bootstrap
from suprr.robustness.scenarios import build_scenario_grid


def test_scenario_grid_is_reproducible_and_marks_unverified_revised_cases(config):
    scenarios = build_scenario_grid(config)
    assert scenarios[0]["scenario_id"] == "base"
    revised = next(item for item in scenarios if item["dimension"] == "revised_targets")
    assert revised["status"] == "skipped_unverified"


def test_match_bootstrap_is_deterministic(config):
    frame = pd.DataFrame(
        [
            {"match_id": f"m{match}", "player": f"p{match % 2}", "value": match}
            for match in range(10)
        ]
    )

    def evaluate(sample: pd.DataFrame) -> pd.DataFrame:
        result = sample.groupby("player", as_index=False)["value"].mean()
        result["composite_score"] = result["value"]
        result["rank"] = result["value"].rank(method="min", ascending=False)
        return result[["player", "composite_score", "rank"]]

    first = match_level_bootstrap(
        frame,
        evaluate,
        player_column="player",
        replicates=500,
        seed=config.random_seed,
    )
    second = match_level_bootstrap(
        frame,
        evaluate,
        player_column="player",
        replicates=500,
        seed=config.random_seed,
    )
    pd.testing.assert_frame_equal(first, second)
