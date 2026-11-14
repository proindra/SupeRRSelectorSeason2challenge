from __future__ import annotations

import pandas as pd

from suprr.config import AppConfig
from suprr.ranking.rankings import (
    BATTER_WEIGHTS,
    BOWLER_WEIGHTS,
    rank_batters,
    rank_bowlers,
)


def _score_variants(
    grouped: pd.DataFrame,
    player_column: str,
    exposure_column: str,
    variants: dict[str, dict[str, float]],
) -> pd.DataFrame:
    from suprr.ranking.scoring import competition_weighted_score

    outputs = []
    for variant, weights in variants.items():
        scores = competition_weighted_score(
            grouped,
            player_column=player_column,
            competition_column="comparison_group",
            exposure_column=exposure_column,
            weights=weights,
        )
        scores["variant"] = variant
        outputs.append(scores)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def batter_sensitivity(
    metrics: pd.DataFrame,
    states: pd.DataFrame,
    config: AppConfig,
) -> pd.DataFrame:
    grouped, _ = rank_batters(metrics, states, config)
    variants = {
        "base_raw_pressure_runs": BATTER_WEIGHTS,
        "exclude_raw_pressure_runs": {
            key: value for key, value in BATTER_WEIGHTS.items() if key != "pressure_runs"
        },
        "runs_per_eligible_innings": {
            **{key: value for key, value in BATTER_WEIGHTS.items() if key != "pressure_runs"},
            "runs_per_pressure_innings": 0.15,
        },
    }
    grouped = grouped.copy()
    grouped["runs_per_pressure_innings"] = grouped["pressure_runs"] / grouped[
        "pressure_innings"
    ].replace(0, pd.NA)
    return _score_variants(grouped, "striker_id", "pressure_balls", variants)


def bowler_sensitivity(
    metrics: pd.DataFrame,
    states: pd.DataFrame,
    config: AppConfig,
) -> pd.DataFrame:
    grouped, _ = rank_bowlers(metrics, states, config)
    no_wickets = {key: value for key, value in BOWLER_WEIGHTS.items() if key != "pressure_wickets"}
    rate_wickets = {
        **no_wickets,
        "wickets_per_100_legal_balls": BOWLER_WEIGHTS["pressure_wickets"],
    }
    no_regularised = {
        key: value
        for key, value in BOWLER_WEIGHTS.items()
        if key not in {"regularised_bowling_average", "regularised_bowling_strike_rate"}
    }
    grouped = grouped.copy()
    grouped["wickets_per_100_legal_balls"] = (
        100 * grouped["pressure_wickets"] / grouped["legal_pressure_balls"]
    )
    variants = {
        "base_raw_pressure_wickets": BOWLER_WEIGHTS,
        "exclude_raw_pressure_wickets": no_wickets,
        "wickets_per_100_legal_balls": rate_wickets,
        "exclude_regularised_average_and_strike_rate": no_regularised,
    }
    return _score_variants(grouped, "bowler_id", "legal_pressure_balls", variants)
