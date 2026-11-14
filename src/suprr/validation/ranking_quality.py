from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from suprr.config import AppConfig, load_config
from suprr.metrics.batter import calculate_batter_metrics
from suprr.metrics.bowler import calculate_bowler_metrics
from suprr.ranking.rankings import (
    BATTER_WEIGHTS,
    BOWLER_WEIGHTS,
    rank_batters,
    rank_bowlers,
)
from suprr.ranking.scoring import competition_weighted_score

SCOPES = ("IPL_T20I", "IPL", "T20I")
ROLES = ("batter", "bowler")
ASSESSMENT_LABEL = "ROBUSTNESS-ASSESSED"
EXPLORATORY_LABEL = "EXPLORATORY"
SENSITIVITY_FACTORS = (0.75, 1.25)


def _role_columns(role: str) -> tuple[str, str, dict[str, float]]:
    if role == "batter":
        return "striker_id", "pressure_balls", BATTER_WEIGHTS
    if role == "bowler":
        return "bowler_id", "legal_pressure_balls", BOWLER_WEIGHTS
    raise ValueError(f"Unknown ranking role: {role}")


def _player_key(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0"):
        numeric = text[:-2]
        if numeric.isdigit():
            return numeric
    return text


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    columns = [str(column) for column in frame.columns]
    rows = [
        [
            str(value).replace("|", "\\|").replace("\n", " ") if not pd.isna(value) else ""
            for value in row
        ]
        for row in frame.itertuples(index=False, name=None)
    ]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _read_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "reports" / "run_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Exploratory run manifest not found: {path}")
    with path.open(encoding="utf-8") as file:
        manifest = json.load(file)
    if (
        manifest.get("status") != "EXPLORATORY_COMPLETE"
        or manifest.get("analysis_mode") != "ASSUMPTION_BASED_EXPLORATORY"
        or manifest.get("output_label") != EXPLORATORY_LABEL
    ):
        raise ValueError(
            "Ranking validation accepts only a completed, explicitly labelled "
            "ASSUMPTION_BASED_EXPLORATORY run."
        )
    return manifest


def _check_row(
    check_id: str,
    description: str,
    failures: int,
    rows_checked: int,
    *,
    max_abs_error: float | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "description": description,
        "status": "VALIDATED" if failures == 0 else "FAILED",
        "rows_checked": rows_checked,
        "failure_count": failures,
        "max_abs_error": max_abs_error,
        "validation_scope": "mathematical consistency only",
        "input_label": EXPLORATORY_LABEL,
        "assessment_label": ASSESSMENT_LABEL,
    }


def _numeric_values(values: pd.Series | np.ndarray) -> np.ndarray:
    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)
    return np.asarray(values, dtype="float64")


def _relation_check(
    frame: pd.DataFrame,
    check_id: str,
    description: str,
    actual_column: str,
    expected: pd.Series | np.ndarray,
    *,
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    actual = _numeric_values(frame[actual_column])
    expected_values = _numeric_values(expected)
    matches = np.isclose(actual, expected_values, rtol=tolerance, atol=tolerance, equal_nan=True)
    comparable = np.isfinite(actual) & np.isfinite(expected_values)
    max_error = (
        float(np.max(np.abs(actual[comparable] - expected_values[comparable])))
        if comparable.any()
        else 0.0
    )
    return _check_row(
        check_id,
        description,
        int((~matches).sum()),
        len(frame),
        max_abs_error=max_error,
    )


def mathematical_consistency_checks(
    full: pd.DataFrame,
    top10: pd.DataFrame,
    role: str,
) -> pd.DataFrame:
    player_column, _, weights = _role_columns(role)
    checks: list[dict[str, Any]] = []
    formula_columns = (
        {
            "pressure_balls",
            "pressure_runs",
            "normal_strike_rate",
            "pressure_strike_rate",
            "strike_rate_change",
            "fours",
            "sixes",
            "boundary_rate",
            "dots",
            "dot_ball_rate",
            "dismissals",
            "dismissal_rate",
        }
        if role == "batter"
        else {
            "legal_pressure_balls",
            "pressure_wickets",
            "pressure_conceded_runs",
            "pressure_economy",
            "dot_ball_rate",
            "dots",
            "fours",
            "sixes",
            "boundary_conceded_rate",
            "regularised_bowling_average",
            "regularised_bowling_strike_rate",
            "wickets_per_100_legal_balls",
            "normal_economy",
            "economy_improvement",
        }
    )
    required = {
        player_column,
        "composite_score",
        "rank",
        "complete_metrics",
        "output_label",
        *formula_columns,
        *weights.keys(),
        *(f"{metric}_weighted_z" for metric in weights),
    }
    missing = (required - set(full.columns)) | (
        {player_column, "output_label"} - set(top10.columns)
    )
    if missing:
        return pd.DataFrame(
            [
                _check_row(
                    "required_columns",
                    f"Required ranking columns exist: {sorted(missing)}",
                    len(missing),
                    len(required),
                )
            ]
        )

    checks.append(
        _check_row(
            "unique_player_rows",
            "The full ranking contains at most one row per player.",
            int(full[player_column].duplicated().sum()),
            len(full),
        )
    )
    labels = full["output_label"]
    top_labels = top10["output_label"]
    wrong_labels = int((labels.astype("string") != EXPLORATORY_LABEL).sum()) + int(
        (top_labels.astype("string") != EXPLORATORY_LABEL).sum()
    )
    checks.append(
        _check_row(
            "exploratory_labels",
            "Full and Top-10 files retain the EXPLORATORY label.",
            wrong_labels,
            len(full) + len(top10),
        )
    )

    composite = sum(
        pd.to_numeric(full[f"{metric}_weighted_z"], errors="coerce") * weight
        for metric, weight in weights.items()
    )
    checks.append(
        _relation_check(
            full,
            "composite_score_identity",
            "Composite score equals the weighted sum of the exported weighted-Z components.",
            "composite_score",
            composite,
        )
    )
    expected_rank = pd.to_numeric(full["composite_score"], errors="coerce").rank(
        method="min", ascending=False
    )
    checks.append(
        _relation_check(
            full,
            "rank_identity",
            "Exported rank equals descending composite-score rank using method=min.",
            "rank",
            expected_rank,
        )
    )

    complete_columns = [f"{metric}_weighted_z" for metric in weights]
    complete = full[complete_columns].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)
    exported_complete = (
        full["complete_metrics"].astype("string").str.lower().isin({"true", "1", "yes"})
    )
    checks.append(
        _check_row(
            "complete_metrics_identity",
            "complete_metrics agrees with non-null weighted-Z components.",
            int((complete != exported_complete).sum()),
            len(full),
        )
    )

    if role == "batter":
        balls = pd.to_numeric(full["pressure_balls"], errors="coerce").replace(0, np.nan)
        runs = pd.to_numeric(full["pressure_runs"], errors="coerce")
        checks.extend(
            [
                _relation_check(
                    full,
                    "pressure_strike_rate_identity",
                    "Pressure strike rate equals 100 * pressure runs / pressure balls.",
                    "pressure_strike_rate",
                    100 * runs / balls,
                ),
                _relation_check(
                    full,
                    "boundary_rate_identity",
                    "Boundary rate equals 100 * (fours + sixes) / pressure balls.",
                    "boundary_rate",
                    100
                    * (
                        pd.to_numeric(full["fours"], errors="coerce")
                        + pd.to_numeric(full["sixes"], errors="coerce")
                    )
                    / balls,
                ),
                _relation_check(
                    full,
                    "dot_ball_rate_identity",
                    "Dot-ball rate equals 100 * dots / pressure balls.",
                    "dot_ball_rate",
                    100 * pd.to_numeric(full["dots"], errors="coerce") / balls,
                ),
                _relation_check(
                    full,
                    "dismissal_rate_identity",
                    "Dismissal rate equals 100 * dismissals / pressure balls.",
                    "dismissal_rate",
                    100 * pd.to_numeric(full["dismissals"], errors="coerce") / balls,
                ),
            ]
        )
    else:
        legal_balls = pd.to_numeric(full["legal_pressure_balls"], errors="coerce").replace(
            0, np.nan
        )
        wickets = pd.to_numeric(full["pressure_wickets"], errors="coerce")
        conceded = pd.to_numeric(full["pressure_conceded_runs"], errors="coerce")
        checks.extend(
            [
                _relation_check(
                    full,
                    "pressure_economy_identity",
                    "Pressure economy equals 6 * conceded runs / legal pressure balls.",
                    "pressure_economy",
                    6 * conceded / legal_balls,
                ),
                _relation_check(
                    full,
                    "dot_ball_rate_identity",
                    "Dot-ball rate equals 100 * dots / legal pressure balls.",
                    "dot_ball_rate",
                    100 * pd.to_numeric(full["dots"], errors="coerce") / legal_balls,
                ),
                _relation_check(
                    full,
                    "boundary_rate_identity",
                    "Boundary-conceded rate equals 100 * (fours + sixes) / legal pressure balls.",
                    "boundary_conceded_rate",
                    100
                    * (
                        pd.to_numeric(full["fours"], errors="coerce")
                        + pd.to_numeric(full["sixes"], errors="coerce")
                    )
                    / legal_balls,
                ),
                _relation_check(
                    full,
                    "wickets_per_100_identity",
                    "Wickets per 100 legal balls equals 100 * wickets / legal balls.",
                    "wickets_per_100_legal_balls",
                    100 * wickets / legal_balls,
                ),
            ]
        )

    expected_ids = (
        full.loc[pd.to_numeric(full["rank"], errors="coerce").le(10)]
        .sort_values(["rank", player_column], kind="stable")
        .head(10)[player_column]
        .astype("string")
        .tolist()
    )
    actual_ids = top10[player_column].astype("string").tolist()
    checks.append(
        _check_row(
            "top10_matches_full_ranking",
            "Top-10 player IDs and order match the full ranking.",
            int(expected_ids != actual_ids),
            max(len(expected_ids), len(actual_ids)),
        )
    )
    checks.append(
        _check_row(
            "top10_count",
            "The exported Top-10 file contains exactly ten players.",
            abs(len(top10) - 10),
            10,
        )
    )
    return pd.DataFrame(checks)


def _input_file_issues(
    full: pd.DataFrame,
    top10: pd.DataFrame,
    *,
    role: str,
    full_path: Path,
    top_path: Path,
) -> pd.DataFrame:
    player_column, _, _ = _role_columns(role)
    rows: list[dict[str, Any]] = []
    for path, frame in [(full_path, full), (top_path, top10)]:
        for index, row in frame.iterrows():
            player_id = row.get(player_column)
            label = row.get("output_label")
            if pd.isna(label) or str(label) != EXPLORATORY_LABEL:
                rows.append(
                    {
                        "input_label": EXPLORATORY_LABEL,
                        "assessment_label": ASSESSMENT_LABEL,
                        "role": role,
                        "source_file": path.name,
                        "csv_row": int(index) + 2,
                        "issue_id": "unexpected_output_label",
                        "player_id": None if pd.isna(player_id) else str(player_id),
                        "output_label": None if pd.isna(label) else str(label),
                        "details": "Expected output_label=EXPLORATORY.",
                    }
                )
            if pd.isna(player_id):
                rows.append(
                    {
                        "input_label": EXPLORATORY_LABEL,
                        "assessment_label": ASSESSMENT_LABEL,
                        "role": role,
                        "source_file": path.name,
                        "csv_row": int(index) + 2,
                        "issue_id": "missing_player_id",
                        "player_id": None,
                        "output_label": None if pd.isna(label) else str(label),
                        "details": "Ranking row has no player identifier.",
                    }
                )
        duplicate_ids = frame.loc[frame[player_column].duplicated(keep=False), player_column]
        for player_id in duplicate_ids.dropna().astype(str).unique():
            rows.append(
                {
                    "input_label": EXPLORATORY_LABEL,
                    "assessment_label": ASSESSMENT_LABEL,
                    "role": role,
                    "source_file": path.name,
                    "csv_row": None,
                    "issue_id": "duplicate_player_id",
                    "player_id": player_id,
                    "output_label": None,
                    "details": "Player appears in more than one row.",
                }
            )
    expected_ids = (
        full.loc[pd.to_numeric(full["rank"], errors="coerce").le(10)]
        .sort_values(["rank", player_column], kind="stable")
        .head(10)[player_column]
        .map(_player_key)
        .tolist()
    )
    actual_ids = [None if pd.isna(value) else _player_key(value) for value in top10[player_column]]
    if len(top10) != 10:
        rows.append(
            {
                "input_label": EXPLORATORY_LABEL,
                "assessment_label": ASSESSMENT_LABEL,
                "role": role,
                "source_file": top_path.name,
                "csv_row": None,
                "issue_id": "top10_row_count",
                "player_id": None,
                "output_label": None,
                "details": f"Expected 10 rows; found {len(top10)}.",
            }
        )
    for position in range(max(len(expected_ids), len(actual_ids))):
        expected = expected_ids[position] if position < len(expected_ids) else None
        actual = actual_ids[position] if position < len(actual_ids) else None
        if expected != actual:
            rows.append(
                {
                    "input_label": EXPLORATORY_LABEL,
                    "assessment_label": ASSESSMENT_LABEL,
                    "role": role,
                    "source_file": top_path.name,
                    "csv_row": position + 2 if position < len(actual_ids) else None,
                    "issue_id": "top10_order_mismatch",
                    "player_id": actual,
                    "output_label": None,
                    "details": f"Expected player ID {expected!r} at position {position + 1}.",
                }
            )
    return pd.DataFrame(rows)


def _group_metric_checks(grouped: pd.DataFrame, role: str) -> pd.DataFrame:
    checks: list[dict[str, Any]] = []
    if role == "batter":
        balls = pd.to_numeric(grouped["pressure_balls"], errors="coerce").replace(0, np.nan)
        checks.extend(
            [
                _relation_check(
                    grouped,
                    "group_strike_rate_change",
                    "Competition-scoped strike-rate change equals pressure minus "
                    "normal strike rate.",
                    "strike_rate_change",
                    pd.to_numeric(grouped["pressure_strike_rate"], errors="coerce")
                    - pd.to_numeric(grouped["normal_strike_rate"], errors="coerce"),
                ),
                _relation_check(
                    grouped,
                    "group_pressure_strike_rate",
                    "Competition-scoped pressure strike rate equals runs per pressure ball.",
                    "pressure_strike_rate",
                    100 * pd.to_numeric(grouped["pressure_runs"], errors="coerce") / balls,
                ),
                _relation_check(
                    grouped,
                    "group_shrunk_strike_rate_change",
                    "Shrunk strike-rate change equals pressure rate minus normal rate "
                    "after shrinkage.",
                    "strike_rate_change_shrunk",
                    pd.to_numeric(grouped["pressure_strike_rate_shrunk"], errors="coerce")
                    - pd.to_numeric(grouped["normal_strike_rate_shrunk"], errors="coerce"),
                ),
            ]
        )
    else:
        balls = pd.to_numeric(grouped["legal_pressure_balls"], errors="coerce").replace(0, np.nan)
        wickets = pd.to_numeric(grouped["pressure_wickets"], errors="coerce")
        conceded = pd.to_numeric(grouped["pressure_conceded_runs"], errors="coerce")
        checks.extend(
            [
                _relation_check(
                    grouped,
                    "group_pressure_economy",
                    "Competition-scoped pressure economy equals six times conceded "
                    "runs per legal ball.",
                    "pressure_economy",
                    6 * conceded / balls,
                ),
                _relation_check(
                    grouped,
                    "group_regularised_average",
                    "Regularised bowling average equals conceded runs / (wickets + 1).",
                    "regularised_bowling_average",
                    conceded / (wickets + 1),
                ),
                _relation_check(
                    grouped,
                    "group_regularised_strike_rate",
                    "Regularised bowling strike rate equals legal balls / (wickets + 1).",
                    "regularised_bowling_strike_rate",
                    balls / (wickets + 1),
                ),
                _relation_check(
                    grouped,
                    "group_economy_improvement",
                    "Economy improvement equals normal economy minus pressure economy.",
                    "economy_improvement",
                    pd.to_numeric(grouped["normal_economy"], errors="coerce")
                    - pd.to_numeric(grouped["pressure_economy"], errors="coerce"),
                ),
                _relation_check(
                    grouped,
                    "group_shrunk_economy_improvement",
                    "Shrunk economy improvement equals shrunk normal economy minus "
                    "shrunk pressure economy.",
                    "economy_improvement_shrunk",
                    pd.to_numeric(grouped["normal_economy_shrunk"], errors="coerce")
                    - pd.to_numeric(grouped["pressure_economy_shrunk"], errors="coerce"),
                ),
            ]
        )
    return pd.DataFrame(checks)


def _role_metrics(states: pd.DataFrame, role: str, config: AppConfig) -> pd.DataFrame:
    if role == "batter":
        metrics = calculate_batter_metrics(states, config)
    else:
        metrics = calculate_bowler_metrics(states, config)
    lookup = states[["competition_id", "comparison_group"]].drop_duplicates()
    conflicts = lookup.groupby("competition_id")["comparison_group"].nunique()
    if conflicts.gt(1).any():
        raise ValueError("A competition_id maps to multiple comparison groups in pressure states.")
    return metrics.merge(
        lookup,
        on="competition_id",
        how="left",
        validate="many_to_one",
    )


def _scope_frames(
    states: pd.DataFrame, metrics: pd.DataFrame, scope: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if scope == "IPL_T20I":
        return states, metrics
    return (
        states.loc[states["comparison_group"].eq(scope)],
        metrics.loc[metrics["comparison_group"].eq(scope)],
    )


def _rank_scope(
    role: str,
    states: pd.DataFrame,
    metrics: pd.DataFrame,
    config: AppConfig,
    scope: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    scope_states, scope_metrics = _scope_frames(states, metrics, scope)
    if role == "batter":
        return rank_batters(scope_metrics, scope_states, config)
    return rank_bowlers(scope_metrics, scope_states, config)


def _profile_metrics(grouped: pd.DataFrame, role: str) -> tuple[pd.DataFrame, list[str], list[str]]:
    player_column, _, _ = _role_columns(role)
    if role == "batter":
        count_columns = [
            "pressure_runs",
            "pressure_balls",
            "pressure_innings",
            "qualifying_innings",
            "fours",
            "sixes",
            "dots",
            "dismissals",
        ]
        rate_columns = [
            "pressure_strike_rate",
            "pressure_strike_rate_shrunk",
            "normal_strike_rate",
            "strike_rate_change_shrunk",
            "strike_rate_change",
            "boundary_rate",
            "boundary_rate_shrunk",
            "dot_ball_rate",
            "dot_ball_rate_shrunk",
            "dismissal_rate",
            "dismissal_rate_shrunk",
            "consistency",
        ]
        exposure_column = "pressure_balls"
    else:
        count_columns = [
            "pressure_wickets",
            "pressure_conceded_runs",
            "legal_pressure_balls",
            "pressure_spells",
            "qualifying_spells",
            "dots",
            "fours",
            "sixes",
        ]
        rate_columns = [
            "pressure_economy",
            "pressure_economy_shrunk",
            "dot_ball_rate",
            "dot_ball_rate_shrunk",
            "boundary_conceded_rate",
            "boundary_conceded_rate_shrunk",
            "regularised_bowling_average",
            "regularised_bowling_strike_rate",
            "conventional_bowling_average",
            "normal_economy",
            "economy_improvement_shrunk",
            "economy_improvement",
            "wickets_per_100_legal_balls",
            "consistency",
        ]
        exposure_column = "legal_pressure_balls"
    profiles = grouped.groupby(player_column, as_index=False)[count_columns].sum()
    for column in rate_columns:
        weighted = grouped.assign(_weighted=grouped[column] * grouped[exposure_column])
        rates = weighted.groupby(player_column, as_index=False).agg(
            _weighted=("_weighted", "sum"),
            _exposure=(exposure_column, "sum"),
        )
        rates[column] = rates["_weighted"] / rates["_exposure"].replace(0, np.nan)
        profiles = profiles.merge(
            rates[[player_column, column]],
            on=player_column,
            how="left",
            validate="one_to_one",
        )
    return profiles, count_columns, rate_columns


def _scope_ranking_output(
    grouped: pd.DataFrame,
    scores: pd.DataFrame,
    role: str,
    scope: str,
    names: dict[str, str],
) -> pd.DataFrame:
    player_column, _, weights = _role_columns(role)
    profiles, _, _ = _profile_metrics(grouped, role)
    contexts = (
        grouped.groupby(player_column)["comparison_group"]
        .agg(lambda values: ", ".join(sorted(set(values.dropna().astype(str)))))
        .rename("comparison_context")
        .reset_index()
    )
    profiles = profiles.merge(contexts, on=player_column, how="left", validate="one_to_one")
    score_columns = {metric: f"{metric}_weighted_z" for metric in weights}
    score_frame = scores.rename(columns=score_columns)
    result = profiles.merge(
        score_frame,
        on=player_column,
        how="left",
        validate="one_to_one",
    )
    result["player_name"] = result[player_column].map(lambda value: names.get(_player_key(value)))
    result = result.rename(columns={player_column: "player_id"})
    result.insert(0, "input_label", EXPLORATORY_LABEL)
    result.insert(1, "assessment_label", ASSESSMENT_LABEL)
    result.insert(2, "role", role)
    result.insert(3, "scope", scope)
    return result.sort_values(["rank", "player_id"], na_position="last", kind="stable")


def _baseline_reproduction_check(
    full: pd.DataFrame,
    grouped: pd.DataFrame,
    scores: pd.DataFrame,
    role: str,
) -> dict[str, Any]:
    player_column, _, weights = _role_columns(role)
    profiles, count_columns, rate_columns = _profile_metrics(grouped, role)

    actual = full.set_index(player_column)
    expected_profiles = profiles.set_index(player_column)
    profile_ids_match = set(actual.index.astype(str)) == set(expected_profiles.index.astype(str))
    common_profiles = actual.index.intersection(expected_profiles.index)
    mismatches = 0
    max_error = 0.0
    comparison_count = 0
    for column in [*count_columns, *rate_columns]:
        left = _numeric_values(actual.loc[common_profiles, column])
        right = _numeric_values(expected_profiles.loc[common_profiles, column])
        equal = np.isclose(left, right, rtol=1e-8, atol=1e-8, equal_nan=True)
        mismatches += int((~equal).sum())
        comparison_count += len(equal)
        finite = np.isfinite(left) & np.isfinite(right)
        if finite.any():
            max_error = max(max_error, float(np.max(np.abs(left[finite] - right[finite]))))

    actual_scored = full.loc[full["composite_score"].notna()].set_index(player_column)
    reproduced = scores.loc[scores["composite_score"].notna()].set_index(player_column)
    score_ids_match = set(actual_scored.index.astype(str)) == set(reproduced.index.astype(str))
    common_scores = actual_scored.index.intersection(reproduced.index)
    for column in ["composite_score", "rank", *weights.keys()]:
        export_column = f"{column}_weighted_z" if column in weights else column
        left = _numeric_values(actual_scored.loc[common_scores, export_column])
        right = _numeric_values(reproduced.loc[common_scores, column])
        equal = np.isclose(left, right, rtol=1e-8, atol=1e-8, equal_nan=True)
        mismatches += int((~equal).sum())
        comparison_count += len(equal)
        finite = np.isfinite(left) & np.isfinite(right)
        if finite.any():
            max_error = max(max_error, float(np.max(np.abs(left[finite] - right[finite]))))
    failures = mismatches + int(not profile_ids_match) + int(not score_ids_match)
    return _check_row(
        "source_state_reproduction",
        "Current metric code reproduces exported player metrics and scores from "
        "saved pressure states.",
        failures,
        comparison_count,
        max_abs_error=max_error,
    )


def _resample_matches(
    states: pd.DataFrame, random: np.random.Generator, replicate: int
) -> pd.DataFrame:
    matches = states[["match_id", "comparison_group"]].drop_duplicates()
    if matches["match_id"].duplicated().any():
        raise ValueError("A match_id belongs to multiple competition strata.")
    draws: list[pd.DataFrame] = []
    for group, group_matches in matches.groupby("comparison_group", sort=True):
        identifiers = group_matches["match_id"].dropna().to_numpy()
        if len(identifiers) == 0:
            continue
        sampled = random.choice(identifiers, size=len(identifiers), replace=True)
        draws.append(
            pd.DataFrame(
                {
                    "_source_match_id": sampled,
                    "_bootstrap_match_id": [
                        f"bootstrap-{replicate}-{group}-{draw}" for draw in range(len(sampled))
                    ],
                }
            )
        )
    if not draws:
        raise ValueError("Cannot bootstrap without match records.")
    sampled_matches = pd.concat(draws, ignore_index=True)
    result = sampled_matches.merge(
        states,
        left_on="_source_match_id",
        right_on="match_id",
        how="inner",
        validate="many_to_many",
        sort=False,
    )
    result["match_id"] = result["_bootstrap_match_id"]
    return result.drop(columns=["_source_match_id", "_bootstrap_match_id"])


def _pressure_metric(grouped: pd.DataFrame, role: str) -> pd.DataFrame:
    player_column, exposure_column, _ = _role_columns(role)
    metric_column = (
        "pressure_strike_rate" if role == "batter" else "regularised_bowling_strike_rate"
    )
    data = grouped[[player_column, exposure_column, metric_column]].copy()
    data["_weighted_metric"] = pd.to_numeric(data[metric_column], errors="coerce") * pd.to_numeric(
        data[exposure_column], errors="coerce"
    )
    summary = data.groupby(player_column, as_index=False).agg(
        _weighted_metric=("_weighted_metric", "sum"),
        _exposure=(exposure_column, "sum"),
    )
    summary["pressure_metric_value"] = summary["_weighted_metric"] / summary["_exposure"].replace(
        0, np.nan
    )
    summary["pressure_metric_name"] = metric_column
    return summary[[player_column, "pressure_metric_value", "pressure_metric_name"]]


def _bootstrap(
    states: pd.DataFrame,
    config: AppConfig,
    *,
    replicates: int,
    seed: int,
) -> pd.DataFrame:
    random = np.random.default_rng(seed)
    records: list[pd.DataFrame] = []
    for replicate in range(replicates):
        sample = _resample_matches(states, random, replicate)
        for role in ROLES:
            metrics = _role_metrics(sample, role, config)
            player_column, _, _ = _role_columns(role)
            for scope in SCOPES:
                grouped, scores = _rank_scope(role, sample, metrics, config, scope)
                pressure = _pressure_metric(grouped, role)
                candidates = (
                    grouped[[player_column]]
                    .drop_duplicates()
                    .merge(
                        scores[[player_column, "composite_score", "rank"]].drop_duplicates(
                            player_column
                        ),
                        on=player_column,
                        how="outer",
                        validate="one_to_one",
                    )
                )
                candidates = candidates.merge(
                    pressure, on=player_column, how="left", validate="one_to_one"
                )
                candidates["player_id"] = candidates[player_column]
                candidates = candidates.drop(columns=player_column)
                candidates["role"] = role
                candidates["scope"] = scope
                candidates["replicate"] = replicate
                records.append(candidates)
    if not records:
        return pd.DataFrame()
    result = pd.concat(records, ignore_index=True)
    # Each role's identifier was normalized before concatenation.
    result.insert(0, "input_label", EXPLORATORY_LABEL)
    result.insert(1, "assessment_label", ASSESSMENT_LABEL)
    return result[
        [
            "input_label",
            "assessment_label",
            "role",
            "scope",
            "player_id",
            "replicate",
            "rank",
            "composite_score",
            "pressure_metric_name",
            "pressure_metric_value",
        ]
    ]


def _summarize_bootstrap(
    replicates_frame: pd.DataFrame,
    *,
    role: str,
    scope: str,
    candidates: Iterable[str],
    baseline: pd.DataFrame,
    names: dict[str, str],
    replicate_count: int,
    confidence_level: float,
) -> pd.DataFrame:
    player_column, _, _ = _role_columns(role)
    subset = replicates_frame.loc[
        replicates_frame["role"].eq(role) & replicates_frame["scope"].eq(scope)
    ]
    base = (
        baseline[[player_column, "rank", "composite_score"]]
        .drop_duplicates(player_column)
        .set_index(player_column)
    )
    tail = (1 - confidence_level) / 2
    rows: list[dict[str, Any]] = []
    for player in sorted(set(str(value) for value in candidates)):
        sample = subset.loc[subset["player_id"].astype(str).eq(player)]
        ranks = pd.to_numeric(sample["rank"], errors="coerce").dropna()
        scores = pd.to_numeric(sample["composite_score"], errors="coerce").dropna()
        metric_values = pd.to_numeric(sample["pressure_metric_value"], errors="coerce").dropna()
        base_rank = base.loc[player, "rank"] if player in base.index else np.nan
        base_score = base.loc[player, "composite_score"] if player in base.index else np.nan
        rows.append(
            {
                "input_label": EXPLORATORY_LABEL,
                "assessment_label": ASSESSMENT_LABEL,
                "role": role,
                "scope": scope,
                "player_id": player,
                "player_name": names.get(player),
                "baseline_rank": base_rank,
                "baseline_composite_score": base_score,
                "top10_inclusion_probability": (float(ranks.le(10).sum()) / replicate_count),
                "median_rank": float(ranks.median()) if not ranks.empty else np.nan,
                "rank_ci_low": (float(ranks.quantile(tail)) if not ranks.empty else np.nan),
                "rank_ci_high": (float(ranks.quantile(1 - tail)) if not ranks.empty else np.nan),
                "median_composite_score": (float(scores.median()) if not scores.empty else np.nan),
                "score_ci_low": (float(scores.quantile(tail)) if not scores.empty else np.nan),
                "score_ci_high": (float(scores.quantile(1 - tail)) if not scores.empty else np.nan),
                "pressure_metric_name": (
                    str(sample["pressure_metric_name"].dropna().iloc[0])
                    if sample["pressure_metric_name"].notna().any()
                    else None
                ),
                "pressure_metric_median": (
                    float(metric_values.median()) if not metric_values.empty else np.nan
                ),
                "pressure_metric_ci_low": (
                    float(metric_values.quantile(tail)) if not metric_values.empty else np.nan
                ),
                "pressure_metric_ci_high": (
                    float(metric_values.quantile(1 - tail)) if not metric_values.empty else np.nan
                ),
                "valid_ranking_replicates": int(ranks.shape[0]),
                "valid_pressure_metric_replicates": int(metric_values.shape[0]),
                "replicates_total": replicate_count,
            }
        )
    return pd.DataFrame(rows)


def _scenario_frame(
    *,
    role: str,
    scope: str,
    baseline_grouped: pd.DataFrame,
    baseline_scores: pd.DataFrame,
    alternative_scores: pd.DataFrame,
    dimension: str,
    scenario_id: str,
    parameter: str,
    player_column: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    base_rank = baseline_scores[[player_column, "rank"]].rename(columns={"rank": "baseline_rank"})
    alt_rank = alternative_scores[[player_column, "rank"]].rename(columns={"rank": "scenario_rank"})
    candidates = (
        baseline_grouped[[player_column]]
        .drop_duplicates()
        .merge(base_rank, on=player_column, how="left", validate="one_to_one")
    )
    candidates = candidates.merge(alt_rank, on=player_column, how="left", validate="one_to_one")
    candidates["baseline_top10"] = pd.to_numeric(candidates["baseline_rank"], errors="coerce").le(
        10
    )
    candidates["scenario_top10"] = pd.to_numeric(candidates["scenario_rank"], errors="coerce").le(
        10
    )
    candidates["top10_membership_changed"] = (
        candidates["baseline_top10"] != candidates["scenario_top10"]
    )
    scenario_rank = pd.Series(_numeric_values(candidates["scenario_rank"]), index=candidates.index)
    baseline_rank = pd.Series(_numeric_values(candidates["baseline_rank"]), index=candidates.index)
    candidates["rank_change"] = scenario_rank - baseline_rank
    candidates.insert(0, "input_label", EXPLORATORY_LABEL)
    candidates.insert(1, "assessment_label", ASSESSMENT_LABEL)
    candidates["player_id"] = candidates[player_column]
    candidates = candidates.drop(columns=player_column)
    candidates["role"] = role
    candidates["scope"] = scope
    candidates["dimension"] = dimension
    candidates["scenario_id"] = scenario_id
    candidates["parameter"] = parameter
    baseline_top = set(candidates.loc[candidates["baseline_top10"], player_column].astype(str))
    scenario_top = set(candidates.loc[candidates["scenario_top10"], player_column].astype(str))
    summary = {
        "input_label": EXPLORATORY_LABEL,
        "assessment_label": ASSESSMENT_LABEL,
        "role": role,
        "scope": scope,
        "dimension": dimension,
        "scenario_id": scenario_id,
        "parameter": parameter,
        "baseline_top10_count": len(baseline_top),
        "scenario_top10_count": len(scenario_top),
        "top10_overlap": len(baseline_top & scenario_top),
        "top10_added": len(scenario_top - baseline_top),
        "top10_removed": len(baseline_top - scenario_top),
        "players_with_membership_change": int(candidates["top10_membership_changed"].sum()),
        "median_absolute_rank_change": (
            float(pd.to_numeric(candidates["rank_change"], errors="coerce").abs().median())
            if candidates["rank_change"].notna().any()
            else None
        ),
    }
    return candidates, summary


def _sensitivity(
    states: pd.DataFrame,
    metrics_by_role: dict[str, pd.DataFrame],
    baseline_by_role_scope: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]],
    config: AppConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    details: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for role in ROLES:
        player_column, exposure_column, base_weights = _role_columns(role)
        base_metrics = metrics_by_role[role]
        for scope in SCOPES:
            grouped, base_scores = baseline_by_role_scope[(role, scope)]
            scope_states, scope_metrics = _scope_frames(states, base_metrics, scope)
            weight_delta = config.robustness.weight_perturbation
            for metric, base_weight in base_weights.items():
                for direction, factor in [
                    ("down", 1 - weight_delta),
                    ("up", 1 + weight_delta),
                ]:
                    weights = dict(base_weights)
                    weights[metric] = base_weight * factor
                    scores = competition_weighted_score(
                        grouped,
                        player_column=player_column,
                        competition_column="comparison_group",
                        exposure_column=exposure_column,
                        weights=weights,
                    )
                    scenario, summary = _scenario_frame(
                        role=role,
                        scope=scope,
                        baseline_grouped=grouped,
                        baseline_scores=base_scores,
                        alternative_scores=scores,
                        dimension="composite_weight",
                        scenario_id=f"{metric}_{direction}_{factor:.2f}",
                        parameter=f"{metric}: {base_weight:.6g} -> {weights[metric]:.6g}",
                        player_column=player_column,
                    )
                    details.append(scenario)
                    summaries.append(summary)

            samples = config.samples
            threshold_specs = (
                (
                    "minimum_pressure_exposure",
                    "batter_pressure_balls" if role == "batter" else "bowler_legal_pressure_balls",
                    getattr(
                        samples,
                        "batter_pressure_balls"
                        if role == "batter"
                        else "bowler_legal_pressure_balls",
                    ),
                    False,
                ),
                (
                    "minimum_innings_or_spells",
                    "batter_pressure_innings" if role == "batter" else "bowler_pressure_spells",
                    getattr(
                        samples,
                        "batter_pressure_innings" if role == "batter" else "bowler_pressure_spells",
                    ),
                    False,
                ),
                (
                    "minimum_balls_per_innings_or_spell",
                    "minimum_balls_per_innings_or_spell",
                    samples.minimum_balls_per_innings_or_spell,
                    True,
                ),
            )
            for dimension, setting, base_value, recalculates_metrics in threshold_specs:
                for factor in SENSITIVITY_FACTORS:
                    changed = max(1, int(math.ceil(base_value * factor)))
                    sample_config = config.model_copy(
                        update={"samples": samples.model_copy(update={setting: changed})}
                    )
                    if recalculates_metrics:
                        changed_metrics = _role_metrics(scope_states, role, sample_config)
                        _, scores = _rank_scope(
                            role,
                            scope_states,
                            changed_metrics,
                            sample_config,
                            scope if scope != "IPL_T20I" else "IPL_T20I",
                        )
                    else:
                        _, scores = _rank_scope(
                            role, scope_states, scope_metrics, sample_config, scope
                        )
                    scenario, summary = _scenario_frame(
                        role=role,
                        scope=scope,
                        baseline_grouped=grouped,
                        baseline_scores=base_scores,
                        alternative_scores=scores,
                        dimension=dimension,
                        scenario_id=f"{setting}_{changed}",
                        parameter=f"{setting}: {base_value} -> {changed}",
                        player_column=player_column,
                    )
                    details.append(scenario)
                    summaries.append(summary)
    return (
        pd.concat(details, ignore_index=True) if details else pd.DataFrame(),
        pd.DataFrame(summaries),
    )


def _mapping_sensitivity(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "rankings" / "scoring_mapping_sensitivity.csv"
    if not path.is_file():
        return pd.DataFrame(columns=["role", "player_id", "assumption_mapping_sensitive"])
    frame = pd.read_csv(path, dtype={"player_id": "string"})
    required = {"player_id", "ranking_track", "top10_membership_changed", "significant_change"}
    if not required.issubset(frame.columns):
        return pd.DataFrame(columns=["role", "player_id", "assumption_mapping_sensitive"])
    for column in ["top10_membership_changed", "significant_change"]:
        frame[column] = frame[column].astype("string").str.lower().isin({"true", "1", "yes"})
    frame["role"] = frame["ranking_track"]
    frame["assumption_mapping_sensitive"] = (
        frame["top10_membership_changed"] | frame["significant_change"]
    )
    frame["player_id"] = frame["player_id"].map(
        lambda value: _player_key(value) if pd.notna(value) else pd.NA
    )
    return frame.groupby(["role", "player_id"], as_index=False).agg(
        assumption_mapping_sensitive=("assumption_mapping_sensitive", "max")
    )


def _player_instability(
    bootstrap_summary: pd.DataFrame,
    sensitivity: pd.DataFrame,
    baseline_by_role_scope: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]],
    full_rankings: dict[str, pd.DataFrame],
    mapping_sensitivity: pd.DataFrame,
    *,
    top10_probability_threshold: float,
    mapping_assessed: bool,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for role in ROLES:
        player_column, _, _ = _role_columns(role)
        full = full_rankings[role]
        names = (
            full[[player_column, "player_name"]]
            .dropna(subset=[player_column])
            .drop_duplicates(player_column)
            .rename(columns={player_column: "player_id"})
        )
        names["player_id"] = names["player_id"].map(_player_key)
        role_mapping = mapping_sensitivity.loc[mapping_sensitivity["role"].eq(role)].rename(
            columns={"assumption_mapping_sensitive": "_mapping_sensitive"}
        )
        for scope in SCOPES:
            grouped, scores = baseline_by_role_scope[(role, scope)]
            base = (
                grouped[[player_column]]
                .drop_duplicates()
                .rename(columns={player_column: "player_id"})
            )
            base["player_id"] = base["player_id"].map(_player_key)
            base_scores = scores[[player_column, "rank", "composite_score"]].rename(
                columns={player_column: "player_id", "rank": "baseline_rank"}
            )
            base_scores["player_id"] = base_scores["player_id"].map(_player_key)
            base = base.merge(base_scores, on="player_id", how="left", validate="one_to_one")
            boot = bootstrap_summary.loc[
                bootstrap_summary["role"].eq(role) & bootstrap_summary["scope"].eq(scope)
            ].drop(columns=["player_name"], errors="ignore")
            boot["player_id"] = boot["player_id"].map(_player_key)
            bootstrap_columns = [
                "player_id",
                "top10_inclusion_probability",
                "median_rank",
                "rank_ci_low",
                "rank_ci_high",
                "median_composite_score",
                "score_ci_low",
                "score_ci_high",
                "pressure_metric_name",
                "pressure_metric_median",
                "pressure_metric_ci_low",
                "pressure_metric_ci_high",
                "valid_ranking_replicates",
                "valid_pressure_metric_replicates",
            ]
            base = base.merge(
                boot[bootstrap_columns],
                on="player_id",
                how="left",
                validate="one_to_one",
            )
            base = base.merge(names, on="player_id", how="left", validate="many_to_one")
            base["role"] = role
            base["scope"] = scope
            base["baseline_top10"] = pd.to_numeric(base["baseline_rank"], errors="coerce").le(10)
            probability = pd.to_numeric(
                base.get("top10_inclusion_probability", pd.Series(np.nan, index=base.index)),
                errors="coerce",
            )
            base["bootstrap_top10_unstable"] = base["baseline_top10"] & probability.lt(
                top10_probability_threshold
            ).fillna(True)
            role_sensitivity = sensitivity.loc[
                sensitivity["role"].eq(role) & sensitivity["scope"].eq(scope)
            ]
            for dimension, output in [
                ("composite_weight", "weight_sensitive"),
                (
                    "minimum_pressure_exposure",
                    "pressure_exposure_threshold_sensitive",
                ),
                (
                    "minimum_innings_or_spells",
                    "innings_or_spells_threshold_sensitive",
                ),
                (
                    "minimum_balls_per_innings_or_spell",
                    "per_spell_threshold_sensitive",
                ),
            ]:
                changed_ids = set(
                    role_sensitivity.loc[
                        role_sensitivity["dimension"].eq(dimension)
                        & role_sensitivity["top10_membership_changed"],
                        player_column,
                    ].map(_player_key)
                )
                base[output] = base["player_id"].map(_player_key).isin(changed_ids)
            base["sample_threshold_sensitive"] = base[
                [
                    "pressure_exposure_threshold_sensitive",
                    "innings_or_spells_threshold_sensitive",
                    "per_spell_threshold_sensitive",
                ]
            ].any(axis=1)
            if scope == "IPL_T20I":
                base = base.merge(
                    role_mapping[["player_id", "_mapping_sensitive"]],
                    on="player_id",
                    how="left",
                    validate="many_to_one",
                )
                base["assumption_mapping_sensitive"] = (
                    base["_mapping_sensitive"].fillna(False).astype(bool)
                )
                base["assumption_sensitivity_assessed"] = mapping_assessed
            else:
                base["assumption_mapping_sensitive"] = False
                base["assumption_sensitivity_assessed"] = False
            base["bootstrap_top10_stable"] = probability.ge(top10_probability_threshold).fillna(
                False
            )
            base["ranking_unstable"] = base[
                [
                    "bootstrap_top10_unstable",
                    "weight_sensitive",
                    "sample_threshold_sensitive",
                    "assumption_mapping_sensitive",
                ]
            ].any(axis=1)
            base["input_label"] = EXPLORATORY_LABEL
            base["assessment_label"] = ASSESSMENT_LABEL
            rows.append(base.drop(columns=["_mapping_sensitive"], errors="ignore"))
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _markdown_report(
    *,
    run_dir: Path,
    manifest: dict[str, Any],
    states: pd.DataFrame,
    checks: pd.DataFrame,
    input_issues: pd.DataFrame,
    bootstrap_summary: pd.DataFrame,
    sensitivity_summary: pd.DataFrame,
    instability: pd.DataFrame,
    replicates: int,
    seed: int,
    config: AppConfig,
    top10_probability_threshold: float,
) -> str:
    check_pass = int(checks["status"].eq("VALIDATED").sum())
    check_fail = int(checks["status"].eq("FAILED").sum())
    counts = (
        states.groupby("comparison_group")
        .agg(rows=("match_id", "size"), matches=("match_id", "nunique"))
        .to_dict(orient="index")
    )
    lines = [
        "# Statistical Ranking Validation Assessment",
        "",
        "> **ROBUSTNESS-ASSESSED — EXPLORATORY INPUTS.** This report assesses arithmetic",
        "> consistency, sampling uncertainty, and sensitivity. It does not source-confirm",
        "> scoring semantics or establish scientific validity.",
        "",
        "## Input and status",
        "",
        f"- Exploratory run: `{manifest.get('run_id', run_dir.name)}`",
        f"- Run status: `{manifest.get('status')}`",
        f"- Analysis mode: `{manifest.get('analysis_mode')}`",
        f"- Source label: `{manifest.get('output_label')}`",
        f"- Pressure-state rows analyzed: {len(states):,}",
        f"- Competition coverage: `{json.dumps(counts, sort_keys=True)}`",
        "- `Other` competitions are excluded from ranking validation, matching the "
        "ranking pipeline.",
        f"- Mathematical checks: {check_pass} VALIDATED; {check_fail} FAILED.",
        "- `VALIDATED` applies only to the explicitly named mathematical consistency checks below.",
        "",
        "## Mathematical consistency",
        "",
        "The checks recompute exported rate formulas, weighted-Z composite scores, ranks,",
        "Top-10 membership, and baseline scores from the saved pressure states using the",
        "project's current metric and ranking functions.",
        "",
        _markdown_table(
            checks[["role", "check_id", "status", "rows_checked", "failure_count", "description"]]
        ),
        "",
        "Top-10 CSV structural issues, including row-level detail, are exported to "
        "`ranking_input_issues.csv`.",
        _markdown_table(
            input_issues.groupby(["role", "source_file", "issue_id"], as_index=False)
            .size()
            .rename(columns={"size": "issue_count"})
            if not input_issues.empty
            else pd.DataFrame(columns=["role", "source_file", "issue_id", "issue_count"])
        ),
        "",
        "## Bootstrap method",
        "",
        f"- Match-cluster bootstrap, stratified by competition group; {replicates:,} replicates.",
        f"- Random seed: {seed}; percentile intervals at "
        f"{config.robustness.bootstrap_confidence_level:.0%}.",
        "- Each sampled match receives a unique bootstrap match ID so repeated "
        "draws remain separate innings/spells.",
        "- Top-10 inclusion probability uses every replicate in its denominator; "
        "ineligible or absent players count as not included.",
        "- Pressure-rate intervals use estimable replicates; valid replicate counts are exported.",
        f"- A baseline Top-10 player is flagged bootstrap-unstable below "
        f"{top10_probability_threshold:.0%} inclusion probability.",
        "- Batter uncertainty uses pressure strike rate; bowler uncertainty uses "
        "the regularised bowling strike rate.",
        "",
        _markdown_table(
            bootstrap_summary.groupby(["role", "scope"], as_index=False).agg(
                players=("player_id", "nunique"),
                mean_top10_probability=("top10_inclusion_probability", "mean"),
                players_above_probability_threshold=(
                    "top10_inclusion_probability",
                    lambda values: int(values.ge(top10_probability_threshold).sum()),
                ),
            )
        ),
        "",
        "## Weight and sample-threshold sensitivity",
        "",
        f"- Each composite weight is varied individually by +/- "
        f"{config.robustness.weight_perturbation:.0%}; signs are preserved and "
        "weights are not renormalized.",
        "- Minimum pressure-ball eligibility, minimum innings/spells, and "
        "minimum balls per innings/spell are varied to 75% and 125% of baseline "
        "(rounded up to a positive integer).",
        "- These are one-factor sensitivity checks, not a search for optimal "
        "weights or thresholds.",
        "",
        _markdown_table(
            sensitivity_summary.groupby(["role", "scope", "dimension"], as_index=False).agg(
                scenarios=("scenario_id", "nunique"),
                lowest_top10_overlap=("top10_overlap", "min"),
                highest_membership_changes=("players_with_membership_change", "max"),
            )
        ),
        "",
        "## Unstable and assumption-sensitive players",
        "",
        "A player is marked `ranking_unstable` if bootstrap Top-10 probability is below the",
        "stated threshold for a baseline Top-10 player, or if any weight, sample-threshold,",
        "or a mapping scenario changes Top-10 membership or shifts rank by at least",
        "five places. Mapping scenarios are",
        "hypothetical alternatives already present in the exploratory run; they are not",
        "source evidence or documented alternatives for the baseline interpretation.",
        "",
    ]
    unstable = instability.loc[instability["ranking_unstable"]].copy()
    if unstable.empty:
        lines.append("No players met the stated instability flags in this assessment.")
    else:
        columns = [
            "role",
            "scope",
            "player_name",
            "player_id",
            "baseline_rank",
            "top10_inclusion_probability",
            "weight_sensitive",
            "sample_threshold_sensitive",
            "assumption_mapping_sensitive",
        ]
        lines.append(
            _markdown_table(
                unstable.sort_values(["role", "scope", "baseline_rank"], na_position="last")[
                    columns
                ].head(60)
            )
        )
    lines.extend(
        [
            "",
            "## Limitations and interpretation",
            "",
            "- Input metrics use configured exploratory scoring assumptions; "
            "they are not source-confirmed.",
            "- This module does not verify source definitions, independent scorecards, "
            "or causal claims about pressure and performance.",
            "- Bootstrap intervals quantify match-sample variability conditional on "
            "the supplied data, filters, assumptions, and ranking model.",
            "- Weight and threshold sensitivity show model dependence; they do not "
            "prove that baseline choices are correct.",
            "- The competition split follows the existing classifier; `Other` "
            "competitions are not ranked.",
            "- Do not represent these outputs as source-validated or scientifically "
            "validated rankings.",
            "",
            "## Reproducible command",
            "",
            "```powershell",
            "uv run python scripts/validate_rankings.py `",
            f"  --run-dir artifacts/exploratory/{manifest.get('run_id', run_dir.name)} `",
            f"  --replicates {replicates} --seed {seed}",
            "```",
            "",
            "Detailed data are in the CSV files next to this report. Exploratory "
            "ranking files are read-only inputs to this assessment.",
            "",
        ]
    )
    return "\n".join(lines)


def validate_exploratory_rankings(
    run_dir: Path,
    *,
    config_path: Path,
    output_dir: Path | None = None,
    replicates: int = 500,
    seed: int | None = None,
    top10_probability_threshold: float = 0.80,
) -> dict[str, Any]:
    if replicates < 500:
        raise ValueError("At least 500 bootstrap replicates are required.")
    if not 0 < top10_probability_threshold <= 1:
        raise ValueError("Top-10 stability threshold must be in (0, 1].")
    run_dir = run_dir.resolve()
    manifest = _read_manifest(run_dir)
    config = load_config(config_path)
    active_seed = config.robustness.random_seed if seed is None else seed
    output = output_dir.resolve() if output_dir else run_dir / "validation"
    output.mkdir(parents=True, exist_ok=True)

    state_path = run_dir / "processed" / "pressure_states.parquet"
    if not state_path.is_file():
        raise FileNotFoundError(f"Saved pressure states not found: {state_path}")
    states = pd.read_parquet(state_path)
    required_states = {
        "match_id",
        "competition_id",
        "comparison_group",
        "winner_team_id",
        "is_high_pressure",
        "is_live_chase",
    }
    missing_states = required_states - set(states.columns)
    if missing_states:
        raise ValueError(f"Pressure states missing required columns: {sorted(missing_states)}")
    states = states.loc[
        states["winner_team_id"].notna() & states["comparison_group"].isin({"IPL", "T20I"})
    ].copy()
    if states.empty:
        raise ValueError("No winning IPL or T20I match states are available for validation.")

    full_rankings: dict[str, pd.DataFrame] = {}
    math_checks: list[pd.DataFrame] = []
    input_issue_frames: list[pd.DataFrame] = []
    metrics_by_role: dict[str, pd.DataFrame] = {}
    baseline_by_role_scope: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]] = {}
    for role in ROLES:
        rankings_dir = run_dir / "rankings"
        full_path = rankings_dir / f"{role}_full_rankings.csv"
        top_path = rankings_dir / f"top_10_{role}s.csv"
        if role == "batter":
            top_path = rankings_dir / "top_10_batters.csv"
        if not full_path.is_file() or not top_path.is_file():
            raise FileNotFoundError(
                f"Expected {role} full and Top-10 ranking files under {rankings_dir}."
            )
        player_column, _, _ = _role_columns(role)
        full = pd.read_csv(full_path, dtype={player_column: "string"})
        top10 = pd.read_csv(top_path, dtype={player_column: "string"})
        full_rankings[role] = full
        input_issue_frames.append(
            _input_file_issues(
                full,
                top10,
                role=role,
                full_path=full_path,
                top_path=top_path,
            )
        )
        role_checks = mathematical_consistency_checks(full, top10, role)
        role_checks["role"] = role
        math_checks.append(role_checks)
        metrics = _role_metrics(states, role, config)
        metrics_by_role[role] = metrics
        for scope in SCOPES:
            grouped, scores = _rank_scope(role, states, metrics, config, scope)
            baseline_by_role_scope[(role, scope)] = (grouped, scores)
            if scope == "IPL_T20I":
                reproduction = pd.DataFrame(
                    [_baseline_reproduction_check(full, grouped, scores, role)]
                )
                reproduction["role"] = role
                math_checks.append(reproduction)
                group_checks = _group_metric_checks(grouped, role)
                group_checks["role"] = role
                math_checks.append(group_checks)
    checks = pd.concat(math_checks, ignore_index=True)
    input_issues = pd.concat(input_issue_frames, ignore_index=True)

    bootstrap_rows = _bootstrap(
        states,
        config,
        replicates=replicates,
        seed=active_seed,
    )
    bootstrap_summaries: list[pd.DataFrame] = []
    full_name_maps = {
        role: dict(
            zip(
                full_rankings[role][_role_columns(role)[0]].map(_player_key),
                full_rankings[role]["player_name"].fillna("").astype(str),
                strict=True,
            )
        )
        for role in ROLES
    }
    scope_ranking_frames: list[pd.DataFrame] = []
    for role in ROLES:
        for scope in SCOPES:
            grouped, scores = baseline_by_role_scope[(role, scope)]
            scope_ranking_frames.append(
                _scope_ranking_output(
                    grouped,
                    scores,
                    role,
                    scope,
                    full_name_maps[role],
                )
            )
    scope_rankings = pd.concat(scope_ranking_frames, ignore_index=True)
    scope_top10 = (
        scope_rankings.loc[pd.to_numeric(scope_rankings["rank"], errors="coerce").notna()]
        .sort_values(["role", "scope", "rank", "player_id"], kind="stable")
        .groupby(["role", "scope"], sort=False)
        .head(10)
        .copy()
    )
    for role in ROLES:
        player_column, _, _ = _role_columns(role)
        for scope in SCOPES:
            grouped, scores = baseline_by_role_scope[(role, scope)]
            scope_states, _ = _scope_frames(states, metrics_by_role[role], scope)
            candidates = scope_states[player_column].dropna().astype(str).unique()
            bootstrap_summaries.append(
                _summarize_bootstrap(
                    bootstrap_rows,
                    role=role,
                    scope=scope,
                    candidates=candidates,
                    baseline=scores,
                    names=full_name_maps[role],
                    replicate_count=replicates,
                    confidence_level=config.robustness.bootstrap_confidence_level,
                )
            )
    bootstrap_summary = pd.concat(bootstrap_summaries, ignore_index=True)

    sensitivity_detail, sensitivity_summary = _sensitivity(
        states, metrics_by_role, baseline_by_role_scope, config
    )
    mapping_sensitivity = _mapping_sensitivity(run_dir)
    instability = _player_instability(
        bootstrap_summary,
        sensitivity_detail,
        baseline_by_role_scope,
        full_rankings,
        mapping_sensitivity,
        top10_probability_threshold=top10_probability_threshold,
        mapping_assessed=not mapping_sensitivity.empty,
    )

    checks.to_csv(output / "mathematical_checks.csv", index=False)
    input_issues.to_csv(output / "ranking_input_issues.csv", index=False)
    scope_rankings.to_csv(output / "scope_rankings.csv", index=False)
    scope_top10.to_csv(output / "scope_top10.csv", index=False)
    bootstrap_rows.to_csv(output / "bootstrap_replicates.csv", index=False)
    bootstrap_summary.to_csv(output / "bootstrap_summary.csv", index=False)
    sensitivity_detail.to_csv(output / "sensitivity_scenarios.csv", index=False)
    sensitivity_summary.to_csv(output / "sensitivity_summary.csv", index=False)
    instability.to_csv(output / "player_instability.csv", index=False)
    overall_status = (
        "ROBUSTNESS-ASSESSED_EXPLORATORY"
        if checks["status"].eq("VALIDATED").all()
        else "ROBUSTNESS-ASSESSED_EXPLORATORY_WITH_MATH_FAILURES"
    )
    report = _markdown_report(
        run_dir=run_dir,
        manifest=manifest,
        states=states,
        checks=checks,
        input_issues=input_issues,
        bootstrap_summary=bootstrap_summary,
        sensitivity_summary=sensitivity_summary,
        instability=instability,
        replicates=replicates,
        seed=active_seed,
        config=config,
        top10_probability_threshold=top10_probability_threshold,
    )
    (output / "validation_report.md").write_text(report, encoding="utf-8")
    result = {
        "assessment_label": ASSESSMENT_LABEL,
        "input_label": EXPLORATORY_LABEL,
        "overall_status": overall_status,
        "mathematical_status": (
            "VALIDATED" if checks["status"].eq("VALIDATED").all() else "FAILED"
        ),
        "mathematical_check_count": len(checks),
        "mathematical_failure_count": int(checks["status"].eq("FAILED").sum()),
        "bootstrap_replicates": replicates,
        "seed": active_seed,
        "run_id": manifest.get("run_id", run_dir.name),
        "output_dir": str(output),
        "scientific_validation_claim": False,
    }
    (output / "validation_manifest.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
