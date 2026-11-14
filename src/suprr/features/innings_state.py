from __future__ import annotations

import pandas as pd

from suprr.config import AppConfig
from suprr.features.phases import add_phase
from suprr.validation.scoring_rules import extra_category


class PressurePrerequisiteError(ValueError):
    """Raised when source semantics cannot support pressure state calculation."""


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _boolean(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip().str.lower()
    return text.isin({"true", "1", "yes", "y"})


def calculate_innings_totals(deliveries: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    if not config.scoring.batter_runs_excludes_extras_confirmed:
        raise PressurePrerequisiteError(
            "Cannot derive innings totals until `runs` is confirmed as batter runs "
            "excluding extras."
        )
    categories = deliveries["extras_type"].map(lambda value: extra_category(value, config))
    unresolved = sorted(categories[categories.eq("unresolved")].dropna().unique().tolist())
    if unresolved:
        raise PressurePrerequisiteError(
            f"Cannot derive innings totals with unresolved extras categories: {unresolved}"
        )
    result = deliveries.copy()
    result["batter_runs"] = _number(result["batter_runs"])
    result["extras_runs"] = _number(result["extras_1"]).fillna(0) + _number(
        result["extras_2"]
    ).fillna(0)
    result["total_runs"] = result["batter_runs"].fillna(0) + result["extras_runs"]
    return result.groupby(["match_id", "innings"], as_index=False, dropna=False).agg(
        innings_total=("total_runs", "sum")
    )


def derive_chase_states(
    deliveries: pd.DataFrame,
    matches: pd.DataFrame,
    config: AppConfig,
    over_base: int = 1,
    verified_super_over_keys: set[tuple[str, int]] | None = None,
) -> pd.DataFrame:
    if not config.scoring.legal_delivery_categories_confirmed:
        raise PressurePrerequisiteError("Legal-ball categories have not been confirmed.")
    if not config.scoring.batter_runs_excludes_extras_confirmed:
        raise PressurePrerequisiteError("Batter-runs semantics have not been confirmed.")
    frame = deliveries.copy()
    extra_innings = _number(frame["innings"]).ge(3)
    if extra_innings.any():
        if verified_super_over_keys is None:
            raise PressurePrerequisiteError(
                "Innings 3+ require source-result verification before they can be excluded."
            )
        observed_keys = {
            (str(match_id), int(innings))
            for match_id, innings in zip(
                frame.loc[extra_innings, "match_id"],
                _number(frame.loc[extra_innings, "innings"]),
                strict=True,
            )
        }
        unverified_keys = observed_keys - verified_super_over_keys
        if unverified_keys:
            raise PressurePrerequisiteError(
                f"Innings 3+ lack verified Super Over evidence: {sorted(unverified_keys)}"
            )
        frame = frame.loc[~extra_innings].copy()
    categories = frame["extras_type"].map(lambda value: extra_category(value, config))
    unresolved = sorted(categories[categories.eq("unresolved")].dropna().unique().tolist())
    if unresolved:
        raise PressurePrerequisiteError(
            f"Cannot calculate legal balls with unresolved extras categories: {unresolved}"
        )
    revised_columns = [
        column
        for column in (
            "revised_target",
            "first_innings_revised_overs",
            "second_innings_revised_overs",
        )
        if column in matches
    ]
    revised_ids: set[str] = set()
    if revised_columns and matches[revised_columns].notna().any(axis=None):
        revised_ids = set(
            matches.loc[matches[revised_columns].notna().any(axis=1), "match_id"].astype("string")
        )
    target_effective_sequence_available = "revised_target_effective_delivery" in matches.columns
    if revised_ids and config.scoring.target_timing_reconstructible:
        if not target_effective_sequence_available:
            raise PressurePrerequisiteError(
                "The config asserts revised-target timing is reconstructible, but no "
                "`revised_target_effective_delivery` field is mapped."
            )
        raise PressurePrerequisiteError(
            "Revised-target effective-delivery handling must be validated before inclusion."
        )

    matches = matches.copy()
    numeric_columns = [
        "innings",
        "over_number",
        "ball_number",
        "delivery_sequence",
        "batter_runs",
        "extras_1",
        "extras_2",
    ]
    for column in numeric_columns:
        if column in frame:
            frame[column] = _number(frame[column])
    frame["wicket_flag"] = _boolean(frame["wicket_flag"])
    frame["extras_category"] = categories
    frame["extras_runs"] = frame["extras_1"].fillna(0) + frame["extras_2"].fillna(0)
    frame["total_runs"] = frame["batter_runs"].fillna(0) + frame["extras_runs"]
    frame["legal_ball_flag"] = ~frame["extras_category"].isin({"wide", "no_ball"})
    frame["match_id"] = frame["match_id"].astype("string")
    matches["match_id"] = matches["match_id"].astype("string")

    if revised_ids:
        frame = frame.loc[~frame["match_id"].isin(revised_ids)].copy()

    innings_totals = calculate_innings_totals(frame, config)
    first_totals = innings_totals.loc[innings_totals["innings"].eq(1)].rename(
        columns={"innings_total": "first_innings_total"}
    )
    frame = frame.merge(
        first_totals[["match_id", "first_innings_total"]], on="match_id", how="left"
    )
    frame = frame.loc[frame["innings"].eq(2)].copy()
    match_fields = [
        "match_id",
        "competition_id",
        "winner_team_id",
        "revised_target",
        "second_innings_revised_overs",
        "match_date",
    ]
    available_match_fields = [column for column in match_fields if column in matches.columns]
    frame = frame.merge(
        matches[available_match_fields].drop_duplicates("match_id"),
        on="match_id",
        how="left",
        validate="many_to_one",
    )
    order_columns = ["match_id"]
    if "delivery_sequence" in frame.columns:
        order_columns.append("delivery_sequence")
    order_columns.extend(["over_number", "ball_number"])
    frame = frame.sort_values(order_columns, kind="stable")
    if frame.empty:
        empty = frame.assign(
            target_runs=pd.Series(dtype="float64"),
            scheduled_legal_balls=pd.Series(dtype="int64"),
            runs_scored_before=pd.Series(dtype="float64"),
            legal_balls_bowled_before=pd.Series(dtype="int64"),
            wickets_lost_before=pd.Series(dtype="int64"),
            runs_needed_before=pd.Series(dtype="float64"),
            legal_balls_remaining_before=pd.Series(dtype="int64"),
            wickets_in_hand_before=pd.Series(dtype="int64"),
            required_run_rate_before=pd.Series(dtype="float64"),
            R=pd.Series(dtype="float64"),
            W=pd.Series(dtype="float64"),
            D=pd.Series(dtype="float64"),
            S=pd.Series(dtype="float64"),
            pressure_score=pd.Series(dtype="float64"),
            pressure_band=pd.Series(dtype="string"),
            is_live_chase=pd.Series(dtype="bool"),
            is_high_pressure=pd.Series(dtype="bool"),
        )
        return add_phase(empty, config, over_base=over_base)

    frame["target_runs"] = frame["first_innings_total"] + 1
    frame["scheduled_legal_balls"] = config.pressure.scheduled_legal_balls
    frame["runs_scored_before"] = (
        frame.groupby("match_id")["total_runs"].cumsum() - frame["total_runs"]
    )
    frame["legal_balls_bowled_before"] = frame.groupby("match_id")[
        "legal_ball_flag"
    ].cumsum().astype(int) - frame["legal_ball_flag"].astype(int)
    frame["wickets_lost_before"] = frame.groupby("match_id")["wicket_flag"].cumsum().astype(
        int
    ) - frame["wicket_flag"].astype(int)
    frame["runs_needed_before"] = frame["target_runs"] - frame["runs_scored_before"]
    frame["legal_balls_remaining_before"] = (
        frame["scheduled_legal_balls"] - frame["legal_balls_bowled_before"]
    )
    frame["wickets_in_hand_before"] = 10 - frame["wickets_lost_before"]
    live = (
        frame["runs_needed_before"].gt(0)
        & frame["legal_balls_remaining_before"].gt(0)
        & frame["wickets_in_hand_before"].gt(0)
        & frame["target_runs"].notna()
    )
    frame["required_run_rate_before"] = (
        frame["runs_needed_before"] * 6 / frame["legal_balls_remaining_before"].where(live)
    )
    frame["R"] = (frame["required_run_rate_before"] / config.pressure.required_rate_cap).clip(0, 1)
    frame["W"] = (frame["wickets_lost_before"] / 10).clip(0, 1)
    difficulty_denominator = (
        frame["legal_balls_remaining_before"]
        * config.pressure.maximum_assumed_runs_per_ball
        * frame["wickets_in_hand_before"]
        / 10
    )
    frame["D"] = (frame["runs_needed_before"] / difficulty_denominator.where(live)).clip(0, 1)
    frame["S"] = (frame["legal_balls_bowled_before"] / frame["scheduled_legal_balls"]).clip(0, 1)
    weights = config.pressure.weights
    frame["pressure_score"] = (
        weights.required_rate * frame["R"]
        + weights.wickets_lost * frame["W"]
        + weights.chase_difficulty * frame["D"]
        + weights.innings_stage * frame["S"]
    ).where(live)
    frame["is_live_chase"] = live
    frame["pressure_band"] = pd.cut(
        frame["pressure_score"],
        bins=[-0.0000001, 0.2, 0.4, 0.6, 0.8, 1.0000001],
        labels=["0-.2", ".2-.4", ".4-.6", ".6-.8", ".8-1"],
        right=False,
        include_lowest=True,
    )
    frame["is_high_pressure"] = (
        frame["pressure_score"].ge(config.pressure.high_pressure_threshold).fillna(False)
    )
    frame = add_phase(frame, config, over_base=over_base)
    if not frame["pressure_score"].dropna().between(0, 1).all():
        raise ArithmeticError("Pressure scores must be finite values within [0, 1].")
    return frame
