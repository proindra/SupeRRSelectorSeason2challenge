from __future__ import annotations

import numpy as np
import pandas as pd

from suprr.ranking.rankings import (
    BATTER_WEIGHTS,
    BOWLER_WEIGHTS,
    _aggregate_player_groups,
    _pooled_rates_many,
    _shrink_rows,
)
from suprr.validation.ranking_quality import (
    _resample_matches,
    _summarize_bootstrap,
    mathematical_consistency_checks,
)


def _batter_frame() -> pd.DataFrame:
    row: dict[str, object] = {
        "output_label": "EXPLORATORY",
        "striker_id": "b1",
        "pressure_runs": 30,
        "pressure_balls": 20,
        "pressure_strike_rate": 150.0,
        "pressure_strike_rate_shrunk": 140.0,
        "normal_strike_rate": 100.0,
        "strike_rate_change": 50.0,
        "strike_rate_change_shrunk": 40.0,
        "fours": 2,
        "sixes": 1,
        "boundary_rate": 15.0,
        "boundary_rate_shrunk": 12.0,
        "dots": 5,
        "dot_ball_rate": 25.0,
        "dot_ball_rate_shrunk": 22.0,
        "dismissals": 1,
        "dismissal_rate": 5.0,
        "dismissal_rate_shrunk": 4.0,
        "consistency": 0.75,
        "complete_metrics": True,
        "composite_score": 0.0,
        "rank": 1.0,
    }
    row.update({f"{metric}_weighted_z": 0.0 for metric in BATTER_WEIGHTS})
    return pd.DataFrame([row])


def _bowler_frame() -> pd.DataFrame:
    row: dict[str, object] = {
        "output_label": "EXPLORATORY",
        "bowler_id": "w1",
        "pressure_wickets": 2,
        "pressure_conceded_runs": 18,
        "legal_pressure_balls": 12,
        "pressure_economy": 9.0,
        "pressure_economy_shrunk": 9.5,
        "dots": 3,
        "dot_ball_rate": 25.0,
        "dot_ball_rate_shrunk": 24.0,
        "fours": 1,
        "sixes": 1,
        "boundary_conceded_rate": 16.666666666666668,
        "boundary_conceded_rate_shrunk": 17.0,
        "regularised_bowling_average": 6.0,
        "regularised_bowling_strike_rate": 4.0,
        "wickets_per_100_legal_balls": 16.666666666666668,
        "normal_economy": 10.0,
        "economy_improvement": 1.0,
        "economy_improvement_shrunk": 0.5,
        "consistency": 0.75,
        "complete_metrics": True,
        "composite_score": 0.0,
        "rank": 1.0,
    }
    row.update({f"{metric}_weighted_z": 0.0 for metric in BOWLER_WEIGHTS})
    return pd.DataFrame([row])


def test_batter_formula_and_composite_checks_pass() -> None:
    full = _batter_frame()
    checks = mathematical_consistency_checks(full, full.copy(), "batter")

    formula_checks = checks.loc[checks["check_id"].ne("top10_count")]
    assert formula_checks["status"].eq("VALIDATED").all()


def test_bowler_formula_check_detects_corrupt_metric() -> None:
    full = _bowler_frame()
    full.loc[0, "pressure_economy"] = 8.0
    checks = mathematical_consistency_checks(full, full.copy(), "bowler")

    result = checks.set_index("check_id")
    assert result.loc["pressure_economy_identity", "status"] == "FAILED"


def test_bootstrap_top10_probability_uses_total_replicates() -> None:
    replicate_rows = pd.DataFrame(
        [
            {
                "role": "batter",
                "scope": "IPL",
                "player_id": "b1",
                "replicate": replicate,
                "rank": rank,
                "composite_score": 1.0 / rank,
                "pressure_metric_value": 150.0,
                "pressure_metric_name": "pressure_strike_rate",
            }
            for replicate, rank in enumerate([1.0, 12.0, 12.0])
        ]
    )
    baseline = pd.DataFrame([{"striker_id": "b1", "rank": 1.0, "composite_score": 1.0}])
    result = _summarize_bootstrap(
        replicate_rows,
        role="batter",
        scope="IPL",
        candidates=["b1", "b2"],
        baseline=baseline,
        names={"b1": "Batter One"},
        replicate_count=4,
        confidence_level=0.90,
    ).set_index("player_id")

    assert result.loc["b1", "top10_inclusion_probability"] == 0.25
    assert result.loc["b2", "top10_inclusion_probability"] == 0.0


def test_match_bootstrap_resamples_each_competition_stratum() -> None:
    states = pd.DataFrame(
        [
            {"match_id": "i1", "comparison_group": "IPL", "delivery": 1},
            {"match_id": "i1", "comparison_group": "IPL", "delivery": 2},
            {"match_id": "i2", "comparison_group": "IPL", "delivery": 1},
            {"match_id": "t1", "comparison_group": "T20I", "delivery": 1},
            {"match_id": "t2", "comparison_group": "T20I", "delivery": 1},
        ]
    )

    sampled = _resample_matches(states, np.random.default_rng(42), 0)
    match_counts = sampled.groupby("comparison_group")["match_id"].nunique().to_dict()

    assert match_counts == {"IPL": 2, "T20I": 2}


def test_vectorized_player_aggregation_preserves_exposure_weighted_rate() -> None:
    metrics = pd.DataFrame(
        [
            {"group": "IPL", "player": "p1", "balls": 10, "runs": 15, "rate": 1.0},
            {"group": "IPL", "player": "p1", "balls": 20, "runs": 20, "rate": 0.5},
            {"group": "T20I", "player": "p1", "balls": 10, "runs": 5, "rate": np.nan},
        ]
    )

    result = _aggregate_player_groups(
        metrics,
        player_column="player",
        comparison_group_column="group",
        sum_columns=["balls", "runs"],
        rate_columns=["rate"],
        exposure_column="balls",
    ).set_index("group")

    assert result.loc["IPL", "balls"] == 30
    assert result.loc["IPL", "runs"] == 35
    assert result.loc["IPL", "rate"] == 2 / 3
    assert result.loc["T20I", "rate"] == 0.0


def test_batched_pooled_rates_respect_pressure_and_chase_masks() -> None:
    states = pd.DataFrame(
        [
            {
                "group": "IPL",
                "is_high_pressure": True,
                "is_live_chase": True,
                "runs": 4,
                "balls": 1,
            },
            {
                "group": "IPL",
                "is_high_pressure": False,
                "is_live_chase": True,
                "runs": 2,
                "balls": 1,
            },
            {
                "group": "IPL",
                "is_high_pressure": False,
                "is_live_chase": False,
                "runs": 8,
                "balls": 1,
            },
        ]
    )

    result = _pooled_rates_many(
        states,
        "group",
        {
            "pressure": (True, "runs", "balls"),
            "normal_chase": (False, "runs", "balls"),
        },
    )

    assert result["pressure"]["IPL"] == (4.0, 1.0)
    assert result["normal_chase"]["IPL"] == (2.0, 1.0)


def test_vectorized_shrinkage_matches_exposure_and_league_weighting() -> None:
    frame = pd.DataFrame(
        [
            {"group": "IPL", "runs": 20, "balls": 10},
            {"group": "IPL", "runs": 40, "balls": 20},
        ]
    )

    result = _shrink_rows(
        frame,
        group_column="group",
        numerator="runs",
        denominator="balls",
        baseline={"IPL": (100.0, 100.0)},
        k=10,
        scale=100,
    )

    np.testing.assert_allclose(result.to_numpy(), [150.0, 166.66666666666666])
