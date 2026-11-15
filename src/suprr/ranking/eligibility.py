from __future__ import annotations

import pandas as pd


def exclude_players(
    frame: pd.DataFrame,
    *,
    player_column: str,
    excluded_player_ids: set[str],
) -> pd.DataFrame:
    if not excluded_player_ids:
        return frame.copy()
    return frame.loc[
        ~frame[player_column].astype("string").isin(excluded_player_ids)
    ].copy()


def apply_combined_eligibility(
    frame: pd.DataFrame,
    *,
    player_column: str,
    exposure_column: str,
    count_column: str,
    minimum_exposure: int,
    minimum_count: int,
    output_column: str = "eligible",
) -> pd.DataFrame:
    totals = frame.groupby(player_column, as_index=False).agg(
        _total_exposure=(exposure_column, "sum"),
        _total_count=(count_column, "sum"),
    )
    totals[output_column] = totals["_total_exposure"].ge(minimum_exposure) & totals[
        "_total_count"
    ].ge(minimum_count)
    result = frame.drop(columns=[output_column], errors="ignore").merge(
        totals[[player_column, output_column]],
        on=player_column,
        how="left",
        validate="many_to_one",
    )
    return result
