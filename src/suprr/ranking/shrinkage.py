from __future__ import annotations

import pandas as pd


def shrink_rate(
    numerator: float,
    denominator: float,
    league_numerator: float,
    league_denominator: float,
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("k must be a positive exposure count.")
    if denominator <= 0 or league_denominator <= 0:
        return float("nan")
    player_rate = numerator / denominator
    league_rate = league_numerator / league_denominator
    return denominator / (denominator + k) * player_rate + k / (denominator + k) * league_rate


def add_shrunk_rate(
    frame: pd.DataFrame,
    *,
    numerator: str,
    denominator: str,
    group_columns: list[str],
    output: str,
    k: int,
    scale: float = 1.0,
) -> pd.DataFrame:
    if k <= 0:
        raise ValueError("k must be a positive exposure count.")
    missing = set(group_columns + [numerator, denominator]) - set(frame.columns)
    if missing:
        raise ValueError(f"Cannot shrink rate; missing columns: {sorted(missing)}")
    result = frame.copy()
    league = result.groupby(group_columns, dropna=False, as_index=False).agg(
        _league_num=(numerator, "sum"), _league_den=(denominator, "sum")
    )
    result = result.merge(league, on=group_columns, how="left", validate="many_to_one")
    player_denominator = result[denominator]
    league_denominator = result["_league_den"]
    result[output] = player_denominator / (player_denominator + k) * (
        scale * result[numerator] / player_denominator.where(player_denominator.gt(0))
    ) + k / (player_denominator + k) * (
        scale * result["_league_num"] / league_denominator.where(league_denominator.gt(0))
    )
    return result.drop(columns=["_league_num", "_league_den"])
