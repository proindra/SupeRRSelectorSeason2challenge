from __future__ import annotations

import numpy as np
import pandas as pd

from suprr.config import AppConfig


def _bool(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.lower().isin({"true", "1", "yes"})


def calculate_batter_metrics(states: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    required = {
        "competition_id",
        "match_id",
        "striker_id",
        "batter_runs",
        "extras_category",
        "is_high_pressure",
        "pressure_score",
        "phase",
        "is_four",
        "is_six",
        "dismissed_player_id",
        "dismissal_type",
        "is_live_chase",
    }
    missing = required - set(states.columns)
    if missing:
        raise ValueError(f"Batter metrics are missing required fields: {sorted(missing)}")
    frame = states.copy()
    frame["batter_runs"] = pd.to_numeric(frame["batter_runs"], errors="coerce")
    frame["is_four"] = _bool(frame["is_four"])
    frame["is_six"] = _bool(frame["is_six"])
    frame["is_wide"] = frame["extras_category"].eq("wide")
    frame["ball_faced"] = ~frame["is_wide"]
    frame["high_batter_ball"] = frame["is_high_pressure"] & frame["ball_faced"]
    frame["low_batter_ball"] = (~frame["is_high_pressure"]) & frame["ball_faced"]
    frame["dismissal_type"] = frame["dismissal_type"].astype("string").str.strip()
    frame["striker_dismissed"] = (
        frame["dismissed_player_id"].notna()
        & frame["dismissed_player_id"].eq(frame["striker_id"])
        & frame["dismissal_type"].isin(config.scoring.dismissals["batter_dismissed"])
    )

    high = frame.loc[frame["high_batter_ball"]].copy()
    innings = high.groupby(
        ["competition_id", "striker_id", "match_id", "phase"], as_index=False
    ).agg(
        balls=("ball_faced", "sum"),
        runs=("batter_runs", "sum"),
    )
    baselines = high.groupby(["competition_id", "phase"], as_index=False).agg(
        baseline_runs=("batter_runs", "sum"), baseline_balls=("ball_faced", "sum")
    )
    baselines["baseline_sr"] = (
        100
        * baselines["baseline_runs"]
        / baselines["baseline_balls"].where(baselines["baseline_balls"].gt(0))
    )
    # Combine phase segments within each player-match innings before comparison.
    inning_totals = innings.groupby(
        ["competition_id", "striker_id", "match_id"], as_index=False
    ).agg(pressure_balls=("balls", "sum"), pressure_runs=("runs", "sum"))
    phase_mix = innings.merge(
        baselines[["competition_id", "phase", "baseline_sr"]],
        on=["competition_id", "phase"],
        how="left",
        validate="many_to_one",
    )
    phase_mix["weighted_baseline"] = phase_mix["baseline_sr"] * phase_mix["balls"]
    inning_baseline = phase_mix.groupby(
        ["competition_id", "striker_id", "match_id"], as_index=False
    ).agg(
        _weighted_baseline=("weighted_baseline", "sum"),
        _baseline_balls=("balls", "sum"),
    )
    inning_totals = inning_totals.merge(
        inning_baseline, on=["competition_id", "striker_id", "match_id"], validate="one_to_one"
    )
    inning_totals["baseline_sr"] = (
        inning_totals["_weighted_baseline"] / inning_totals["_baseline_balls"]
    )
    inning_totals["innings_sr"] = (
        100 * inning_totals["pressure_runs"] / inning_totals["pressure_balls"]
    )
    inning_totals["qualifies"] = inning_totals["pressure_balls"].ge(
        config.samples.minimum_balls_per_innings_or_spell
    )
    inning_totals["meets_benchmark"] = inning_totals["innings_sr"].ge(inning_totals["baseline_sr"])
    eligible_innings = inning_totals.loc[inning_totals["qualifies"]]
    exposure = eligible_innings.groupby(["competition_id", "striker_id"], as_index=False).agg(
        pressure_balls=("pressure_balls", "sum"),
        pressure_runs=("pressure_runs", "sum"),
        pressure_innings=("match_id", "nunique"),
    )
    eligible_innings["_benchmark_balls"] = eligible_innings["pressure_balls"].where(
        eligible_innings["meets_benchmark"], 0
    )
    consistency_rows = eligible_innings.groupby(
        ["competition_id", "striker_id"], as_index=False
    ).agg(
        _benchmark_balls=("_benchmark_balls", "sum"),
        _total_balls=("pressure_balls", "sum"),
    )
    consistency_rows["consistency"] = (
        consistency_rows["_benchmark_balls"] / consistency_rows["_total_balls"]
    )
    consistency_rows = consistency_rows.drop(columns=["_benchmark_balls", "_total_balls"])
    consistency_count = eligible_innings.groupby(
        ["competition_id", "striker_id"], as_index=False
    ).agg(qualifying_innings=("meets_benchmark", "sum"))
    exposure = exposure.merge(
        consistency_rows, on=["competition_id", "striker_id"], how="left", validate="one_to_one"
    ).merge(
        consistency_count, on=["competition_id", "striker_id"], how="left", validate="one_to_one"
    )

    pressure_eligible_keys = eligible_innings[["competition_id", "striker_id", "match_id"]]
    eligible_high = high.merge(
        pressure_eligible_keys,
        on=["competition_id", "striker_id", "match_id"],
        how="inner",
        validate="many_to_one",
    )
    eligible_high["dot"] = eligible_high["batter_runs"].eq(0)
    eligible_high["boundaries"] = eligible_high["is_four"].astype(int) + eligible_high[
        "is_six"
    ].astype(int)
    pressure_agg = eligible_high.groupby(["competition_id", "striker_id"], as_index=False).agg(
        fours=("is_four", "sum"),
        sixes=("is_six", "sum"),
        dots=("dot", "sum"),
        dismissals=("striker_dismissed", "sum"),
    )
    low = frame.loc[frame["low_batter_ball"] & frame["is_live_chase"]]
    normal_agg = low.groupby(["competition_id", "striker_id"], as_index=False).agg(
        normal_runs=("batter_runs", "sum"), normal_balls=("ball_faced", "sum")
    )
    result = exposure.merge(
        pressure_agg, on=["competition_id", "striker_id"], how="left", validate="one_to_one"
    ).merge(normal_agg, on=["competition_id", "striker_id"], how="left", validate="one_to_one")
    for column in ["fours", "sixes", "dots", "dismissals", "normal_runs", "normal_balls"]:
        result[column] = result[column].fillna(0)
    result["pressure_strike_rate"] = 100 * result["pressure_runs"] / result["pressure_balls"]
    result["boundary_rate"] = 100 * (result["fours"] + result["sixes"]) / result["pressure_balls"]
    result["dot_ball_rate"] = 100 * result["dots"] / result["pressure_balls"]
    result["dismissal_rate"] = 100 * result["dismissals"] / result["pressure_balls"]
    result["normal_strike_rate"] = (
        100 * result["normal_runs"] / result["normal_balls"].replace(0, np.nan)
    )
    result["strike_rate_change"] = result["pressure_strike_rate"] - result["normal_strike_rate"]
    result["runs_per_pressure_innings"] = result["pressure_runs"] / result["pressure_innings"]
    result["eligible"] = result["pressure_balls"].ge(config.samples.batter_pressure_balls) & result[
        "pressure_innings"
    ].ge(config.samples.batter_pressure_innings)
    return result
