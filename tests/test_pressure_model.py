from __future__ import annotations

import pandas as pd
import pytest

from suprr.features.innings_state import (
    PressurePrerequisiteError,
    derive_chase_states,
)
from suprr.validation.pressure_gate import validate_pressure_model


def _deliveries() -> pd.DataFrame:
    rows = []
    sequence = 1
    for innings, entries in [
        (1, [(4, "None", 0, 0, False)]),
        (
            2,
            [
                (1, "None", 0, 0, False),
                (0, "wide", 1, 0, False),
                (0, "no_ball", 1, 0, False),
                (1, "None", 0, 0, True),
                (1, "None", 0, 0, False),
                (1, "None", 0, 0, False),
            ],
        ),
        (3, [(2, "None", 0, 0, False)]),
    ]:
        for ball, (runs, extras, extra_1, extra_2, wicket) in enumerate(entries, start=1):
            rows.append(
                {
                    "match_id": "m1",
                    "innings": innings,
                    "over_number": 1,
                    "ball_number": ball,
                    "delivery_sequence": sequence,
                    "batting_team_id": "t2" if innings % 2 == 0 else "t1",
                    "bowling_team_id": "t1" if innings % 2 == 0 else "t2",
                    "striker_id": "p1",
                    "non_striker_id": "p2",
                    "bowler_id": "p3",
                    "batter_runs": runs,
                    "wicket_flag": wicket,
                    "dismissal_type": "Bowled" if wicket else None,
                    "dismissed_player_id": "p1" if wicket else None,
                    "extras_type": extras,
                    "extras_1": extra_1,
                    "extras_2": extra_2,
                    "is_four": False,
                    "is_six": False,
                    "delivery_time": None,
                }
            )
            sequence += 1
    return pd.DataFrame(rows)


def _matches() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "match_id": "m1",
                "competition_id": "c1",
                "team1_id": "t1",
                "team2_id": "t2",
                "winner_team_id": "t2",
                "result": "won",
                "revised_target": None,
                "first_innings_revised_overs": None,
                "second_innings_revised_overs": None,
                "venue_id": "v1",
                "is_knockout": False,
                "stage": "group",
                "match_date": "2024-01-01",
            }
        ]
    )


def test_pre_delivery_state_excludes_current_runs_and_wicket(config):
    states = derive_chase_states(
        _deliveries(), _matches(), config, verified_super_over_keys={("m1", 3)}
    )
    first = states.iloc[0]
    after_wide = states.iloc[1]
    after_no_ball = states.iloc[2]
    wicket_delivery = states.iloc[3]
    assert first["target_runs"] == 5
    assert first["runs_scored_before"] == 0
    assert first["wickets_lost_before"] == 0
    assert after_wide["legal_balls_remaining_before"] == 119
    assert after_no_ball["legal_balls_remaining_before"] == 119
    assert wicket_delivery["runs_scored_before"] == 3
    assert wicket_delivery["wickets_lost_before"] == 0
    assert states["innings"].eq(2).all()
    assert states["pressure_score"].dropna().between(0, 1).all()


def test_unconfirmed_legal_delivery_semantics_block_pressure(config):
    unconfirmed_scoring = config.scoring.model_copy(
        update={"legal_delivery_categories_confirmed": False}
    )
    unconfirmed = config.model_copy(update={"scoring": unconfirmed_scoring})
    with pytest.raises(PressurePrerequisiteError, match="Legal-ball categories"):
        derive_chase_states(_deliveries(), _matches(), unconfirmed)


def test_unverified_extra_innings_block_pressure(config):
    with pytest.raises(PressurePrerequisiteError, match="source-result verification"):
        derive_chase_states(_deliveries(), _matches(), config)


def test_runs_needed_zero_has_no_live_pressure(config):
    deliveries = _deliveries()
    second_indices = deliveries.index[deliveries["innings"].eq(2)]
    deliveries.loc[second_indices[0], "batter_runs"] = 5
    states = derive_chase_states(
        deliveries, _matches(), config, verified_super_over_keys={("m1", 3)}
    )
    next_delivery = states.iloc[1]
    assert next_delivery["runs_needed_before"] <= 0
    assert not next_delivery["is_live_chase"]
    assert pd.isna(next_delivery["pressure_score"])


def test_empty_chase_states_return_a_blocked_validation(config):
    deliveries = _deliveries().loc[lambda frame: frame["innings"].ne(2)]
    states = derive_chase_states(
        deliveries, _matches(), config, verified_super_over_keys={("m1", 3)}
    )
    assert states.empty
    result = validate_pressure_model(states, _matches(), config)
    assert not result.passed
    assert result.status == "PRESSURE MODEL NOT VALIDATED"
