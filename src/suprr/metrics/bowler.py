from __future__ import annotations

import numpy as np
import pandas as pd

from suprr.config import AppConfig


def _bool(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.lower().isin({"true", "1", "yes"})


def calculate_bowler_metrics(states: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    required = {
        "competition_id",
        "match_id",
        "bowler_id",
        "batter_runs",
        "extras_1",
        "extras_2",
        "extras_category",
        "is_high_pressure",
        "pressure_score",
        "phase",
        "is_four",
        "is_six",
        "dismissal_type",
        "wicket_flag",
        "is_live_chase",
    }
    missing = required - set(states.columns)
    if missing:
        raise ValueError(f"Bowler metrics are missing required fields: {sorted(missing)}")
    frame = states.copy()
    for column in ["batter_runs", "extras_1", "extras_2"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    frame["is_four"] = _bool(frame["is_four"])
    frame["is_six"] = _bool(frame["is_six"])
    frame["wicket_flag"] = _bool(frame["wicket_flag"])
    frame["is_wide"] = frame["extras_category"].eq("wide")
    frame["is_no_ball"] = frame["extras_category"].eq("no_ball")
    frame["legal_ball"] = ~(frame["is_wide"] | frame["is_no_ball"])
    charged_extras = frame["extras_category"].isin({"wide", "no_ball"})
    frame["bowler_runs"] = frame["batter_runs"] + (frame["extras_1"] + frame["extras_2"]).where(
        charged_extras, 0
    )
    frame["total_runs_delivery"] = frame["batter_runs"] + frame["extras_1"] + frame["extras_2"]
    frame["dot_legal_ball"] = frame["legal_ball"] & frame["total_runs_delivery"].eq(0)
    frame["credited_wicket"] = frame["wicket_flag"] & frame["dismissal_type"].astype(
        "string"
    ).str.strip().isin(config.scoring.dismissals["bowler_credited"])
    high = frame.loc[frame["is_high_pressure"]].copy()
    phase_spell = high.groupby(
        ["competition_id", "bowler_id", "match_id", "phase"], as_index=False
    ).agg(
        legal_balls=("legal_ball", "sum"),
        conceded_runs=("bowler_runs", "sum"),
        wickets=("credited_wicket", "sum"),
    )
    # A match spell can span phases; preserve phase-specific benchmark comparisons.
    phase_baselines = high.groupby(["competition_id", "phase"], as_index=False).agg(
        league_runs=("bowler_runs", "sum"),
        league_legal_balls=("legal_ball", "sum"),
    )
    phase_baselines["league_economy"] = (
        6
        * phase_baselines["league_runs"]
        / phase_baselines["league_legal_balls"].replace(0, np.nan)
    )
    phase_spell = phase_spell.merge(
        phase_baselines[["competition_id", "phase", "league_economy"]],
        on=["competition_id", "phase"],
        how="left",
        validate="many_to_one",
    )
    phase_spell["economy"] = (
        6 * phase_spell["conceded_runs"] / phase_spell["legal_balls"].replace(0, np.nan)
    )
    match_spell = phase_spell.groupby(
        ["competition_id", "bowler_id", "match_id"], as_index=False
    ).agg(
        legal_balls=("legal_balls", "sum"),
        conceded_runs=("conceded_runs", "sum"),
        wickets=("wickets", "sum"),
    )
    # Weight phase baselines by legal-ball exposure for a match-level spell.
    phase_spell["weighted_baseline"] = phase_spell["league_economy"] * phase_spell["legal_balls"]
    match_baseline = phase_spell.groupby(
        ["competition_id", "bowler_id", "match_id"], as_index=False
    ).agg(
        _weighted_baseline=("weighted_baseline", "sum"),
        _baseline_balls=("legal_balls", "sum"),
    )
    match_spell = match_spell.merge(
        match_baseline,
        on=["competition_id", "bowler_id", "match_id"],
        validate="one_to_one",
    )
    match_spell["league_economy"] = (
        match_spell["_weighted_baseline"] / match_spell["_baseline_balls"]
    )
    match_spell["economy"] = (
        6 * match_spell["conceded_runs"] / match_spell["legal_balls"].replace(0, np.nan)
    )
    match_spell["qualifies"] = match_spell["legal_balls"].ge(
        config.samples.minimum_balls_per_innings_or_spell
    )
    match_spell["meets_benchmark"] = match_spell["economy"].le(match_spell["league_economy"])
    eligible_spells = match_spell.loc[match_spell["qualifies"]]
    exposure = eligible_spells.groupby(["competition_id", "bowler_id"], as_index=False).agg(
        legal_pressure_balls=("legal_balls", "sum"),
        pressure_conceded_runs=("conceded_runs", "sum"),
        pressure_wickets=("wickets", "sum"),
        pressure_spells=("match_id", "nunique"),
    )
    eligible_spells["_benchmark_balls"] = eligible_spells["legal_balls"].where(
        eligible_spells["meets_benchmark"], 0
    )
    consistency = eligible_spells.groupby(["competition_id", "bowler_id"], as_index=False).agg(
        _benchmark_balls=("_benchmark_balls", "sum"),
        _total_balls=("legal_balls", "sum"),
    )
    consistency["consistency"] = consistency["_benchmark_balls"] / consistency["_total_balls"]
    consistency = consistency.drop(columns=["_benchmark_balls", "_total_balls"])
    consistency_count = eligible_spells.groupby(
        ["competition_id", "bowler_id"], as_index=False
    ).agg(qualifying_spells=("meets_benchmark", "sum"))
    exposure = exposure.merge(
        consistency, on=["competition_id", "bowler_id"], how="left", validate="one_to_one"
    ).merge(
        consistency_count, on=["competition_id", "bowler_id"], how="left", validate="one_to_one"
    )
    pressure_keys = eligible_spells[["competition_id", "bowler_id", "match_id"]]
    eligible_high = high.merge(
        pressure_keys,
        on=["competition_id", "bowler_id", "match_id"],
        how="inner",
        validate="many_to_one",
    )
    detail = eligible_high.groupby(["competition_id", "bowler_id"], as_index=False).agg(
        legal_balls=("legal_ball", "sum"),
        conceded_runs=("bowler_runs", "sum"),
        wickets=("credited_wicket", "sum"),
        dots=("dot_legal_ball", "sum"),
        fours=("is_four", "sum"),
        sixes=("is_six", "sum"),
    )
    low = frame.loc[(~frame["is_high_pressure"]) & frame["is_live_chase"]]
    low_economy = low.groupby(["competition_id", "bowler_id"], as_index=False).agg(
        normal_runs=("bowler_runs", "sum"), normal_legal_balls=("legal_ball", "sum")
    )
    result = exposure.merge(
        detail,
        on=["competition_id", "bowler_id"],
        how="left",
        suffixes=("_eligible", ""),
        validate="one_to_one",
    ).merge(
        low_economy,
        on=["competition_id", "bowler_id"],
        how="left",
        validate="one_to_one",
    )
    for column in ["legal_balls", "conceded_runs", "wickets", "dots", "fours", "sixes"]:
        result[column] = result[column].fillna(0)
    result["pressure_economy"] = (
        6 * result["pressure_conceded_runs"] / result["legal_pressure_balls"]
    )
    result["dot_ball_rate"] = 100 * result["dots"] / result["legal_pressure_balls"]
    result["boundary_conceded_rate"] = (
        100 * (result["fours"] + result["sixes"]) / result["legal_pressure_balls"]
    )
    result["regularised_bowling_average"] = result["pressure_conceded_runs"] / (
        result["pressure_wickets"] + 1
    )
    result["regularised_bowling_strike_rate"] = result["legal_pressure_balls"] / (
        result["pressure_wickets"] + 1
    )
    result["conventional_bowling_average"] = (
        result["pressure_conceded_runs"] / result["pressure_wickets"].replace(0, np.nan)
    ).where(result["pressure_wickets"].ge(3))
    result["normal_economy"] = (
        6 * result["normal_runs"] / result["normal_legal_balls"].replace(0, np.nan)
    )
    result["economy_improvement"] = result["normal_economy"] - result["pressure_economy"]
    result["wickets_per_100_legal_balls"] = (
        100 * result["pressure_wickets"] / result["legal_pressure_balls"]
    )
    result["eligible"] = result["legal_pressure_balls"].ge(
        config.samples.bowler_legal_pressure_balls
    ) & result["pressure_spells"].ge(config.samples.bowler_pressure_spells)
    return result
