from __future__ import annotations

import pandas as pd

from suprr.config import AppConfig


def add_comparison_group(
    frame: pd.DataFrame,
    competitions: pd.DataFrame,
    config: AppConfig,
    *,
    competition_column: str = "competition_id",
) -> pd.DataFrame:
    required = {competition_column, "competition_name", "format"}
    missing = required - set(competitions.columns)
    if missing:
        raise ValueError(f"Competition grouping is missing columns: {sorted(missing)}")
    lookup = competitions[[competition_column, "competition_name", "format"]].drop_duplicates(
        competition_column
    )
    tokens = [token.casefold() for token in config.competition_groups.ipl_name_tokens]

    def classify(row: pd.Series) -> str:
        name = str(row["competition_name"]).casefold()
        match_format = str(row["format"]).strip().casefold()
        if any(token.casefold() in name for token in tokens):
            return "IPL"
        if match_format == config.competition_groups.t20i_format.casefold():
            return "T20I"
        return "Other"

    lookup["comparison_group"] = lookup.apply(classify, axis=1)
    return frame.merge(
        lookup[[competition_column, "comparison_group"]],
        on=competition_column,
        how="left",
        validate="many_to_one",
    )
