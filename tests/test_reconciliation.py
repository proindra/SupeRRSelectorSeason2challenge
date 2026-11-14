from __future__ import annotations

import pandas as pd

from suprr.schemas import SourceTables
from suprr.validation.reconciliation import build_reconciliation


def _sources() -> SourceTables:
    deliveries = pd.DataFrame(
        [
            {
                "match_id": "m1",
                "innings": "1",
                "striker_id": "p1",
                "bowler_id": "b1",
                "runs": "4",
                "extras1_runs": "0",
                "extras_2_runs": "0",
                "extras_type": "None",
                "is_wicket": "false",
            },
            {
                "match_id": "m1",
                "innings": "2",
                "striker_id": "p2",
                "bowler_id": "b2",
                "runs": "0",
                "extras1_runs": "1",
                "extras_2_runs": "0",
                "extras_type": "Overstep",
                "is_wicket": "false",
            },
        ]
    )
    matches = pd.DataFrame(
        [
            {
                "match_id": "m1",
                "result": "Team 2 won",
                "revised_target": pd.NA,
                "first_inn_revised_overs": pd.NA,
                "second_inn_revised_overs": pd.NA,
            }
        ]
    )
    return {"deliveries": deliveries, "matches": matches}


def test_candidate_totals_are_not_marked_as_reconciled():
    innings, scorecard = build_reconciliation(_sources())

    first = innings.loc[innings["innings"].eq("1")].iloc[0]
    chase = innings.loc[innings["innings"].eq("2")].iloc[0]
    assert first["additive_total_candidate"] == 4
    assert first["score_comparison_status"] == "NOT_COMPARABLE_NO_INDEPENDENT_SCORECARD"
    assert chase["chase_target_candidate"] == 5
    assert chase["target_comparison_status"] == "NOT_COMPARABLE_NO_EFFECTIVE_TARGET_TIMELINE"
    assert scorecard["independent_scorecard_value"].isna().all()


def test_bowler_concessions_remain_unavailable_without_scoring_rules():
    _, scorecard = build_reconciliation(_sources())

    bowler_rows = scorecard.loc[scorecard["metric"].eq("bowler_conceded_runs")]
    assert len(bowler_rows) == 2
    assert bowler_rows["delivery_candidate_value"].isna().all()
    assert bowler_rows["comparison_status"].eq(
        "NOT_CALCULABLE_SCORING_RULES_UNRESOLVED"
    ).all()
