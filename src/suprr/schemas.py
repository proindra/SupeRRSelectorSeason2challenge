from __future__ import annotations

from typing import TypeAlias

import pandas as pd

SourceTables: TypeAlias = dict[str, pd.DataFrame]
CanonicalTables: TypeAlias = dict[str, pd.DataFrame]

SOURCE_FILES = {
    "deliveries": "ball_by_ball.csv",
    "player_team_mapping": "competition_team_player_mapping.csv",
    "competitions": "competitions.csv",
    "matches": "matches.csv",
    "playing_eleven": "playing_eleven.csv",
    "teams": "teams.csv",
}

REQUIRED_SOURCE_COLUMNS = {
    "deliveries": {
        "match_id",
        " innings",
        " overid",
        " over_ball_num",
        " innings_ball_num",
        " batting_team_id",
        " bowling_team_id",
        " striker_id",
        " non_striker_id",
        " bowler_id",
        " runs",
        " is_wicket",
        " dismissal_type       ",
        " dismissed_player_id",
        " extras_type",
        " extras1_runs",
        " extras_2_runs",
    },
    "player_team_mapping": {
        "comp_id",
        " team_id",
        " player_id",
        " player_name",
    },
    "competitions": {"comp_id", " match_format", " season"},
    "matches": {
        "match_id",
        "comp_id",
        "home_team_id",
        "away_team_id",
        "win_team_id",
        "result",
        "revised_target",
    },
    "playing_eleven": {"match_id", " team_id", " player_id", " is_played"},
    "teams": {"comp_id", "team_id", "team_name"},
}
