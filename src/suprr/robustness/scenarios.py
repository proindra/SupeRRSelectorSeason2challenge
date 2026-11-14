from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from suprr.config import AppConfig


def build_scenario_grid(
    config: AppConfig, revised_cases_verified: bool = False
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = [
        {
            "scenario_id": "base",
            "dimension": "base",
            "pressure_threshold": config.pressure.high_pressure_threshold,
            "clutch_threshold": config.pressure.clutch_threshold,
            "shrinkage_k": config.reliability.default_k_balls,
            "normal_baseline": "lower_pressure_chases",
            "comparison_group": "IPL_T20I",
            "include_revised_targets": False,
            "weight_adjustment": None,
        }
    ]
    for threshold in config.robustness.pressure_thresholds:
        if threshold == config.pressure.high_pressure_threshold:
            continue
        scenarios.append(
            {
                **scenarios[0],
                "scenario_id": f"pressure-{threshold:.2f}",
                "dimension": "pressure_threshold",
                "pressure_threshold": threshold,
            }
        )
    weight_names = list(config.pressure.weights.model_dump())
    base_weights = config.pressure.weights.model_dump()
    for weight_name in weight_names:
        for direction in (-1, 1):
            adjusted = dict(base_weights)
            adjusted[weight_name] *= 1 + direction * config.robustness.weight_perturbation
            total = sum(adjusted.values())
            adjusted = {key: value / total for key, value in adjusted.items()}
            scenarios.append(
                {
                    **scenarios[0],
                    "scenario_id": f"weight-{weight_name}-{'up' if direction > 0 else 'down'}",
                    "dimension": "pressure_weights",
                    "weight_adjustment": adjusted,
                }
            )
    for k in config.reliability.sensitivity_k:
        if k == config.reliability.default_k_balls:
            continue
        scenarios.append(
            {
                **scenarios[0],
                "scenario_id": f"shrinkage-k-{k}",
                "dimension": "shrinkage_k",
                "shrinkage_k": k,
            }
        )
    for threshold in config.robustness.clutch_thresholds:
        scenarios.append(
            {
                **scenarios[0],
                "scenario_id": f"clutch-{threshold:.2f}",
                "dimension": "clutch_threshold",
                "clutch_threshold": threshold,
            }
        )
    scenarios.extend(
        [
            {
                **scenarios[0],
                "scenario_id": "normal-baseline-first-innings-plus-low-pressure",
                "dimension": "normal_baseline",
                "normal_baseline": "first_innings_plus_lower_pressure",
            },
            {
                **scenarios[0],
                "scenario_id": "ipl-only",
                "dimension": "comparison_group",
                "comparison_group": "IPL",
            },
            {
                **scenarios[0],
                "scenario_id": "t20i-only",
                "dimension": "comparison_group",
                "comparison_group": "T20I",
            },
        ]
    )
    if revised_cases_verified:
        scenarios.append(
            {
                **scenarios[0],
                "scenario_id": "verified-revised-targets",
                "dimension": "revised_targets",
                "include_revised_targets": True,
            }
        )
    else:
        scenarios.append(
            {
                "scenario_id": "verified-revised-targets",
                "dimension": "revised_targets",
                "status": "skipped_unverified",
                "reason": "No verified revised-target effective timing is available.",
            }
        )
    return scenarios


def run_scenario_grid(
    config: AppConfig,
    evaluate: Callable[[AppConfig, dict[str, Any]], pd.DataFrame],
    *,
    player_column: str,
    revised_cases_verified: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    runs = []
    scenario_rows = build_scenario_grid(config, revised_cases_verified)
    all_players: set[object] = set()
    for scenario in scenario_rows:
        if scenario.get("status") == "skipped_unverified":
            runs.append({**scenario, "status": "skipped"})
            continue
        if scenario.get("dimension") == "clutch_threshold":
            runs.append(
                {
                    **scenario,
                    "status": "metric_only",
                    "reason": "Clutch threshold changes descriptive labels, not ranking inputs.",
                }
            )
            continue
        rankings = evaluate(config, scenario)
        if not {player_column, "rank"}.issubset(rankings.columns):
            raise ValueError("Scenario evaluator must return player IDs and ranks.")
        all_players.update(rankings[player_column].dropna().tolist())
        top_ids = set(rankings.nsmallest(10, "rank")[player_column])
        runs.append(
            {
                **scenario,
                "status": "valid",
                "eligible_players": int(rankings["rank"].notna().sum()),
                "top_10_ids": top_ids,
            }
        )
    valid = [run for run in runs if run["status"] == "valid"]
    valid_count = len(valid)
    appearances: dict[object, int] = {}
    for run in valid:
        for player_id in run["top_10_ids"]:
            appearances[player_id] = appearances.get(player_id, 0) + 1
    stability = pd.DataFrame(
        [
            {
                player_column: player_id,
                "top_10_scenarios": appearances.get(player_id, 0),
                "valid_scenarios": valid_count,
                "stability_score": (
                    appearances.get(player_id, 0) / valid_count if valid_count else None
                ),
                "unstable": (
                    appearances.get(player_id, 0) / valid_count
                    < config.robustness.stability_flag_threshold
                    if valid_count
                    else None
                ),
            }
            for player_id in all_players
        ]
    )
    serializable_runs = []
    for run in runs:
        cleaned = dict(run)
        if isinstance(cleaned.get("top_10_ids"), set):
            cleaned["top_10_ids"] = "|".join(sorted(map(str, cleaned["top_10_ids"])))
        if "weight_adjustment" in cleaned and isinstance(cleaned["weight_adjustment"], dict):
            cleaned["weight_adjustment"] = str(cleaned["weight_adjustment"])
        serializable_runs.append(cleaned)
    return pd.DataFrame(serializable_runs), stability


def stability_adjusted_top10(
    rankings: pd.DataFrame,
    stability: pd.DataFrame,
    *,
    player_column: str,
    threshold: float = 0.50,
) -> pd.DataFrame:
    if not 0 <= threshold <= 1:
        raise ValueError("Stability threshold must be between zero and one.")
    base = rankings.loc[rankings["rank"].notna()].nsmallest(10, "rank").copy()
    scored = rankings.merge(
        stability[[player_column, "stability_score"]],
        on=player_column,
        how="left",
        validate="one_to_one",
    )
    outside = scored.loc[
        scored["rank"].gt(10) & scored["stability_score"].ge(threshold)
    ].sort_values("rank", kind="stable")
    used_replacements: set[object] = set()
    replacements = iter(outside[player_column].tolist())
    adjusted_rows = []
    for position, row in enumerate(base.to_dict(orient="records"), start=1):
        player_id = row[player_column]
        stability_score = stability.loc[stability[player_column].eq(player_id), "stability_score"]
        score = float(stability_score.iloc[0]) if not stability_score.empty else 0.0
        is_unstable = score < threshold
        replacement_id = None
        if is_unstable:
            replacement_id = next(
                (candidate for candidate in replacements if candidate not in used_replacements),
                None,
            )
        if replacement_id is not None:
            used_replacements.add(replacement_id)
            adjusted_rows.append(
                {
                    "base_rank": position,
                    player_column: player_id,
                    "base_stability_score": score,
                    "unstable_base_player": True,
                    "adjusted_player_id": replacement_id,
                    "replacement_applied": True,
                    "replacement_rule": (
                        "highest-ranked eligible outside candidate with stability >= threshold"
                    ),
                }
            )
        else:
            adjusted_rows.append(
                {
                    "base_rank": position,
                    player_column: player_id,
                    "base_stability_score": score,
                    "unstable_base_player": is_unstable,
                    "adjusted_player_id": player_id,
                    "replacement_applied": False,
                    "replacement_rule": None,
                }
            )
    return pd.DataFrame(adjusted_rows)
