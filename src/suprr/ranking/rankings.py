from __future__ import annotations

import numpy as np
import pandas as pd

from suprr.config import AppConfig
from suprr.ranking.eligibility import apply_combined_eligibility
from suprr.ranking.scoring import competition_weighted_score

BATTER_WEIGHTS = {
    "pressure_strike_rate_shrunk": 0.25,
    "pressure_runs": 0.15,
    "strike_rate_change_shrunk": 0.15,
    "boundary_rate_shrunk": 0.10,
    "consistency": 0.10,
    "dot_ball_rate_shrunk": -0.10,
    "dismissal_rate_shrunk": -0.15,
}

BOWLER_WEIGHTS = {
    "pressure_economy_shrunk": -0.25,
    "dot_ball_rate_shrunk": 0.20,
    "pressure_wickets": 0.15,
    "boundary_conceded_rate_shrunk": -0.15,
    "regularised_bowling_average": -0.05,
    "regularised_bowling_strike_rate": -0.05,
    "economy_improvement_shrunk": 0.10,
    "consistency": 0.05,
}


def _pooled_rates_many(
    states: pd.DataFrame,
    group_column: str,
    specifications: dict[str, tuple[bool, str, str]],
) -> dict[str, dict[object, tuple[float, float]]]:
    result: dict[str, dict[object, tuple[float, float]]] = {}
    for pressure in {specification[0] for specification in specifications.values()}:
        selected = {
            name: specification
            for name, specification in specifications.items()
            if specification[0] == pressure
        }
        mask = (
            states["is_high_pressure"].astype(bool)
            if pressure
            else (~states["is_high_pressure"].astype(bool) & states["is_live_chase"].astype(bool))
        )
        columns = list(
            dict.fromkeys(
                column
                for _, numerator, denominator in selected.values()
                for column in (numerator, denominator)
            )
        )
        totals = states.loc[mask].groupby(group_column, dropna=False)[columns].sum()
        for name, (_, numerator, denominator) in selected.items():
            result[name] = {
                group: (float(row[numerator]), float(row[denominator]))
                for group, row in totals.iterrows()
            }
    return result


def _shrink_rows(
    frame: pd.DataFrame,
    *,
    group_column: str,
    numerator: str,
    denominator: str,
    baseline: dict[object, tuple[float, float]],
    k: int,
    scale: float = 1.0,
) -> pd.Series:
    if k <= 0:
        raise ValueError("k must be a positive exposure count.")
    player_numerator = pd.to_numeric(frame[numerator], errors="coerce").to_numpy(
        dtype="float64", na_value=np.nan
    )
    player_denominator = pd.to_numeric(frame[denominator], errors="coerce").to_numpy(
        dtype="float64", na_value=np.nan
    )
    pooled = np.asarray(
        [baseline.get(group, (0.0, 0.0)) for group in frame[group_column].to_numpy(dtype=object)],
        dtype="float64",
    )
    league_numerator = pooled[:, 0]
    league_denominator = pooled[:, 1]
    valid = (player_denominator > 0) & (league_denominator > 0)
    result = np.full(len(frame), np.nan, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        result[valid] = scale * (
            player_denominator[valid]
            / (player_denominator[valid] + k)
            * (player_numerator[valid] / player_denominator[valid])
            + k
            / (player_denominator[valid] + k)
            * (league_numerator[valid] / league_denominator[valid])
        )
    return pd.Series(result, index=frame.index, dtype="float64")


def _bool(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.lower().isin({"true", "1", "yes", "y"})


def _aggregate_player_groups(
    metrics: pd.DataFrame,
    *,
    player_column: str,
    comparison_group_column: str,
    sum_columns: list[str],
    rate_columns: list[str],
    exposure_column: str,
) -> pd.DataFrame:
    keys = [comparison_group_column, player_column]
    weighted_columns = {column: f"_weighted_{column}" for column in rate_columns}
    weighted_metrics = metrics.assign(
        **{
            weighted_columns[column]: metrics[column] * metrics[exposure_column]
            for column in rate_columns
        }
    )
    aggregates = weighted_metrics.groupby(keys, as_index=False, dropna=False)[
        sum_columns + list(weighted_columns.values())
    ].sum()
    exposure = pd.to_numeric(aggregates[exposure_column], errors="coerce").replace(0, np.nan)
    for column, weighted_column in weighted_columns.items():
        aggregates[column] = aggregates[weighted_column] / exposure
    return aggregates.drop(columns=list(weighted_columns.values()))


def rank_batters(
    metrics: pd.DataFrame,
    states: pd.DataFrame,
    config: AppConfig,
    *,
    player_column: str = "striker_id",
    comparison_group_column: str = "comparison_group",
    k: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    k_value = k or config.reliability.default_k_balls
    counts = [
        "pressure_runs",
        "pressure_balls",
        "pressure_innings",
        "qualifying_innings",
        "fours",
        "sixes",
        "dots",
        "dismissals",
        "normal_runs",
        "normal_balls",
    ]
    grouped = _aggregate_player_groups(
        metrics,
        player_column=player_column,
        comparison_group_column=comparison_group_column,
        sum_columns=counts,
        rate_columns=["consistency"],
        exposure_column="pressure_balls",
    )
    grouped["pressure_strike_rate"] = (
        100 * grouped["pressure_runs"] / grouped["pressure_balls"].replace(0, np.nan)
    )
    grouped["boundary_rate"] = (
        100 * (grouped["fours"] + grouped["sixes"]) / grouped["pressure_balls"].replace(0, np.nan)
    )
    grouped["dot_ball_rate"] = 100 * grouped["dots"] / grouped["pressure_balls"].replace(0, np.nan)
    grouped["dismissal_rate"] = (
        100 * grouped["dismissals"] / grouped["pressure_balls"].replace(0, np.nan)
    )
    grouped["fours_sixes"] = grouped["fours"] + grouped["sixes"]
    grouped["normal_strike_rate"] = (
        100 * grouped["normal_runs"] / grouped["normal_balls"].replace(0, np.nan)
    )
    grouped["strike_rate_change"] = grouped["pressure_strike_rate"] - grouped["normal_strike_rate"]
    baseline_states = states.copy()
    baseline_states["ball_faced"] = ~baseline_states["extras_category"].eq("wide")
    baseline_states["boundary_count"] = _bool(baseline_states["is_four"]).astype(int) + _bool(
        baseline_states["is_six"]
    ).astype(int)
    baseline_states["dot_count"] = (
        baseline_states["batter_runs"].eq(0) & baseline_states["ball_faced"]
    ).astype(int)
    baseline_states["dismissal_count"] = (
        baseline_states["dismissed_player_id"].notna()
        & baseline_states["dismissed_player_id"].eq(baseline_states["striker_id"])
        & baseline_states["dismissal_type"].isin(config.scoring.dismissals["batter_dismissed"])
    ).astype(int)
    baseline_states["batter_runs"] = pd.to_numeric(
        baseline_states["batter_runs"], errors="coerce"
    ).fillna(0)
    baselines = _pooled_rates_many(
        baseline_states.assign(_runs=baseline_states["batter_runs"]),
        comparison_group_column,
        {
            "pressure_strike_rate": (True, "_runs", "ball_faced"),
            "normal_strike_rate": (False, "_runs", "ball_faced"),
            "boundary_rate": (True, "boundary_count", "ball_faced"),
            "dot_ball_rate": (True, "dot_count", "ball_faced"),
            "dismissal_rate": (True, "dismissal_count", "ball_faced"),
        },
    )
    grouped["pressure_strike_rate_shrunk"] = _shrink_rows(
        grouped,
        group_column=comparison_group_column,
        numerator="pressure_runs",
        denominator="pressure_balls",
        baseline=baselines["pressure_strike_rate"],
        k=k_value,
        scale=100,
    )
    grouped["normal_strike_rate_shrunk"] = _shrink_rows(
        grouped,
        group_column=comparison_group_column,
        numerator="normal_runs",
        denominator="normal_balls",
        baseline=baselines["normal_strike_rate"],
        k=k_value,
        scale=100,
    )
    rate_specs = [
        ("boundary_rate_shrunk", "fours_sixes", "pressure_balls"),
        ("dot_ball_rate_shrunk", "dots", "pressure_balls"),
        ("dismissal_rate_shrunk", "dismissals", "pressure_balls"),
    ]
    for output, numerator, denominator in rate_specs:
        grouped[output] = _shrink_rows(
            grouped,
            group_column=comparison_group_column,
            numerator=numerator,
            denominator=denominator,
            baseline=baselines[output.removesuffix("_shrunk")],
            k=k_value,
            scale=100,
        )
    grouped["strike_rate_change_shrunk"] = (
        grouped["pressure_strike_rate_shrunk"] - grouped["normal_strike_rate_shrunk"]
    )
    grouped = apply_combined_eligibility(
        grouped,
        player_column=player_column,
        exposure_column="pressure_balls",
        count_column="pressure_innings",
        minimum_exposure=config.samples.batter_pressure_balls,
        minimum_count=config.samples.batter_pressure_innings,
    )
    scores = competition_weighted_score(
        grouped,
        player_column=player_column,
        competition_column=comparison_group_column,
        exposure_column="pressure_balls",
        weights=BATTER_WEIGHTS,
    )
    return grouped, scores


def rank_bowlers(
    metrics: pd.DataFrame,
    states: pd.DataFrame,
    config: AppConfig,
    *,
    player_column: str = "bowler_id",
    comparison_group_column: str = "comparison_group",
    k: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    k_value = k or config.reliability.default_k_balls
    counts = [
        "legal_pressure_balls",
        "pressure_conceded_runs",
        "pressure_wickets",
        "pressure_spells",
        "qualifying_spells",
        "dots",
        "fours",
        "sixes",
        "normal_runs",
        "normal_legal_balls",
    ]
    grouped = _aggregate_player_groups(
        metrics,
        player_column=player_column,
        comparison_group_column=comparison_group_column,
        sum_columns=counts,
        rate_columns=["consistency"],
        exposure_column="legal_pressure_balls",
    )
    grouped["pressure_economy"] = (
        6 * grouped["pressure_conceded_runs"] / grouped["legal_pressure_balls"].replace(0, np.nan)
    )
    grouped["normal_economy"] = (
        6 * grouped["normal_runs"] / grouped["normal_legal_balls"].replace(0, np.nan)
    )
    grouped["economy_improvement"] = grouped["normal_economy"] - grouped["pressure_economy"]
    grouped["dot_ball_rate"] = (
        100 * grouped["dots"] / grouped["legal_pressure_balls"].replace(0, np.nan)
    )
    grouped["boundary_conceded_rate"] = (
        100
        * (grouped["fours"] + grouped["sixes"])
        / grouped["legal_pressure_balls"].replace(0, np.nan)
    )
    grouped["fours_sixes"] = grouped["fours"] + grouped["sixes"]
    grouped["regularised_bowling_average"] = grouped["pressure_conceded_runs"] / (
        grouped["pressure_wickets"] + 1
    )
    grouped["regularised_bowling_strike_rate"] = grouped["legal_pressure_balls"] / (
        grouped["pressure_wickets"] + 1
    )
    grouped["conventional_bowling_average"] = (
        grouped["pressure_conceded_runs"] / grouped["pressure_wickets"].replace(0, np.nan)
    ).where(grouped["pressure_wickets"].ge(3))

    baseline_states = states.copy()
    for column in ["batter_runs", "extras_1", "extras_2"]:
        baseline_states[column] = pd.to_numeric(baseline_states[column], errors="coerce").fillna(0)
    baseline_states["is_wide"] = baseline_states["extras_category"].eq("wide")
    baseline_states["is_no_ball"] = baseline_states["extras_category"].eq("no_ball")
    baseline_states["legal_ball"] = ~(baseline_states["is_wide"] | baseline_states["is_no_ball"])
    charged = baseline_states["extras_category"].isin({"wide", "no_ball"})
    baseline_states["bowler_runs"] = baseline_states["batter_runs"] + (
        baseline_states["extras_1"] + baseline_states["extras_2"]
    ).where(charged, 0)
    baseline_states["dot_count"] = (
        baseline_states["legal_ball"]
        & (
            baseline_states["batter_runs"]
            + baseline_states["extras_1"]
            + baseline_states["extras_2"]
        ).eq(0)
    ).astype(int)
    baseline_states["boundary_count"] = _bool(baseline_states["is_four"]).astype(int) + _bool(
        baseline_states["is_six"]
    ).astype(int)
    baselines = _pooled_rates_many(
        baseline_states,
        comparison_group_column,
        {
            "pressure_economy_shrunk": (
                True,
                "bowler_runs",
                "legal_ball",
            ),
            "normal_economy_shrunk": (
                False,
                "bowler_runs",
                "legal_ball",
            ),
            "dot_ball_rate_shrunk": (
                True,
                "dot_count",
                "legal_ball",
            ),
            "boundary_conceded_rate_shrunk": (
                True,
                "boundary_count",
                "legal_ball",
            ),
        },
    )
    for output, numerator, denominator, scale in [
        ("pressure_economy_shrunk", "pressure_conceded_runs", "legal_pressure_balls", 6),
        ("normal_economy_shrunk", "normal_runs", "normal_legal_balls", 6),
        ("dot_ball_rate_shrunk", "dots", "legal_pressure_balls", 100),
        ("boundary_conceded_rate_shrunk", "fours_sixes", "legal_pressure_balls", 100),
    ]:
        grouped[output] = _shrink_rows(
            grouped,
            group_column=comparison_group_column,
            numerator=numerator,
            denominator=denominator,
            baseline=baselines[output],
            k=k_value,
            scale=scale,
        )
    grouped["economy_improvement_shrunk"] = (
        grouped["normal_economy_shrunk"] - grouped["pressure_economy_shrunk"]
    )
    grouped["wickets_per_100_legal_balls"] = (
        100 * grouped["pressure_wickets"] / grouped["legal_pressure_balls"]
    )
    grouped = apply_combined_eligibility(
        grouped,
        player_column=player_column,
        exposure_column="legal_pressure_balls",
        count_column="pressure_spells",
        minimum_exposure=config.samples.bowler_legal_pressure_balls,
        minimum_count=config.samples.bowler_pressure_spells,
    )
    scores = competition_weighted_score(
        grouped,
        player_column=player_column,
        competition_column=comparison_group_column,
        exposure_column="legal_pressure_balls",
        weights=BOWLER_WEIGHTS,
    )
    return grouped, scores
