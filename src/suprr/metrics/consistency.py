from __future__ import annotations

import pandas as pd


def ball_weighted_consistency(
    group: pd.DataFrame,
    exposure_column: str,
    meets_benchmark_column: str,
) -> float:
    denominator = float(group[exposure_column].sum())
    if denominator <= 0:
        return float("nan")
    numerator = float(group.loc[group[meets_benchmark_column], exposure_column].sum())
    return numerator / denominator
