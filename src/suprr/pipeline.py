from __future__ import annotations

import hashlib
import json
import platform
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from suprr.config import AppConfig, load_config
from suprr.exports import (
    write_csv,
    write_json,
    write_methodology_report,
    write_results_pdf,
)
from suprr.features.innings_state import derive_chase_states
from suprr.ingestion.loader import load_source_files
from suprr.ingestion.manifest import build_data_manifest
from suprr.ingestion.mapping import canonicalize_sources, normalize_source_mappings
from suprr.metrics.batter import calculate_batter_metrics
from suprr.metrics.bowler import calculate_bowler_metrics
from suprr.metrics.competition import add_comparison_group
from suprr.ranking.rankings import rank_batters, rank_bowlers
from suprr.robustness.bootstrap import match_level_bootstrap, summarize_bootstrap
from suprr.robustness.scenarios import run_scenario_grid, stability_adjusted_top10
from suprr.robustness.scoring_mapping import hypothetical_scoring_mappings
from suprr.robustness.sensitivity import batter_sensitivity, bowler_sensitivity
from suprr.robustness.split_half import split_half_checks
from suprr.validation.audit import audit_sources
from suprr.validation.investigations import (
    investigate_sources,
    write_investigation_reports,
)
from suprr.validation.pressure_gate import PressureValidationResult, validate_pressure_model
from suprr.validation.reconciliation import write_reconciliation_reports
from suprr.validation.report import write_audit_report


def _fingerprint(manifest: list[dict[str, object]]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ranked_profiles(
    grouped: pd.DataFrame,
    scores: pd.DataFrame,
    *,
    player_column: str,
    name_lookup: pd.DataFrame,
    count_columns: list[str],
    rate_columns: list[str],
    exposure_column: str,
    comparison_group_column: str = "comparison_group",
) -> pd.DataFrame:
    counts = grouped.groupby(player_column, as_index=False)[count_columns].sum()
    profiles = counts
    contexts = (
        grouped.groupby(player_column)[comparison_group_column]
        .agg(lambda values: ", ".join(sorted(set(values.dropna().astype(str)))))
        .rename("comparison_context")
        .reset_index()
    )
    profiles = profiles.merge(
        contexts,
        on=player_column,
        how="left",
        validate="one_to_one",
    )
    for column in rate_columns:
        weighted = grouped.assign(_weighted=grouped[column] * grouped[exposure_column])
        aggregate = weighted.groupby(player_column, as_index=False).agg(
            _weighted=("_weighted", "sum"), _exposure=(exposure_column, "sum")
        )
        aggregate[column] = aggregate["_weighted"] / aggregate["_exposure"].replace(0, pd.NA)
        profiles = profiles.merge(
            aggregate[[player_column, column]],
            on=player_column,
            how="left",
            validate="one_to_one",
        )
    score_columns = {
        column: f"{column}_weighted_z"
        for column in scores.columns
        if column not in {player_column, "composite_score", "rank", "complete_metrics"}
    }
    profiles = profiles.merge(
        scores.rename(columns=score_columns),
        on=player_column,
        how="outer",
        validate="one_to_one",
    )
    return profiles.merge(name_lookup, on=player_column, how="left", validate="many_to_one")


def _player_name_lookup(mapping: pd.DataFrame) -> pd.DataFrame:
    names = mapping[["player_id", "player_name"]].dropna().drop_duplicates()
    name_counts = names.groupby("player_id")["player_name"].nunique()
    unique_ids = name_counts[name_counts.eq(1)].index
    lookup = (
        names.loc[names["player_id"].isin(unique_ids)]
        .drop_duplicates("player_id")
        .rename(columns={"player_id": "player_id", "player_name": "player_name"})
    )
    return lookup


def _pressure_validation_csv(result: PressureValidationResult) -> pd.DataFrame:
    rows = [
        {
            "record_type": "summary",
            "name": key,
            "status": result.status,
            "value": value,
            "details": "",
        }
        for key, value in result.summary.items()
    ]
    rows.extend(
        {
            "record_type": "outcome_gradient",
            "name": row["pressure_band"],
            "status": row["interpretation"],
            "value": row["win_rate"],
            "details": json.dumps(row, default=str),
        }
        for row in result.outcome_gradient
    )
    rows.extend(
        {
            "record_type": "ablation",
            "name": row["name"],
            "status": row["status"],
            "value": row.get("auc"),
            "details": json.dumps(row, default=str),
        }
        for row in result.ablations
    )
    rows.extend(
        {
            "record_type": "diagnostic",
            "name": f"diagnostic_{index + 1}",
            "status": "review",
            "value": None,
            "details": diagnostic,
        }
        for index, diagnostic in enumerate(result.diagnostics)
    )
    return pd.DataFrame(rows)


def _sensitivity_overlap(frame: pd.DataFrame, player_column: str) -> dict[str, int]:
    if frame.empty or not {"variant", player_column, "rank"}.issubset(frame.columns):
        return {}
    base = set(
        frame.loc[
            frame["variant"].eq(frame["variant"].iloc[0]) & frame["rank"].le(10),
            player_column,
        ]
    )
    return {
        str(variant): int(len(base & set(group.loc[group["rank"].le(10), player_column].dropna())))
        for variant, group in frame.groupby("variant", sort=False)
    }


def _write_run_manifest(
    report_dir: Path,
    *,
    run_id: str,
    config: AppConfig,
    data_fingerprint: str,
    data_manifest: list[dict[str, object]],
    status: str,
    started_at: str,
    completed_at: str,
    full_robustness_requested: bool = False,
    pressure_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "analysis_mode": "ASSUMPTION_BASED_EXPLORATORY",
        "full_robustness_requested": full_robustness_requested,
        "output_label": "EXPLORATORY",
        "config_version": config.version,
        "configuration": config.model_dump(mode="json"),
        "config_fingerprint": hashlib.sha256(config.model_dump_json().encode("utf-8")).hexdigest(),
        "random_seed": config.random_seed,
        "python_version": platform.python_version(),
        "data_fingerprint": data_fingerprint,
        "data_manifest": data_manifest,
        "pressure_validation": pressure_validation,
    }
    write_json(report_dir / "run_manifest.json", payload)
    return payload


def _rank_role_for_states(
    states: pd.DataFrame,
    config: AppConfig,
    competition_table: pd.DataFrame,
    role: str,
    *,
    k: int | None = None,
) -> pd.DataFrame:
    states = states.loc[
        states["winner_team_id"].notna() & states["comparison_group"].isin({"IPL", "T20I"})
    ].copy()
    if role == "batter":
        metrics = calculate_batter_metrics(states, config)
        metrics = add_comparison_group(metrics, competition_table, config)
        metrics = metrics.loc[metrics["comparison_group"].isin({"IPL", "T20I"})]
        _, scores = rank_batters(metrics, states, config, k=k)
        player_column = "striker_id"
    elif role == "bowler":
        metrics = calculate_bowler_metrics(states, config)
        metrics = add_comparison_group(metrics, competition_table, config)
        metrics = metrics.loc[metrics["comparison_group"].isin({"IPL", "T20I"})]
        _, scores = rank_bowlers(metrics, states, config, k=k)
        player_column = "bowler_id"
    else:
        raise ValueError(f"Unknown player role: {role}")
    return scores[[player_column, "composite_score", "rank"]]


def _scenario_states(
    source_states: pd.DataFrame,
    config: AppConfig,
    scenario: dict[str, Any],
) -> pd.DataFrame:
    result = source_states.copy()
    weights = scenario.get("weight_adjustment")
    if weights:
        result["pressure_score"] = (
            weights["required_rate"] * result["R"]
            + weights["wickets_lost"] * result["W"]
            + weights["chase_difficulty"] * result["D"]
            + weights["innings_stage"] * result["S"]
        ).where(result["is_live_chase"])
    result["is_high_pressure"] = (
        result["pressure_score"]
        .ge(scenario.get("pressure_threshold", config.pressure.high_pressure_threshold))
        .fillna(False)
    )
    return result


def _scoring_mapping_sensitivity(
    *,
    deliveries: pd.DataFrame,
    matches: pd.DataFrame,
    config: AppConfig,
    competition_table: pd.DataFrame,
    over_base: int,
    verified_super_over_keys: set[tuple[str, int]],
    baseline_scores: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    detail_rows: list[pd.DataFrame] = []
    summary_rows: list[dict[str, Any]] = []
    scenario_manifest: list[dict[str, Any]] = []
    seasons = competition_table[["competition_id", "season"]].drop_duplicates(
        "competition_id"
    )

    for scenario in hypothetical_scoring_mappings(config):
        scenario_states = derive_chase_states(
            deliveries,
            matches,
            scenario.config,
            over_base=over_base,
            verified_super_over_keys=verified_super_over_keys,
        )
        scenario_states = add_comparison_group(
            scenario_states, competition_table, scenario.config
        ).merge(seasons, on="competition_id", how="left", validate="many_to_one")
        pressure_validation = validate_pressure_model(
            scenario_states, matches, scenario.config
        )
        scenario_manifest.append(
            {
                "scenario_id": scenario.scenario_id,
                "description": scenario.description,
                "status": "HYPOTHETICAL_SENSITIVITY_ONLY",
                "used_for_primary_rankings": False,
                "source_confirmed": False,
                "pressure_validation_status": pressure_validation.status,
                "scoring_override": scenario.config.scoring.model_dump(mode="json"),
            }
        )

        for role, player_column in (
            ("batter", "striker_id"),
            ("bowler", "bowler_id"),
        ):
            baseline = baseline_scores[role]
            baseline_top = set(
                baseline.loc[baseline["rank"].le(10), player_column].dropna()
            )
            if not pressure_validation.passed:
                summary_rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "scenario_description": scenario.description,
                        "ranking_track": role,
                        "scenario_status": "NOT_RUN_PRESSURE_VALIDATION_FAILED",
                        "pressure_validation_status": pressure_validation.status,
                        "baseline_top10_count": len(baseline_top),
                        "scenario_top10_count": None,
                        "top10_overlap": None,
                        "top10_added_player_ids": None,
                        "top10_removed_player_ids": None,
                        "players_with_significant_change": None,
                    }
                )
                continue

            alternative = _rank_role_for_states(
                scenario_states, scenario.config, competition_table, role
            )
            alternative_top = set(
                alternative.loc[alternative["rank"].le(10), player_column].dropna()
            )
            combined = baseline[
                [player_column, "composite_score", "rank"]
            ].merge(
                alternative[[player_column, "composite_score", "rank"]],
                on=player_column,
                how="outer",
                suffixes=("_baseline", "_scenario"),
                validate="one_to_one",
            )
            combined["scenario_id"] = scenario.scenario_id
            combined["scenario_description"] = scenario.description
            combined["ranking_track"] = role
            combined["scenario_status"] = "HYPOTHETICAL_SENSITIVITY_ONLY"
            combined["pressure_validation_status"] = pressure_validation.status
            scenario_rank = pd.to_numeric(
                combined["rank_scenario"], errors="coerce"
            ).astype("float64")
            baseline_rank = pd.to_numeric(
                combined["rank_baseline"], errors="coerce"
            ).astype("float64")
            combined["rank_change"] = scenario_rank - baseline_rank
            combined["baseline_top10"] = combined["rank_baseline"].le(10).fillna(False)
            combined["scenario_top10"] = combined["rank_scenario"].le(10).fillna(False)
            combined["top10_membership_changed"] = (
                combined["baseline_top10"] != combined["scenario_top10"]
            )
            combined["significant_change"] = combined["top10_membership_changed"] | (
                combined["rank_change"].abs().ge(5).fillna(False)
            )
            detail_rows.append(combined)
            summary_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "scenario_description": scenario.description,
                    "ranking_track": role,
                    "scenario_status": "RANKED_HYPOTHETICAL_ONLY",
                    "pressure_validation_status": pressure_validation.status,
                    "baseline_top10_count": len(baseline_top),
                    "scenario_top10_count": len(alternative_top),
                    "top10_overlap": len(baseline_top & alternative_top),
                    "top10_added_player_ids": ", ".join(
                        sorted(str(value) for value in alternative_top - baseline_top)
                    ),
                    "top10_removed_player_ids": ", ".join(
                        sorted(str(value) for value in baseline_top - alternative_top)
                    ),
                    "players_with_significant_change": int(
                        combined["significant_change"].sum()
                    ),
                }
            )
    details = (
        pd.concat(detail_rows, ignore_index=True)
        if detail_rows
        else pd.DataFrame(
            columns=[
                "scenario_id",
                "scenario_description",
                "ranking_track",
                "scenario_status",
                "pressure_validation_status",
                "player_id",
            ]
        )
    )
    if not details.empty:
        details = details.rename(
            columns={
                "striker_id": "player_id",
                "bowler_id": "player_id",
                "composite_score_baseline": "baseline_score",
                "composite_score_scenario": "scenario_score",
                "rank_baseline": "baseline_rank",
                "rank_scenario": "scenario_rank",
            }
        )
        details.insert(0, "output_label", "EXPLORATORY")
        details.insert(1, "analysis_mode", "ASSUMPTION_BASED_EXPLORATORY")
    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary.insert(0, "output_label", "EXPLORATORY")
        summary.insert(1, "analysis_mode", "ASSUMPTION_BASED_EXPLORATORY")
    return details, summary, scenario_manifest


def _write_scoring_mapping_report(path: Path, summary: pd.DataFrame) -> None:
    lines = [
        "# Exploratory Scoring-Mapping Sensitivity",
        "",
        "**EXPLORATORY only.** The baseline mappings are assumptions and are not "
        "source-confirmed. Alternative mappings below are hypothetical sensitivity tests and "
        "are not used for the primary exploratory rankings.",
        "",
        "A top-10 overlap is the count of players shared with the baseline top 10 for that role. "
        "A significant change means top-10 membership changed or rank moved by at least five "
        "places. Alternative scenarios with failed pressure validation do not produce rankings.",
        "",
        "| Scenario | Track | Status | Pressure validation | Top-10 overlap | Added | "
        "Removed | Significant changes |",
        "|---|---|---|---|---:|---|---|---:|",
    ]
    for row in summary.to_dict(orient="records"):
        lines.append(
            "| {scenario_id} | {ranking_track} | {scenario_status} | "
            "{pressure_validation_status} | {top10_overlap} | {top10_added_player_ids} | "
            "{top10_removed_player_ids} | {players_with_significant_change} |".format(
                **{
                    key: "" if pd.isna(value) else value
                    for key, value in row.items()
                }
            )
        )
    lines.extend(
        [
            "",
            "These comparisons quantify dependence on unresolved source semantics; they do not "
            "establish which interpretation is correct.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _add_first_innings_baseline(
    states: pd.DataFrame,
    deliveries: pd.DataFrame,
    matches: pd.DataFrame,
    competition_table: pd.DataFrame,
    config: AppConfig,
    over_base: int,
) -> pd.DataFrame:
    first = deliveries.loc[pd.to_numeric(deliveries["innings"], errors="coerce").eq(1)].copy()
    first = first.merge(
        matches[["match_id", "competition_id", "winner_team_id", "match_date"]],
        on="match_id",
        how="left",
        validate="many_to_one",
    )
    first = first.loc[first["winner_team_id"].notna()].copy()
    from suprr.features.phases import add_phase
    from suprr.validation.scoring_rules import extra_category

    first["extras_category"] = first["extras_type"].map(lambda value: extra_category(value, config))
    first["is_live_chase"] = True
    first["is_high_pressure"] = False
    first["pressure_score"] = pd.NA
    first["R"] = pd.NA
    first["W"] = pd.NA
    first["D"] = pd.NA
    first["S"] = pd.NA
    first = add_phase(first, config, over_base=over_base)
    first = add_comparison_group(first, competition_table, config)
    return pd.concat([states, first], ignore_index=True, sort=False)


def run_pipeline(
    project_dir: Path | str,
    *,
    raw_dir: Path | str | None = None,
    config_path: Path | str | None = None,
    full_robustness: bool = False,
    mapping_overrides: Mapping[str, Mapping[str, str | None]] | None = None,
) -> dict[str, Any]:
    root = Path(project_dir)
    source_dir = Path(raw_dir) if raw_dir else root / "data" / "raw"
    settings_path = Path(config_path) if config_path else root / "config" / "default.yaml"
    config = load_config(settings_path)
    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC).isoformat()
    mode = "ASSUMPTION_BASED_EXPLORATORY"
    output_root = root / "artifacts" / "exploratory" / run_id
    report_dir = output_root / "reports"
    rankings_dir = output_root / "rankings"

    run_settings = config.model_dump(mode="json")
    run_settings["analysis_mode"] = mode
    run_settings["output_label"] = "EXPLORATORY"
    run_settings["full_robustness_requested"] = full_robustness

    sources = load_source_files(source_dir)
    if mapping_overrides:
        sources = normalize_source_mappings(sources, config, mapping_overrides)
    investigation = investigate_sources(sources, config)
    write_investigation_reports(investigation, report_dir, analysis_mode=mode)
    write_reconciliation_reports(sources, report_dir, analysis_mode=mode)
    audit = audit_sources(sources, config, investigation)
    data_manifest = build_data_manifest(source_dir, sources)
    fingerprint = _fingerprint(data_manifest)
    write_audit_report(audit, report_dir, analysis_mode=mode)

    canonical = canonicalize_sources(sources, config)
    matches = canonical["matches"]
    deliveries = canonical["deliveries"]
    over_base = int(audit.checks["over_number_convention"]["inferred_base"])
    verified_super_over_keys = {
        (str(item["match_id"]), int(item["innings"]))
        for item in audit.checks["super_over_reconciliation"]["verified_innings"]
    }
    states = derive_chase_states(
        deliveries,
        matches,
        config,
        over_base=over_base,
        verified_super_over_keys=verified_super_over_keys,
    )
    competition_table = canonical["competitions"]
    states = add_comparison_group(states, competition_table, config)
    seasons = competition_table[["competition_id", "season"]].drop_duplicates("competition_id")
    states = states.merge(
        seasons,
        on="competition_id",
        how="left",
        validate="many_to_one",
    )
    processed_dir = output_root / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    states.to_parquet(processed_dir / "pressure_states.parquet", index=False)
    pressure_validation = validate_pressure_model(states, matches, config)
    validation_dict = pressure_validation.to_dict()
    validation_dict["analysis_mode"] = mode
    validation_dict["output_label"] = "EXPLORATORY"
    write_json(report_dir / "pressure_validation.json", validation_dict)
    write_csv(
        rankings_dir / "pressure_validation.csv",
        _pressure_validation_csv(pressure_validation),
    )
    if not pressure_validation.passed:
        blockers = pressure_validation.diagnostics or [
            "Pressure-model validation did not pass its decision rule."
        ]
        write_methodology_report(
            report_dir / "methodology_and_results.md",
            status=pressure_validation.status,
            blockers=blockers,
            pressure_validation=validation_dict,
            config_version=config.version,
            data_fingerprint=fingerprint,
            settings=run_settings,
        )
        _write_run_manifest(
            report_dir,
            run_id=run_id,
            config=config,
            data_fingerprint=fingerprint,
            data_manifest=data_manifest,
            status=pressure_validation.status,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat(),
            full_robustness_requested=full_robustness,
            pressure_validation=validation_dict,
        )
        return {
            "status": pressure_validation.status,
            "run_id": run_id,
            "analysis_mode": mode,
            "pressure_validation": pressure_validation,
            "output_dir": str(output_root),
        }

    valid_states = states.loc[
        states["winner_team_id"].notna() & states["comparison_group"].isin({"IPL", "T20I"})
    ].copy()
    batter_metrics = calculate_batter_metrics(valid_states, config)
    bowler_metrics = calculate_bowler_metrics(valid_states, config)
    batter_metrics = add_comparison_group(batter_metrics, competition_table, config)
    bowler_metrics = add_comparison_group(bowler_metrics, competition_table, config)
    batter_metrics = batter_metrics.loc[batter_metrics["comparison_group"].isin({"IPL", "T20I"})]
    bowler_metrics = bowler_metrics.loc[bowler_metrics["comparison_group"].isin({"IPL", "T20I"})]
    batter_states = valid_states.loc[valid_states["comparison_group"].isin({"IPL", "T20I"})]
    batter_grouped, batter_scores = rank_batters(batter_metrics, batter_states, config)
    bowler_grouped, bowler_scores = rank_bowlers(bowler_metrics, batter_states, config)
    name_lookup = _player_name_lookup(canonical["player_team_mapping"])
    batter_full = _ranked_profiles(
        batter_grouped,
        batter_scores,
        player_column="striker_id",
        name_lookup=name_lookup.rename(columns={"player_id": "striker_id"}),
        count_columns=[
            "pressure_runs",
            "pressure_balls",
            "pressure_innings",
            "qualifying_innings",
            "fours",
            "sixes",
            "dots",
            "dismissals",
        ],
        rate_columns=[
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
        ],
        exposure_column="pressure_balls",
    )
    bowler_full = _ranked_profiles(
        bowler_grouped,
        bowler_scores,
        player_column="bowler_id",
        name_lookup=name_lookup.rename(columns={"player_id": "bowler_id"}),
        count_columns=[
            "pressure_wickets",
            "pressure_conceded_runs",
            "legal_pressure_balls",
            "pressure_spells",
            "qualifying_spells",
            "dots",
            "fours",
            "sixes",
        ],
        rate_columns=[
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
        ],
        exposure_column="legal_pressure_balls",
    )
    batter_full = batter_full.sort_values("rank", na_position="last", kind="stable")
    bowler_full = bowler_full.sort_values("rank", na_position="last", kind="stable")
    batter_top10 = batter_full.loc[batter_full["rank"].le(10)].head(10).copy()
    bowler_top10 = bowler_full.loc[bowler_full["rank"].le(10)].head(10).copy()
    batter_sensitivity_table: pd.DataFrame | None = None
    bowler_sensitivity_table: pd.DataFrame | None = None
    mapping_summary: pd.DataFrame | None = None
    if full_robustness:
        batter_sensitivity_table = batter_sensitivity(batter_metrics, batter_states, config)
        bowler_sensitivity_table = bowler_sensitivity(bowler_metrics, batter_states, config)
        mapping_sensitivity, mapping_summary, mapping_scenarios = (
            _scoring_mapping_sensitivity(
                deliveries=deliveries,
                matches=matches,
                config=config,
                competition_table=competition_table,
                over_base=over_base,
                verified_super_over_keys=verified_super_over_keys,
                baseline_scores={"batter": batter_scores, "bowler": bowler_scores},
            )
        )
        write_csv(rankings_dir / "scoring_mapping_sensitivity.csv", mapping_sensitivity)
        write_csv(report_dir / "scoring_mapping_sensitivity_summary.csv", mapping_summary)
        write_json(report_dir / "scoring_mapping_scenarios.json", mapping_scenarios)
        _write_scoring_mapping_report(
            report_dir / "scoring_mapping_sensitivity.md", mapping_summary
        )
    for frame in (batter_full, bowler_full, batter_top10, bowler_top10):
        frame.insert(0, "output_label", "EXPLORATORY")
        frame.insert(1, "analysis_mode", mode)
    for frame in (batter_sensitivity_table, bowler_sensitivity_table):
        if frame is not None:
            frame.insert(0, "output_label", "EXPLORATORY")
            frame.insert(1, "analysis_mode", mode)
    write_csv(rankings_dir / "batter_full_rankings.csv", batter_full)
    write_csv(rankings_dir / "bowler_full_rankings.csv", bowler_full)
    if batter_sensitivity_table is not None and bowler_sensitivity_table is not None:
        write_csv(rankings_dir / "batter_sensitivity.csv", batter_sensitivity_table)
        write_csv(rankings_dir / "bowler_sensitivity.csv", bowler_sensitivity_table)
    if full_robustness:

        def make_evaluator(player_role: str):
            def evaluate(sample: pd.DataFrame) -> pd.DataFrame:
                return _rank_role_for_states(
                    sample,
                    config,
                    competition_table,
                    player_role,
                )

            return evaluate

        def scenario_evaluator(role: str):
            def evaluate(active_config: AppConfig, scenario: dict[str, Any]) -> pd.DataFrame:
                scenario_frame = _scenario_states(states, active_config, scenario)
                group = scenario.get("comparison_group", "IPL_T20I")
                if group in {"IPL", "T20I"}:
                    scenario_frame = scenario_frame.loc[
                        scenario_frame["comparison_group"].eq(group)
                    ]
                if scenario.get("normal_baseline") == "first_innings_plus_lower_pressure":
                    scenario_frame = _add_first_innings_baseline(
                        scenario_frame,
                        deliveries,
                        matches,
                        competition_table,
                        active_config,
                        over_base,
                    )
                if group in {"IPL", "T20I"}:
                    scenario_frame = scenario_frame.loc[
                        scenario_frame["comparison_group"].eq(group)
                    ]
                return _rank_role_for_states(
                    scenario_frame,
                    active_config,
                    competition_table,
                    role,
                    k=int(scenario.get("shrinkage_k", active_config.reliability.default_k_balls)),
                )

            return evaluate

        scenario_runs: list[pd.DataFrame] = []
        stability_tables: list[pd.DataFrame] = []
        adjusted_lists: list[pd.DataFrame] = []
        bootstrap_summaries: list[pd.DataFrame] = []
        for role, player_column in [("batter", "striker_id"), ("bowler", "bowler_id")]:
            runs, stability = run_scenario_grid(
                config,
                scenario_evaluator(role),
                player_column=player_column,
                revised_cases_verified=False,
            )
            runs["role"] = role
            stability["role"] = role
            scenario_runs.append(runs)
            stability_tables.append(stability)
            base_scores = batter_scores if role == "batter" else bowler_scores
            adjusted = stability_adjusted_top10(
                base_scores,
                stability,
                player_column=player_column,
                threshold=config.robustness.stability_flag_threshold,
            )
            adjusted["role"] = role
            adjusted_lists.append(adjusted)
            evaluator = make_evaluator(role)
            bootstrap = match_level_bootstrap(
                valid_states,
                evaluator,
                player_column=player_column,
                replicates=config.robustness.bootstrap_replicates,
                seed=config.robustness.random_seed,
            )
            write_csv(
                rankings_dir / f"{role}_bootstrap_replicates.csv",
                bootstrap,
            )
            summary = summarize_bootstrap(
                bootstrap,
                player_column=player_column,
                confidence_level=config.robustness.bootstrap_confidence_level,
            )
            summary["role"] = role
            bootstrap_summaries.append(summary)
            write_csv(rankings_dir / f"{role}_bootstrap_summary.csv", summary)
            split_checks = split_half_checks(
                valid_states,
                evaluator,
                player_column=player_column,
            )
            split_checks["role"] = role
            write_csv(rankings_dir / f"{role}_split_half.csv", split_checks)
        write_csv(
            rankings_dir / "scenario_runs.csv",
            pd.concat(scenario_runs, ignore_index=True),
        )
        write_csv(
            rankings_dir / "scenario_stability.csv",
            pd.concat(stability_tables, ignore_index=True),
        )
        write_csv(
            rankings_dir / "stability_adjusted_top10.csv",
            pd.concat(adjusted_lists, ignore_index=True),
        )
        write_csv(
            rankings_dir / "bootstrap_results.csv",
            pd.concat(bootstrap_summaries, ignore_index=True),
        )

    complete = len(batter_top10) == 10 and len(bowler_top10) == 10
    status = "EXPLORATORY_COMPLETE" if complete else "INSUFFICIENT_ELIGIBLE_PLAYERS"
    final_blockers = (
        []
        if complete
        else [
            f"Only {len(batter_top10)} batter(s) and {len(bowler_top10)} bowler(s) "
            "have complete eligible ranking scores; no complete Top 10 can be reported."
        ]
    )
    unconfirmed_source_evidence = [
        gate
        for gate in audit.checks.get("gate_statuses", [])
        if gate.get("status") in {"INFERRED", "UNRESOLVED"}
    ]
    write_json(
        report_dir / "exploratory_assumption_status.json",
        {
            "analysis_mode": mode,
            "output_label": "EXPLORATORY",
            "ranking_status": status,
            "assumptions_are_source_confirmed": False,
            "selected_assumptions": config.scoring.model_dump(mode="json"),
            "unconfirmed_source_evidence": unconfirmed_source_evidence,
            "pressure_validation_status": pressure_validation.status,
            "confirmed_exclusions": {
                "super_overs": {
                    "innings_groups": int(
                        audit.checks.get("super_over_reconciliation", {}).get(
                            "innings_groups", 0
                        )
                    ),
                    "delivery_rows": int(
                        audit.checks.get("super_over_reconciliation", {}).get(
                            "delivery_rows", 0
                        )
                    ),
                    "matches": int(
                        audit.checks.get("super_over_reconciliation", {}).get(
                            "matches", 0
                        )
                    ),
                },
                "revised_conditions": {
                    "matches": int(
                        audit.checks.get("source_investigation_summary", {}).get(
                            "revised_match_count", 0
                        )
                    ),
                    "effective_target_timing_available": False,
                },
            },
            "mapping_sensitivity_file": (
                "rankings/scoring_mapping_sensitivity.csv"
                if mapping_summary is not None
                else None
            ),
            "mapping_sensitivity_status": (
                "COMPUTED" if mapping_summary is not None else "NOT_RUN"
            ),
            "mapping_sensitivity_scenarios_are_hypothetical": True,
        },
    )
    sensitivity_summary = None
    if (
        batter_sensitivity_table is not None
        and bowler_sensitivity_table is not None
        and mapping_summary is not None
    ):
        sensitivity_summary = {
            "batter_top10_overlap_by_variant": _sensitivity_overlap(
                batter_sensitivity_table, "striker_id"
            ),
            "bowler_top10_overlap_by_variant": _sensitivity_overlap(
                bowler_sensitivity_table, "bowler_id"
            ),
            "scoring_mapping_sensitivity": mapping_summary.to_dict(orient="records"),
        }
    if complete:
        write_csv(rankings_dir / "top_10_batters.csv", batter_top10)
        write_csv(rankings_dir / "top_10_bowlers.csv", bowler_top10)
        write_results_pdf(
            output_root / "final_results.pdf",
            batter_top10=batter_top10,
            bowler_top10=bowler_top10,
            run_metadata={
                "run_id": run_id,
                "config_version": config.version,
                "data_fingerprint": fingerprint,
                "random_seed": config.random_seed,
                "analysis_mode": mode,
            },
            pressure_validation=validation_dict,
            sensitivity_summary=sensitivity_summary,
        )
    write_methodology_report(
        report_dir / "methodology_and_results.md",
        status=status,
        blockers=final_blockers,
        pressure_validation=validation_dict,
        batter_top10=batter_top10 if complete else None,
        bowler_top10=bowler_top10 if complete else None,
        config_version=config.version,
        data_fingerprint=fingerprint,
        settings=run_settings,
        scoring_mapping_sensitivity=mapping_summary,
    )
    _write_run_manifest(
        report_dir,
        run_id=run_id,
        config=config,
        data_fingerprint=fingerprint,
        data_manifest=data_manifest,
        status=status,
        started_at=started_at,
        completed_at=datetime.now(UTC).isoformat(),
        full_robustness_requested=full_robustness,
        pressure_validation=validation_dict,
    )
    return {
        "status": status,
        "run_id": run_id,
        "analysis_mode": mode,
        "batter_top10": batter_top10,
        "bowler_top10": bowler_top10,
        "pressure_validation": pressure_validation,
        "output_dir": str(output_root),
    }
