from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Protocol, cast

import pandas as pd


class DashboardBuilder(Protocol):
    RUNS_ROOT: Path

    def _optional_tables(
        self, run_dir: Path, excluded_player_ids: set[str]
    ) -> dict[str, list[dict[str, Any]]]: ...

    def _robustness_source_run(self, run_dir: Path) -> Path | None: ...


def _dashboard_builder() -> DashboardBuilder:
    path = Path(__file__).parents[1] / "scripts" / "build_static_dashboard.py"
    spec = importlib.util.spec_from_file_location("dashboard_builder_test", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load dashboard builder from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(DashboardBuilder, module)


def test_optional_tables_filter_excluded_player_ids(tmp_path):
    rankings = tmp_path / "rankings"
    rankings.mkdir()
    pd.DataFrame(
        [
            {"striker_id": 123.0, "top_10_frequency": 0.9},
            {"striker_id": 456.0, "top_10_frequency": 0.5},
        ]
    ).to_csv(rankings / "batter_bootstrap_summary.csv", index=False)

    tables = _dashboard_builder()._optional_tables(tmp_path, {"123"})

    assert [int(row["striker_id"]) for row in tables["batter_bootstrap_summary"]] == [456]


def test_robustness_source_uses_latest_completed_run_with_summaries(tmp_path, monkeypatch):
    current = tmp_path / "current"
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    for run_dir, completed_at in ((older, "2026-01-01"), (newer, "2026-02-01")):
        reports = run_dir / "reports"
        rankings = run_dir / "rankings"
        reports.mkdir(parents=True)
        rankings.mkdir()
        (reports / "run_manifest.json").write_text(
            json.dumps({"status": "EXPLORATORY_COMPLETE", "completed_at": completed_at}),
            encoding="utf-8",
        )
        for role in ("batter", "bowler"):
            (rankings / f"{role}_bootstrap_summary.csv").write_text(
                "player_id,top_10_frequency\n1,0.5\n",
                encoding="utf-8",
            )
    incomplete_reports = tmp_path / "incomplete" / "reports"
    incomplete_reports.mkdir(parents=True)
    (incomplete_reports / "run_manifest.json").write_text(
        json.dumps({"status": "INCOMPLETE", "completed_at": "2026-03-01"}),
        encoding="utf-8",
    )
    dashboard = _dashboard_builder()
    monkeypatch.setattr(dashboard, "RUNS_ROOT", tmp_path)

    assert dashboard._robustness_source_run(current) == newer
