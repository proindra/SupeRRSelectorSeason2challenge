from __future__ import annotations

import pandas as pd

from suprr.metrics.batter import calculate_batter_metrics
from suprr.metrics.bowler import calculate_bowler_metrics


def _batter_states() -> pd.DataFrame:
    rows = []
    for match_id, runs, balls in [("m1", 0, 6), ("m2", 2, 12)]:
        for _ in range(balls):
            rows.append(
                {
                    "competition_id": "c1",
                    "match_id": match_id,
                    "striker_id": "b1",
                    "bowler_id": "w1",
                    "batter_runs": runs,
                    "extras_category": "None",
                    "extras_1": 0,
                    "extras_2": 0,
                    "is_high_pressure": True,
                    "pressure_score": 0.7,
                    "is_live_chase": True,
                    "phase": "death",
                    "is_four": False,
                    "is_six": False,
                    "dismissed_player_id": None,
                    "dismissal_type": None,
                    "wicket_flag": False,
                }
            )
    rows.append(
        {
            "competition_id": "c1",
            "match_id": "m1",
            "striker_id": "b1",
            "bowler_id": "w1",
            "batter_runs": 0,
            "extras_category": "wide",
            "extras_1": 1,
            "extras_2": 0,
            "is_high_pressure": True,
            "pressure_score": 0.7,
            "is_live_chase": True,
            "phase": "death",
            "is_four": False,
            "is_six": False,
            "dismissed_player_id": None,
            "dismissal_type": None,
            "wicket_flag": False,
        }
    )
    return pd.DataFrame(rows)


def test_batter_wides_excluded_and_consistency_is_ball_weighted(config):
    metrics = calculate_batter_metrics(_batter_states(), config)
    row = metrics.iloc[0]
    assert row["pressure_balls"] == 18
    assert row["pressure_innings"] == 2
    assert row["pressure_runs"] == 24
    assert row["consistency"] == 12 / 18
    assert row["qualifying_innings"] == 1


def test_bowler_charges_wides_no_balls_and_credits_only_mapped_wickets(config):
    rows = []
    extras = [
        ("None", 1, 0, 0, None, False),
        ("wide", 0, 1, 0, None, False),
        ("no_ball", 2, 1, 0, None, False),
        ("byes", 0, 0, 2, None, False),
        ("legbyes", 0, 1, 0, "RunOut", True),
        ("None", 0, 0, 0, "Bowled", True),
        ("None", 0, 0, 0, None, False),
        ("None", 0, 0, 0, None, False),
    ]
    for category, batter, extra_1, extra_2, dismissal, wicket in extras:
        rows.append(
            {
                "competition_id": "c1",
                "match_id": "m1",
                "striker_id": "b1",
                "bowler_id": "w1",
                "batter_runs": batter,
                "extras_category": category,
                "extras_1": extra_1,
                "extras_2": extra_2,
                "is_high_pressure": True,
                "pressure_score": 0.7,
                "is_live_chase": True,
                "phase": "death",
                "is_four": False,
                "is_six": False,
                "dismissed_player_id": "b1" if wicket else None,
                "dismissal_type": dismissal,
                "wicket_flag": wicket,
            }
        )
    metrics = calculate_bowler_metrics(pd.DataFrame(rows), config)
    row = metrics.iloc[0]
    assert row["pressure_conceded_runs"] == 5
    assert row["legal_pressure_balls"] == 6
    assert row["pressure_wickets"] == 1
    assert row["dots"] == 3
