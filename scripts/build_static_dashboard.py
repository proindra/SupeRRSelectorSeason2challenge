from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = PROJECT_ROOT / "artifacts" / "exploratory"
SITE_DATA = PROJECT_ROOT / "site" / "data" / "dashboard.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_completed_run() -> tuple[Path, dict[str, Any]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for run_dir in RUNS_ROOT.iterdir():
        manifest_path = run_dir / "reports" / "run_manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = _read_json(manifest_path)
        if (
            manifest.get("status") == "EXPLORATORY_COMPLETE"
            and manifest.get("analysis_mode") == "ASSUMPTION_BASED_EXPLORATORY"
            and manifest.get("output_label") == "EXPLORATORY"
        ):
            candidates.append((run_dir, manifest))
    if not candidates:
        raise FileNotFoundError(f"No completed exploratory runs found under {RUNS_ROOT}")
    return max(candidates, key=lambda item: str(item[1].get("completed_at", "")))


def _records(path: Path) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    frame = pd.read_csv(path)
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _rankings(run_dir: Path) -> dict[str, Any]:
    rankings_dir = run_dir / "rankings"
    output: dict[str, Any] = {}
    for role in ("batter", "bowler"):
        full = _records(rankings_dir / f"{role}_full_rankings.csv")
        top = _records(rankings_dir / f"top_10_{role}s.csv")
        output[role] = {
            "full": full or [],
            "top10": [
                row
                for row in (top or [])
                if 1 <= int(row.get("rank") or 0) <= 10
            ],
        }
    return output


def _profile_rows(
    states: pd.DataFrame, role: str, excluded_player_ids: set[str]
) -> dict[str, dict[str, Any]]:
    is_batter = role == "batter"
    player_column = "striker_id" if is_batter else "bowler_id"
    high_pressure = states["is_high_pressure"].fillna(False).astype(bool)
    category = states["extras_category"].fillna("").astype(str).str.casefold()
    batter_runs = pd.to_numeric(states["batter_runs"], errors="coerce").fillna(0)

    if is_batter:
        exposure = ~category.eq("wide")
        pressure_runs = batter_runs.where(high_pressure, 0)
        pressure_balls = (exposure & high_pressure).astype(int)
        rate_name = "pressure_strike_rate"
        rate_factor = 100.0
    else:
        charged_extras = category.isin(["wide", "no_ball"])
        extras = (
            pd.to_numeric(states["extras_1"], errors="coerce").fillna(0)
            + pd.to_numeric(states["extras_2"], errors="coerce").fillna(0)
        )
        bowler_runs = batter_runs + extras.where(charged_extras, 0)
        exposure = ~charged_extras
        pressure_runs = bowler_runs.where(high_pressure, 0)
        pressure_balls = (exposure & high_pressure).astype(int)
        rate_name = "pressure_economy"
        rate_factor = 6.0

    player_ids = states[player_column].astype("string")
    included = states[player_column].notna() & ~player_ids.isin(excluded_player_ids)
    detail = states.loc[included, ["match_id", "phase"]].copy()
    detail["player_id"] = states.loc[detail.index, player_column].astype(str)
    detail["pressure_runs"] = pressure_runs.loc[detail.index].astype(float)
    detail["pressure_balls"] = pressure_balls.loc[detail.index].astype(int)
    detail["is_high_pressure"] = high_pressure.loc[detail.index]

    match_rows = (
        detail.groupby(["player_id", "match_id"], as_index=False)
        .agg(
            pressure_runs=("pressure_runs", "sum"),
            pressure_balls=("pressure_balls", "sum"),
        )
        .sort_values(["player_id", "match_id"], kind="stable")
    )
    match_rows[rate_name] = (
        rate_factor
        * match_rows["pressure_runs"]
        / match_rows["pressure_balls"].replace(0, np.nan)
    )
    phase_rows = (
        detail.loc[detail["is_high_pressure"]]
        .groupby(["player_id", "phase"], as_index=False)
        .agg(
            pressure_runs=("pressure_runs", "sum"),
            pressure_balls=("pressure_balls", "sum"),
        )
        .sort_values(["player_id", "phase"], kind="stable")
    )
    phase_rows["rate"] = (
        rate_factor
        * phase_rows["pressure_runs"]
        / phase_rows["pressure_balls"].replace(0, np.nan)
    )

    def grouped_records(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
        if frame.empty:
            return {}
        return {
            str(player_id): json.loads(
                rows.drop(columns="player_id").to_json(orient="records")
            )
            for player_id, rows in frame.groupby("player_id", sort=False)
        }

    match_profiles = grouped_records(match_rows)
    phase_profiles = grouped_records(phase_rows)
    return {
        player_id: {
            "matches": match_profiles.get(player_id, []),
            "phases": phase_profiles.get(player_id, []),
        }
        for player_id in sorted(set(match_profiles) | set(phase_profiles))
    }


def _pressure_distributions(states: pd.DataFrame) -> dict[str, Any]:
    scores = pd.to_numeric(states["pressure_score"], errors="coerce").dropna()
    bins = np.linspace(0, 1, 11)
    counts, edges = np.histogram(scores, bins=bins)
    histogram = [
        {
            "label": f"{edges[index]:.1f}-{edges[index + 1]:.1f}",
            "count": int(count),
        }
        for index, count in enumerate(counts)
    ]
    components: list[dict[str, Any]] = []
    for component in ("R", "W", "D", "S"):
        values = pd.to_numeric(states[component], errors="coerce").dropna()
        if values.empty:
            continue
        components.append(
            {
                "component": component,
                "count": int(values.size),
                "mean": float(values.mean()),
                "median": float(values.median()),
                "q25": float(values.quantile(0.25)),
                "q75": float(values.quantile(0.75)),
            }
        )
    return {"histogram": histogram, "components": components}


def _safe_quality(report_dir: Path) -> dict[str, Any]:
    audit = _read_json(report_dir / "data_audit.json")
    status = _read_json(report_dir / "audit_status.json")
    assumptions = _read_json(report_dir / "exploratory_assumption_status.json")
    return {
        "status": status.get("workflow_status", "EXPLORATORY_ONLY"),
        "findings": audit.get("findings", []),
        "tables": audit.get("tables", {}),
        "schemas": audit.get("schemas", {}),
        "source_evidence": status.get("source_evidence", []),
        "metric_dependency_scope": status.get("metric_dependency_scope", []),
        "confirmed_exclusions": status.get("confirmed_exclusions", {}),
        "assumptions": assumptions.get("selected_assumptions", []),
        "unconfirmed_source_evidence": assumptions.get(
            "unconfirmed_source_evidence", []
        ),
    }


def _has_repeatability_outputs(run_dir: Path) -> bool:
    rankings_dir = run_dir / "rankings"
    return all(
        (rankings_dir / f"{role}_bootstrap_summary.csv").is_file()
        for role in ("batter", "bowler")
    )


def _robustness_source_run(run_dir: Path) -> Path | None:
    if _has_repeatability_outputs(run_dir):
        return run_dir

    candidates: list[tuple[str, Path]] = []
    for candidate in RUNS_ROOT.iterdir():
        manifest_path = candidate / "reports" / "run_manifest.json"
        if candidate == run_dir or not manifest_path.is_file():
            continue
        manifest = _read_json(manifest_path)
        if manifest.get("status") != "EXPLORATORY_COMPLETE":
            continue
        if _has_repeatability_outputs(candidate):
            candidates.append((str(manifest.get("completed_at", "")), candidate))
    return max(candidates, default=(None, None), key=lambda item: item[0])[1]


def _optional_tables(
    run_dir: Path, excluded_player_ids: set[str]
) -> dict[str, list[dict[str, Any]]]:
    names = (
        "batter_sensitivity",
        "bowler_sensitivity",
        "scenario_stability",
        "bootstrap_results",
        "batter_bootstrap_summary",
        "bowler_bootstrap_summary",
        "stability_adjusted_top10",
    )
    rankings_dir = run_dir / "rankings"
    player_columns = {"striker_id", "bowler_id", "player_id", "adjusted_player_id"}
    tables: dict[str, list[dict[str, Any]]] = {}
    for name in names:
        path = rankings_dir / f"{name}.csv"
        if not path.is_file():
            continue
        frame = pd.read_csv(path)
        excluded_rows = pd.Series(False, index=frame.index)
        for column in player_columns.intersection(frame.columns):
            player_ids = frame[column].astype("string").str.replace(r"\.0$", "", regex=True)
            excluded_rows |= player_ids.isin(excluded_player_ids)
        records = _records(path) if not excluded_rows.any() else None
        if records is None:
            frame = frame.loc[~excluded_rows]
            records = json.loads(frame.to_json(orient="records", date_format="iso"))
        tables[name] = records
    return tables


def build_payload(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    report_dir = run_dir / "reports"
    states = pd.read_parquet(run_dir / "processed" / "pressure_states.parquet")
    pressure = _read_json(report_dir / "pressure_validation.json")
    config = yaml.safe_load(
        (PROJECT_ROOT / "config" / "default.yaml").read_text(encoding="utf-8")
    )
    excluded_player_ids = set(manifest.get("ranking_exclusions", {}).get("player_ids", []))
    robustness_run = _robustness_source_run(run_dir)
    robustness = (
        _optional_tables(robustness_run, excluded_player_ids) if robustness_run else {}
    )
    return {
        "manifest": {
            "run_id": manifest.get("run_id", run_dir.name),
            "status": manifest.get("status"),
            "analysis_mode": manifest.get("analysis_mode"),
            "output_label": manifest.get("output_label"),
            "completed_at": manifest.get("completed_at"),
            "config_version": manifest.get("config_version"),
            "ranking_exclusions": {
                "basis": manifest.get("ranking_exclusions", {}).get("basis"),
                "player_count": len(
                    manifest.get("ranking_exclusions", {}).get("player_ids", [])
                ),
            },
            "robustness_source_run_id": (
                robustness_run.name if robustness_run is not None else None
            ),
            "run_artifacts_removed_after_publication": False,
            "pressure_validation": {
                "status": pressure.get("status"),
                "passed": pressure.get("passed"),
            },
        },
        "config": {
            "pressure": config.get("pressure", {}),
            "samples": config.get("samples", {}),
            "reliability": config.get("reliability", {}),
        },
        "coverage": pressure.get("summary", {}),
        "pressure_validation": {
            "outcome_gradient": pressure.get("outcome_gradient", []),
            "ablations": pressure.get("ablations", []),
            "correlations": pressure.get("correlations", {}),
            "diagnostics": pressure.get("diagnostics", []),
        },
        "pressure_distributions": _pressure_distributions(states),
        "rankings": _rankings(run_dir),
        "profiles": {
            "batter": _profile_rows(states, "batter", excluded_player_ids),
            "bowler": _profile_rows(states, "bowler", excluded_player_ids),
        },
        "quality": _safe_quality(report_dir),
        "robustness": robustness,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the static dashboard data from saved exploratory results."
    )
    parser.add_argument(
        "--run-id",
        help="Use a specific saved run; defaults to the latest completed exploratory run.",
    )
    args = parser.parse_args()
    if args.run_id:
        run_dir = RUNS_ROOT / args.run_id
        manifest_path = run_dir / "reports" / "run_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"No run manifest found for run {args.run_id}")
        manifest = _read_json(manifest_path)
    else:
        run_dir, manifest = _latest_completed_run()
    if manifest.get("status") != "EXPLORATORY_COMPLETE":
        raise ValueError(f"Run {run_dir.name} is not marked EXPLORATORY_COMPLETE")
    payload = build_payload(run_dir, manifest)
    SITE_DATA.parent.mkdir(parents=True, exist_ok=True)
    SITE_DATA.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built {SITE_DATA.relative_to(PROJECT_ROOT)} from saved run {run_dir.name}")


if __name__ == "__main__":
    main()
