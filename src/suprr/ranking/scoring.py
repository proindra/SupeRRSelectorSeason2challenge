from __future__ import annotations

import numpy as np
import pandas as pd


def competition_weighted_score(
    frame: pd.DataFrame,
    *,
    player_column: str,
    competition_column: str,
    exposure_column: str,
    weights: dict[str, float],
    eligible_column: str = "eligible",
) -> pd.DataFrame:
    required = {
        player_column,
        competition_column,
        exposure_column,
        eligible_column,
        *weights.keys(),
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Cannot score players; missing columns: {sorted(missing)}")
    result = frame.loc[frame[eligible_column]].copy()
    for metric in weights:
        result[metric] = pd.to_numeric(result[metric], errors="coerce")
        grouped = result.groupby(competition_column)[metric]
        mean = grouped.transform("mean")
        std = grouped.transform("std")
        count = grouped.transform("count")
        z_score = (result[metric] - mean) / std
        constant_group = count.ge(2) & std.eq(0) & result[metric].notna()
        result[f"{metric}_z"] = z_score.mask(constant_group, 0)

    player_scores: list[pd.DataFrame] = []
    for metric in weights:
        z_column = f"{metric}_z"
        values = result[[player_column, exposure_column, z_column]].copy()
        values["_weighted_z"] = values[z_column] * values[exposure_column]
        values["_valid_exposure"] = values[exposure_column].where(values[z_column].notna(), 0)
        aggregate = values.groupby(player_column, as_index=False).agg(
            _weighted_z=("_weighted_z", "sum"), _valid_exposure=("_valid_exposure", "sum")
        )
        aggregate[metric] = aggregate["_weighted_z"] / aggregate["_valid_exposure"].replace(
            0, np.nan
        )
        player_scores.append(aggregate[[player_column, metric]])
    if not player_scores:
        return pd.DataFrame(columns=[player_column, "composite_score", "rank"])
    combined = player_scores[0]
    for part in player_scores[1:]:
        combined = combined.merge(part, on=player_column, how="outer", validate="one_to_one")
    metric_names = list(weights)
    combined["complete_metrics"] = combined[metric_names].notna().all(axis=1)
    combined["composite_score"] = sum(
        combined[metric] * weight for metric, weight in weights.items()
    ).where(combined["complete_metrics"])
    combined = combined.sort_values(
        ["composite_score", player_column],
        ascending=[False, True],
        na_position="last",
        kind="stable",
    )
    combined["rank"] = combined["composite_score"].rank(method="min", ascending=False)
    return combined
