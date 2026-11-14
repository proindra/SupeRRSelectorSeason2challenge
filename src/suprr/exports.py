from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")


def _markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(column) for column in frame.columns]
    rows = frame.astype(str).values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def write_methodology_report(
    path: Path,
    *,
    status: str,
    blockers: list[str],
    pressure_validation: dict[str, Any] | None = None,
    batter_top10: pd.DataFrame | None = None,
    bowler_top10: pd.DataFrame | None = None,
    config_version: str,
    data_fingerprint: str,
    settings: dict[str, Any] | None = None,
    scoring_mapping_sensitivity: pd.DataFrame | None = None,
) -> None:
    lines = [
        "# Methodology and Results",
        "",
        f"**Run status:** {status}",
        f"**Configuration:** {config_version}",
        f"**Data fingerprint:** `{data_fingerprint}`",
        "",
        "## Analytical policy",
        "",
        "Chase pressure is calculated strictly before each delivery from runs needed, "
        "legal balls remaining, wickets in hand, required run rate, chase difficulty, "
        "and innings stage. The primary high-pressure threshold is P >= 0.60.",
        "",
        "Batter rates use balls faced (wides excluded); bowler rates use legal balls "
        "(wides and no-balls excluded). Rate metrics use exposure-based shrinkage "
        "toward pooled IPL or T20I baselines with k=100. Raw runs and wickets and "
        "regularised bowling average/strike rate are not shrunk.",
        "",
        "Batter score weights: pressure strike rate +0.25, pressure runs +0.15, "
        "strike-rate change +0.15, boundary rate +0.10, consistency +0.10, "
        "dot-ball rate -0.10, dismissal rate -0.15.",
        "",
        "Bowler score weights: pressure economy -0.25, dot-ball rate +0.20, "
        "pressure wickets +0.15, boundary conceded rate -0.15, regularised "
        "average -0.05, regularised strike rate -0.05, economy improvement +0.10, "
        "consistency +0.05.",
        "",
        "Each batter pressure innings and bowler pressure spell requires at least "
        "6 pressure balls. Combined player exposure requires at least 60 batter "
        "pressure balls and 8 innings, or 60 legal bowler pressure balls and 8 spells. "
        "Competition-specific z-scores are exposure-weighted across IPL and T20I.",
        "",
        "## Sensitivity and robustness",
        "",
        "Volume and wicket/regularisation ablations are exported when ranking gates pass. "
        "Scenario stability, match-level bootstrap intervals, and split-half checks "
        "are produced only by a full robustness run. Scoring-mapping sensitivity scenarios "
        "are hypothetical alternatives and are not used in the baseline ranking.",
        "",
        "## Gate status",
        "",
    ]
    if blockers:
        lines.extend(["Final rankings are blocked because:", ""])
        lines.extend(f"- {item}" for item in blockers)
        lines.extend(
            [
                "",
                "No Top 10 rankings or final-results PDF were produced. Resolve the listed "
                "source-semantic and validation issues, then rerun the pipeline.",
            ]
        )
    elif pressure_validation:
        lines.extend(
            [
                f"Pressure-model validation: **{pressure_validation.get('status', 'UNKNOWN')}**",
                "",
            ]
        )
    if pressure_validation:
        lines.extend(["## Pressure-model validation", ""])
        lines.append(f"```json\n{json.dumps(pressure_validation, indent=2, default=str)}\n```")
        lines.append("")
    if settings:
        if settings.get("output_label") == "EXPLORATORY":
            lines.extend(
                [
                    "## EXPLORATORY assumptions",
                    "",
                    "This run uses configured assumptions and is not source-confirmed. "
                    "Do not present it as validated.",
                    "",
                ]
            )
        lines.extend(
            [
                "## Reproducibility settings",
                "",
                f"```json\n{json.dumps(settings, indent=2, default=str)}\n```",
                "",
            ]
        )
    if scoring_mapping_sensitivity is not None:
        lines.extend(
            [
                "## Exploratory scoring-mapping sensitivity",
                "",
                "The configured baseline assumptions are not source-confirmed. Alternative "
                "mappings are hypothetical sensitivity tests only and are not evidence of the "
                "correct source interpretation.",
                "",
            ]
        )
        if not scoring_mapping_sensitivity.empty:
            lines.extend([_markdown_table(scoring_mapping_sensitivity), ""])
    for title, table in [("Top 10 batters", batter_top10), ("Top 10 bowlers", bowler_top10)]:
        if table is not None:
            lines.extend(
                [
                    f"## {title}",
                    "",
                    _markdown_table(table),
                    "",
                ]
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_results_pdf(
    path: Path,
    *,
    batter_top10: pd.DataFrame,
    bowler_top10: pd.DataFrame,
    run_metadata: dict[str, Any],
    pressure_validation: dict[str, Any],
    sensitivity_summary: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(
            (
                "EXPLORATORY — SupeRR Selector Season 2 Pressure Analytics"
                if run_metadata.get("analysis_mode") == "ASSUMPTION_BASED_EXPLORATORY"
                else "SupeRR Selector Season 2 — Pressure Analytics"
            ),
            styles["Title"],
        ),
        Spacer(1, 0.15 * inch),
        Paragraph(
            f"Generated {datetime.now(UTC).isoformat()} | "
            f"Run {run_metadata['run_id']} | "
            f"Configuration {run_metadata['config_version']}",
            styles["BodyText"],
        ),
        Paragraph(
            f"Data fingerprint: {run_metadata.get('data_fingerprint', 'not recorded')} | "
            f"Random seed: {run_metadata.get('random_seed', 'not recorded')}",
            styles["BodyText"],
        ),
        Paragraph(
            "EXPLORATORY only: scoring assumptions are not confirmed by an authoritative "
            "source codebook.",
            styles["BodyText"],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Method and sample rules", styles["Heading2"]),
        Paragraph(
            "Pressure states are strictly pre-delivery. Batter balls faced exclude wides; "
            "bowler legal balls exclude wides and no-balls. Batter innings and bowler "
            "match spells require at least 6 pressure balls. Combined player eligibility "
            "requires 60 exposure balls and 8 innings or spells. Rate metrics use pooled "
            "competition-group baselines and exposure-based shrinkage (k=100); regularised "
            "bowling average and strike rate are not shrunk again.",
            styles["BodyText"],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Pressure-model validation", styles["Heading2"]),
        Paragraph(
            f"Status: {pressure_validation['status']}. "
            f"Full model AUC: {pressure_validation['summary'].get('full_model_auc')}; "
            f"best ablation AUC: {pressure_validation['summary'].get('best_ablation_auc')}.",
            styles["BodyText"],
        ),
    ]
    for title, frame in [("Top 10 batters", batter_top10), ("Top 10 bowlers", bowler_top10)]:
        story.extend([Spacer(1, 0.2 * inch), Paragraph(title, styles["Heading2"])])
        preferred = (
            [
                "rank",
                "player_name",
                "composite_score",
                "pressure_runs",
                "pressure_balls",
                "pressure_innings",
                "pressure_strike_rate_shrunk",
                "consistency",
            ]
            if "pressure_runs" in frame
            else [
                "rank",
                "player_name",
                "composite_score",
                "pressure_wickets",
                "legal_pressure_balls",
                "pressure_economy_shrunk",
                "regularised_bowling_average",
                "consistency",
            ]
        )
        selected = frame[[column for column in preferred if column in frame]].head(10)
        data = [list(selected.columns)] + selected.astype(str).values.tolist()
        table = Table(data, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#171B2C")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7DCE5")),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#F3F5F9")],
                    ),
                ]
            )
        )
        story.append(table)
    if sensitivity_summary:
        story.extend(
            [
                Spacer(1, 0.2 * inch),
                Paragraph("Sensitivity and stability", styles["Heading2"]),
                Paragraph(json.dumps(sensitivity_summary, default=str), styles["BodyText"]),
            ]
        )
    story.extend(
        [
            Spacer(1, 0.2 * inch),
            Paragraph(
                "Rates are exposure-adjusted as documented in the project methodology. "
                "See methodology_and_results.md and the run manifest for full data "
                "fingerprint, assumptions, metric definitions, and robustness evidence.",
                styles["BodyText"],
            ),
        ]
    )
    document.build(story)
