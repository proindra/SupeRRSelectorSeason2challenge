from __future__ import annotations

import pandas as pd

from suprr.ranking.eligibility import apply_combined_eligibility, exclude_players
from suprr.ranking.scoring import competition_weighted_score
from suprr.ranking.shrinkage import shrink_rate


def test_shrinkage_uses_player_exposure_and_pooled_rate():
    assert shrink_rate(2, 10, 100, 200, 10) == 0.35


def test_eligibility_combines_samples_across_comparison_groups():
    frame = pd.DataFrame(
        [
            {"player": "p1", "group": "IPL", "balls": 30, "innings": 4},
            {"player": "p1", "group": "T20I", "balls": 30, "innings": 4},
        ]
    )
    result = apply_combined_eligibility(
        frame,
        player_column="player",
        exposure_column="balls",
        count_column="innings",
        minimum_exposure=60,
        minimum_count=8,
    )
    assert result["eligible"].all()


def test_exclude_players_removes_only_listed_player_ids():
    frame = pd.DataFrame(
        [
            {"player": "eligible", "group": "IPL"},
            {"player": "excluded", "group": "T20I"},
        ]
    )

    result = exclude_players(
        frame,
        player_column="player",
        excluded_player_ids={"excluded"},
    )

    assert result[["player", "group"]].to_dict("records") == [
        {"player": "eligible", "group": "IPL"}
    ]


def test_score_orients_metrics_and_preserves_missing_values():
    frame = pd.DataFrame(
        [
            {
                "player": "better",
                "group": "IPL",
                "balls": 100,
                "eligible": True,
                "rate": 10.0,
                "economy": 2.0,
            },
            {
                "player": "worse",
                "group": "IPL",
                "balls": 100,
                "eligible": True,
                "rate": 5.0,
                "economy": 5.0,
            },
            {
                "player": "missing",
                "group": "IPL",
                "balls": 100,
                "eligible": True,
                "rate": None,
                "economy": 4.0,
            },
        ]
    )
    result = competition_weighted_score(
        frame,
        player_column="player",
        competition_column="group",
        exposure_column="balls",
        weights={"rate": 1.0, "economy": -1.0},
    ).set_index("player")
    assert result.loc["better", "rank"] == 1
    assert not result.loc["missing", "complete_metrics"]
    assert pd.isna(result.loc["missing", "composite_score"])
