from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from suprr.exports import write_results_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = PROJECT_ROOT / "artifacts" / "exploratory"
BRIEF_PATH = PROJECT_ROOT / "artifacts" / "briefs" / "rr_ipl_2027_pressure_brief.pdf"
SITE_REPORTS = PROJECT_ROOT / "site" / "reports"


def _paragraph(value: object, style: Any) -> Paragraph:
    return Paragraph(escape(str(value)), style)


def _integer_text(value: object) -> str:
    return str(int(str(value)))


def _decimal_text(value: object, places: int) -> str:
    return f"{float(str(value)):.{places}f}"


def _percent_text(value: object) -> str:
    return f"{float(str(value)):.1%}"


def _ranking_table(frame: pd.DataFrame, role: str, styles: Any) -> Table:
    columns: list[tuple[str, str, Callable[[object], str]]]
    if role == "batter":
        columns = [
            ("rank", "Rank", _integer_text),
            ("player_name", "Player", lambda value: str(value)),
            ("comparison_context", "Scope", lambda value: str(value)),
            ("pressure_runs", "Runs", _integer_text),
            ("pressure_balls", "Balls", _integer_text),
            ("pressure_strike_rate_shrunk", "Shrunk SR", lambda value: _decimal_text(value, 1)),
            ("consistency", "Consistency", _percent_text),
        ]
        widths = [30, 104, 78, 48, 48, 82, 66]
    else:
        columns = [
            ("rank", "Rank", _integer_text),
            ("player_name", "Player", lambda value: str(value)),
            ("comparison_context", "Scope", lambda value: str(value)),
            ("pressure_wickets", "Wickets", _integer_text),
            ("legal_pressure_balls", "Legal balls", _integer_text),
            ("pressure_economy_shrunk", "Shrunk econ.", lambda value: _decimal_text(value, 2)),
            ("consistency", "Consistency", _percent_text),
        ]
        widths = [30, 104, 78, 48, 58, 82, 66]

    header_style = styles["TableHeader"]
    cell_style = styles["TableCell"]
    data = [[_paragraph(label, header_style) for _, label, _ in columns]]
    data.extend(
        [
            _paragraph(formatter(row[column]), cell_style)
            for column, _, formatter in columns
        ]
        for row in frame.to_dict(orient="records")
    )
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#171B2C")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7DCE5")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F5F9")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def build_brief(run_id: str) -> Path:
    run_dir = RUNS_ROOT / run_id
    manifest_path = run_dir / "reports" / "run_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Run manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "EXPLORATORY_COMPLETE":
        raise ValueError(f"Run {run_id} is not marked EXPLORATORY_COMPLETE.")

    rankings_dir = run_dir / "rankings"
    batter_top10 = pd.read_csv(rankings_dir / "top_10_batters.csv").head(10)
    bowler_top10 = pd.read_csv(rankings_dir / "top_10_bowlers.csv").head(10)
    pressure = json.loads(
        (run_dir / "reports" / "pressure_validation.json").read_text(encoding="utf-8")
    )
    excluded_count = len(manifest.get("ranking_exclusions", {}).get("player_ids", []))
    match_count = pressure.get("summary", {}).get("distinct_matches", "not recorded")

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontSize=7,
            leading=8,
        )
    )

    story = [
        Paragraph("RR IPL 2027 Pressure Brief", styles["Title"]),
        Paragraph(
            "Updated historical pressure-performance rankings for scouting context",
            styles["Heading2"],
        ),
        Spacer(1, 0.12 * inch),
        Paragraph(
            f"Run {run_id} · {match_count} resolved-winner match IDs · "
            f"{excluded_count} Pakistan/Pakistan A squad-mapped player IDs excluded "
            "from ranking candidates.",
            styles["BodyText"],
        ),
        Spacer(1, 0.1 * inch),
        Paragraph(
            "Eligibility note: the source has no nationality field, so Pakistan or Pakistan A "
            "squad membership is used as a proxy for IPL ineligibility. Source and match records "
            "are retained. The results are exploratory and are not an official Rajasthan Royals "
            "recommendation or endorsement.",
            styles["BodyText"],
        ),
        Spacer(1, 0.2 * inch),
        _ranking_table(batter_top10, "batter", styles),
        Spacer(1, 0.18 * inch),
        _ranking_table(bowler_top10, "bowler", styles),
        Spacer(1, 0.2 * inch),
        Paragraph(
            "Ranking methods use high-pressure T20 chase performance, minimum exposure rules, "
            "competition-group standardization, and exposure-based shrinkage. Metrics and "
            "scoring mappings remain exploratory assumptions; see the project methodology and "
            "run manifest for details.",
            styles["BodyText"],
        ),
    ]
    BRIEF_PATH.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(BRIEF_PATH),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title="RR IPL 2027 Pressure Brief",
    )
    document.build(story)

    results_pdf = run_dir / "final_results.pdf"
    write_results_pdf(
        results_pdf,
        batter_top10=batter_top10,
        bowler_top10=bowler_top10,
        run_metadata={
            "run_id": manifest["run_id"],
            "config_version": manifest["config_version"],
            "data_fingerprint": manifest["data_fingerprint"],
            "random_seed": manifest["random_seed"],
            "analysis_mode": manifest["analysis_mode"],
        },
        pressure_validation=pressure,
        ranking_exclusion_note=(
            f"{excluded_count} player IDs mapped to Pakistan or Pakistan A squads were "
            "excluded from ranking candidates. The source has no nationality field; squad "
            "membership is used as the available proxy."
        ),
    )
    SITE_REPORTS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BRIEF_PATH, SITE_REPORTS / BRIEF_PATH.name)
    shutil.copy2(results_pdf, SITE_REPORTS / "final_results.pdf")
    return BRIEF_PATH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and publish the brief and results PDFs for a saved run."
    )
    parser.add_argument("--run-id", required=True, help="Completed exploratory run ID.")
    args = parser.parse_args()
    output = build_brief(args.run_id)
    print(f"Built {output.relative_to(PROJECT_ROOT)} and copied both PDFs to site/reports.")


if __name__ == "__main__":
    main()
