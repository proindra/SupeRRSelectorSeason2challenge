from __future__ import annotations

import json

import pandas as pd

from suprr.schemas import SourceTables
from suprr.validation.investigations import investigate_sources
from suprr.validation.scoring_rules import dismissal_category


def _sources() -> SourceTables:
    deliveries = pd.DataFrame(
        [
            {
                "match_id": "m1",
                "innings": "1",
                "overid": "1",
                "over_ball_num": "1",
                "innings_ball_num": "1",
                "striker_id": "p1",
                "bowler_id": "p2",
                "runs": "1",
                "is_four": "false",
                "is_six": "false",
                "is_wicket": "false",
                "dismissal_type_id": pd.NA,
                "dismissal_type": pd.NA,
                "dismissed_player_id": pd.NA,
                "extras_type": "None",
                "extras1_runs": "0",
                "extras_2_runs": "0",
            },
            {
                "match_id": "m1",
                "innings": "1",
                "overid": "1",
                "over_ball_num": "2",
                "innings_ball_num": "2",
                "striker_id": "p1",
                "bowler_id": "p2",
                "runs": "0",
                "is_four": "false",
                "is_six": "false",
                "is_wicket": "false",
                "dismissal_type_id": pd.NA,
                "dismissal_type": pd.NA,
                "dismissed_player_id": pd.NA,
                "extras_type": "Overstep",
                "extras1_runs": "1",
                "extras_2_runs": "0",
            },
            {
                "match_id": "m1",
                "innings": "2",
                "overid": "1",
                "over_ball_num": "1",
                "innings_ball_num": "1",
                "striker_id": "p3",
                "bowler_id": "p4",
                "runs": "0",
                "is_four": "false",
                "is_six": "false",
                "is_wicket": "false",
                "dismissal_type_id": pd.NA,
                "dismissal_type": pd.NA,
                "dismissed_player_id": pd.NA,
                "extras_type": "None",
                "extras1_runs": "0",
                "extras_2_runs": "0",
            },
            {
                "match_id": "m1",
                "innings": "1",
                "overid": "1",
                "over_ball_num": "3",
                "innings_ball_num": "3",
                "striker_id": "p1",
                "bowler_id": "p2",
                "runs": "0",
                "is_four": "false",
                "is_six": "false",
                "is_wicket": "false",
                "dismissal_type_id": pd.NA,
                "dismissal_type": pd.NA,
                "dismissed_player_id": "p1",
                "extras_type": "None",
                "extras1_runs": "0",
                "extras_2_runs": "0",
            },
            {
                "match_id": "m1",
                "innings": "3",
                "overid": "1",
                "over_ball_num": "1",
                "innings_ball_num": "1",
                "striker_id": "p3",
                "bowler_id": "p2",
                "runs": "0",
                "is_four": "false",
                "is_six": "false",
                "is_wicket": "true",
                "dismissal_type_id": "5",
                "dismissal_type": "Stump",
                "dismissed_player_id": "p3",
                "extras_type": "wide",
                "extras1_runs": "1",
                "extras_2_runs": "0",
            },
        ]
    )
    matches = pd.DataFrame(
        [
            {
                "match_id": "m1",
                "result": "Match tied; home team won the Super Over",
                "revised_target": "3",
                "first_inn_revised_overs": pd.NA,
                "second_inn_revised_overs": pd.NA,
            }
        ]
    )
    return {"deliveries": deliveries, "matches": matches}


def test_investigation_traces_issue_rows_and_neighbors(config):
    assert dismissal_category("Stump", config) == "unresolved"
    investigation = investigate_sources(_sources(), config)

    overstep = investigation.records.loc[
        investigation.records["issue_code"].eq("EXTRAS_OVERSTEP")
    ].iloc[0]
    assert overstep["delivery_identifier"] == "m1/1/1/2"
    assert overstep["source_data_row"] == 3
    assert json.loads(overstep["previous_delivery"])["innings_ball_num"] == "1"
    assert json.loads(overstep["next_delivery"])["innings_ball_num"] == "3"

    stump = investigation.dismissal_reconciliation.loc[
        investigation.dismissal_reconciliation["original_label"].eq("Stump")
    ].iloc[0]
    assert stump["count_before"] == 1
    assert stump["canonical_label"] == "UNRESOLVED"
    assert stump["bowler_credited_status"] == "UNRESOLVED"
    assert stump["batter_dismissed_status"] == "CONFIRMED_YES"
    unlabeled = investigation.dismissal_reconciliation.loc[
        investigation.dismissal_reconciliation["original_label"].eq("(blank)")
    ].iloc[0]
    assert unlabeled["count_before"] == 1
    assert unlabeled["batter_dismissed_status"] == "UNRESOLVED"


def test_super_over_needs_explicit_result_and_revised_match_is_excluded(config):
    sources = _sources()
    investigation = investigate_sources(sources, config)

    super_over = investigation.super_over_reconciliation.iloc[0]
    assert super_over["status"] == "CONFIRMED"
    assert super_over["result_names_super_over"]

    exclusion = investigation.revised_exclusions.iloc[0]
    assert exclusion["match_id"] == "m1"
    assert exclusion["status"] == "EXCLUDED_WITH_REASON"
    assert investigation.summary["primary_model_status"] == "ASSUMPTION_BASED_EXPLORATORY"

    sources["matches"].loc[0, "result"] = "Home won by 10 runs"
    unresolved = investigate_sources(sources, config)
    assert unresolved.super_over_reconciliation.iloc[0]["status"] == "UNRESOLVED"
