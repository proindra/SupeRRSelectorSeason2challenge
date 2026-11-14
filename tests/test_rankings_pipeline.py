from __future__ import annotations

import pandas as pd

from suprr.metrics.batter import calculate_batter_metrics
from suprr.metrics.bowler import calculate_bowler_metrics
from suprr.ranking.rankings import rank_batters, rank_bowlers


def _states() -> pd.DataFrame:
    rows = []
    for player_index, (striker, bowler) in enumerate([("b1", "w1"), ("b2", "w2")]):
        for high, count in [(True, 18), (False, 10)]:
            for ball in range(count):
                wicket = high and ball == player_index
                runs = (2 if player_index else 1) if high and ball < 12 else (0 if high else 1)
                rows.append(
                    {
                        "competition_id": "c1",
                        "comparison_group": "IPL",
                        "match_id": f"{striker}-{int(high)}",
                        "striker_id": striker,
                        "bowler_id": bowler,
                        "batter_runs": runs,
                        "extras_category": "None",
                        "extras_1": 0,
                        "extras_2": 0,
                        "is_high_pressure": high,
                        "pressure_score": 0.7 if high else 0.3,
                        "is_live_chase": True,
                        "phase": "death",
                        "is_four": bool(high and ball == 1 and player_index == 1),
                        "is_six": bool(high and ball == 2 and player_index == 1),
                        "dismissed_player_id": striker if wicket else None,
                        "dismissal_type": "Bowled" if wicket else None,
                        "wicket_flag": wicket,
                    }
                )
    return pd.DataFrame(rows)


def test_competition_aware_batter_and_bowler_scores_are_calculated(config):
    samples = config.samples.model_copy(update={"batter_pressure_innings": 1})
    config = config.model_copy(update={"samples": samples})
    states = _states()
    batter_metrics = calculate_batter_metrics(states, config)
    batter_metrics["comparison_group"] = "IPL"
    batter_grouped, batter_scores = rank_batters(batter_metrics, states, config)
    assert set(batter_scores["striker_id"]) == {"b1", "b2"}
    assert batter_scores["composite_score"].notna().all()
    assert (
        batter_grouped["strike_rate_change"]
        == batter_grouped["pressure_strike_rate"] - batter_grouped["normal_strike_rate"]
    ).all()

    bowler_metrics = calculate_bowler_metrics(states, config)
    bowler_metrics["comparison_group"] = "IPL"
    bowler_grouped, bowler_scores = rank_bowlers(bowler_metrics, states, config)
    assert set(bowler_scores["bowler_id"]) == {"w1", "w2"}
    assert bowler_scores["composite_score"].notna().all()
    assert (
        bowler_grouped["economy_improvement"]
        == bowler_grouped["normal_economy"] - bowler_grouped["pressure_economy"]
    ).all()
