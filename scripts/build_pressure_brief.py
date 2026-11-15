from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Sequence
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from suprr.exports import write_results_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = PROJECT_ROOT / "artifacts" / "exploratory"
BRIEF_PATH = PROJECT_ROOT / "artifacts" / "briefs" / "rr_ipl_2027_pressure_brief.pdf"
SITE_REPORTS = PROJECT_ROOT / "site" / "reports"
NAVY = colors.HexColor("#171B2C")
PINK = colors.HexColor("#E91E8C")
PALE = colors.HexColor("#F3F5F9")
LINE = colors.HexColor("#D7DCE5")


def _table(rows: Sequence[Sequence[object]], widths: list[float], styles: Any) -> Table:
    data = [
        [
            Paragraph(
                escape(str(value)).replace("\n", "<br/>"),
                styles["TableHeader"] if row_index == 0 else styles["TableCell"],
            )
            for value in row
        ]
        for row_index, row in enumerate(rows)
    ]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _key(value: object) -> str:
    return str(int(float(str(value))))


def _profile_rows(
    frame: pd.DataFrame,
    role: str,
    robustness: dict[str, Any],
) -> list[list[object]]:
    batter = role == "batter"
    id_column = "striker_id" if batter else "bowler_id"
    bootstrap_rows = robustness.get(f"{role}_bootstrap_summary", [])
    scenario_rows = robustness.get("scenario_stability", [])
    bootstrap = {
        _key(row[id_column]): row for row in bootstrap_rows if row.get(id_column) is not None
    }
    scenarios = {
        _key(row[id_column]): row
        for row in scenario_rows
        if row.get("role") == role and row.get(id_column) is not None
    }
    rows: list[list[object]] = [
        [
            "Rank",
            "Player / scope",
            "Pressure exposure",
            "Shrunk rate",
            "Consistency",
            "Repeatability",
            "Role-fit lens",
        ]
    ]
    for player in frame.to_dict(orient="records"):
        player_id = _key(player[id_column])
        repeat = bootstrap.get(player_id, {})
        scenario = scenarios.get(player_id, {})
        frequency = repeat.get("top_10_frequency")
        valid_replicates = repeat.get("valid_replicates")
        if frequency is None or valid_replicates is None:
            bootstrap_label = "Bootstrap: n/a"
        else:
            numerator = round(float(frequency) * int(valid_replicates))
            bootstrap_label = (
                f"Bootstrap: {float(frequency):.1%}\n({numerator}/{int(valid_replicates)})"
            )
        scenario_count = scenario.get("top_10_scenarios")
        scenario_total = scenario.get("valid_scenarios")
        scenario_label = (
            f"Scenarios: {int(scenario_count)}/{int(scenario_total)}"
            if scenario_count is not None and scenario_total is not None
            else "Scenarios: n/a"
        )
        scope = str(player.get("comparison_context", "scope unavailable"))
        if scope == "T20I":
            role_fit = "T20I-only; review format transfer."
        elif scope == "IPL":
            role_fit = "IPL-only evidence; verify current role."
        else:
            role_fit = "Cross-context; compare with squad need."
        if batter:
            exposure = (
                f"{int(player['pressure_runs'])} runs\n"
                f"{int(player['pressure_balls'])} balls\n"
                f"{int(player['pressure_innings'])} innings"
            )
            rate = f"{float(player['pressure_strike_rate_shrunk']):.1f} SR"
        else:
            exposure = (
                f"{int(player['pressure_wickets'])} wickets\n"
                f"{int(player['legal_pressure_balls'])} legal balls\n"
                f"{int(player['pressure_spells'])} spells"
            )
            rate = f"{float(player['pressure_economy_shrunk']):.2f} econ"
        rows.append(
            [
                int(player["rank"]),
                f"{player.get('player_name', 'Unknown')}\n{scope}",
                exposure,
                rate,
                f"{float(player['consistency']):.1%}",
                f"{bootstrap_label}\n{scenario_label}",
                role_fit,
            ]
        )
    return rows


def _page_chrome(canvas: Canvas, document: SimpleDocTemplate) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(
        document.leftMargin, height - 23, "SUPERR SELECTOR / RR IPL 2027 PRESSURE BRIEF"
    )
    canvas.setFillColor(colors.HexColor("#65718A"))
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(
        width - document.rightMargin, height - 23, "METHODOLOGY & PLAYER PROFILES"
    )
    canvas.setStrokeColor(LINE)
    canvas.line(document.leftMargin, 31, width - document.rightMargin, 31)
    canvas.drawString(
        document.leftMargin,
        19,
        "Historical pressure performance | Role-fit context for RR scouting",
    )
    canvas.drawRightString(width - document.rightMargin, 19, str(document.page))
    canvas.restoreState()


def _heading(title: str, description: str, styles: Any) -> list[object]:
    return [
        Paragraph(title, styles["SectionHeading"]),
        Spacer(1, 0.06 * inch),
        Paragraph(description, styles["BodyText"]),
        Spacer(1, 0.12 * inch),
    ]


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
    dashboard = json.loads(
        (PROJECT_ROOT / "site" / "data" / "dashboard.json").read_text(encoding="utf-8")
    )
    if dashboard.get("manifest", {}).get("run_id") != run_id:
        raise ValueError("Build the dashboard snapshot for this run before building its brief.")
    robustness = dashboard.get("robustness", {})
    robustness_source_run = dashboard.get("manifest", {}).get("robustness_source_run_id")
    summary = pressure.get("summary", {})
    match_count = summary.get("distinct_matches", "not recorded")
    inventory = {row["table"]: row for row in manifest.get("data_manifest", [])}
    source_matches = int(inventory.get("matches", {}).get("rows", 0))
    states = pd.read_parquet(
        run_dir / "processed" / "pressure_states.parquet",
        columns=["match_id", "pressure_score"],
    )
    state_match_count = int(states.loc[states["pressure_score"].notna(), "match_id"].nunique())
    no_state_matches = max(source_matches - state_match_count, 0)
    unresolved_match_count = max(state_match_count - int(match_count), 0)
    batter_leader = batter_top10.iloc[0]["player_name"]
    bowler_leader = bowler_top10.iloc[0]["player_name"]
    batter_ipl = batter_top10.loc[batter_top10["comparison_context"].eq("IPL")].head(1)
    bowler_ipl = bowler_top10.loc[bowler_top10["comparison_context"].eq("IPL")].head(1)
    batter_ipl_name = (
        str(batter_ipl.iloc[0]["player_name"]) if not batter_ipl.empty else "Unavailable"
    )
    bowler_ipl_name = (
        str(bowler_ipl.iloc[0]["player_name"]) if not bowler_ipl.empty else "Unavailable"
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=NAVY,
            spaceAfter=2,
        )
    )
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
            fontSize=6.5,
            leading=8,
        )
    )
    styles.add(
        ParagraphStyle(
            "Kicker",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=PINK,
        )
    )
    styles.add(
        ParagraphStyle(
            "Lead",
            parent=styles["BodyText"],
            fontSize=11,
            leading=15,
            textColor=NAVY,
        )
    )

    available_width = A4[0] - 0.9 * inch
    weights_batter = [
        ["Metric", "Weight", "Direction"],
        ["Shrunk pressure strike rate", "+0.25", "Higher"],
        ["Pressure runs", "+0.15", "Higher volume"],
        ["Shrunk strike-rate change", "+0.15", "Higher"],
        ["Shrunk boundary rate", "+0.10", "Higher"],
        ["Consistency", "+0.10", "Higher"],
        ["Shrunk dot-ball rate", "-0.10", "Lower"],
        ["Shrunk dismissal rate", "-0.15", "Lower"],
    ]
    weights_bowler = [
        ["Metric", "Weight", "Direction"],
        ["Shrunk pressure economy", "-0.25", "Lower"],
        ["Shrunk legal dot-ball rate", "+0.20", "Higher"],
        ["Pressure wickets", "+0.15", "Higher volume"],
        ["Shrunk boundary-conceded rate", "-0.15", "Lower"],
        ["Regularised bowling average", "-0.05", "Lower"],
        ["Regularised bowling strike rate", "-0.05", "Lower"],
        ["Shrunk economy improvement", "+0.10", "Higher"],
        ["Consistency", "+0.05", "Higher"],
    ]
    inventory_rows = [["Source CSV", "Rows in saved-run manifest"]]
    for table in (
        "deliveries",
        "player_team_mapping",
        "competitions",
        "matches",
        "playing_eleven",
        "teams",
    ):
        row = inventory.get(table, {})
        inventory_rows.append([row.get("filename", table), f"{int(row.get('rows', 0)):,}"])
    coverage_rows = [
        ["Stage", "Count", "Reading"],
        [
            "Source matches.csv",
            f"{source_matches:,} rows / {source_matches:,} unique IDs",
            "Source table coverage.",
        ],
        [
            "IDs with pressure states",
            f"{state_match_count:,}",
            "Usable reconstructed states before winner filtering.",
        ],
        [
            "Winner filtering",
            f"{unresolved_match_count:,} matches removed",
            "Undetermined winners excluded from ranking sample.",
        ],
        [
            "Ranking sample",
            f"{int(match_count):,} match IDs",
            "Resolved-winner matches in the saved ranking run.",
        ],
        [
            "No usable states",
            f"{no_state_matches:,} source IDs",
            "No usable non-null pressure-state rows.",
        ],
    ]
    key_findings = [
        ["Area", "Saved-run readout"],
        [
            "Batting leader",
            f"{batter_leader} leads the filtered batter composite; "
            f"{batter_ipl_name} is the highest-ranked IPL-only batter in the Top 10.",
        ],
        [
            "Bowling leader",
            f"{bowler_leader} leads the filtered bowler composite; "
            f"{bowler_ipl_name} is the highest-ranked IPL-only bowler in the Top 10.",
        ],
        [
            "IPL-only repeat signal",
            f"{batter_ipl_name} and {bowler_ipl_name} have saved repeat signals "
            f"sourced from run {robustness_source_run or 'unavailable'}.",
        ],
    ]
    story: list[object] = [
        Paragraph("RAJASTHAN ROYALS | IPL 2027 SCOUTING", styles["Kicker"]),
        Spacer(1, 0.18 * inch),
        Paragraph("Pressure performance<br/>and role-fit signals", styles["Title"]),
        Paragraph(
            "A methods-led historical review of the saved batting and bowling rankings, "
            "with 10 profiles in each discipline.",
            styles["Lead"],
        ),
        Spacer(1, 0.16 * inch),
        Paragraph(
            "Scouting lens: use pressure performance as one evidence stream alongside confirmed "
            "squad roles, auction availability, current form, fitness, and price. These notes are "
            "conditional role-fit prompts, not recommendations.",
            styles["BodyText"],
        ),
        Spacer(1, 0.2 * inch),
        _table(
            [
                ["Profiles", "Ranking sample", "Bootstrap", "Scenarios"],
                [
                    "10 batters + 10 bowlers",
                    f"{int(match_count):,} matches",
                    "500 resamples",
                    "16 variants",
                ],
            ],
            [available_width / 4] * 4,
            styles,
        ),
        Spacer(1, 0.22 * inch),
        Paragraph("Key findings", styles["SectionHeading"]),
        Spacer(1, 0.08 * inch),
        _table(key_findings, [1.35 * inch, available_width - 1.35 * inch], styles),
        Spacer(1, 0.2 * inch),
        Paragraph(
            f"Saved analysis run {run_id} | completed {manifest.get('completed_at', '')[:10]}",
            styles["BodyText"],
        ),
        Spacer(1, 0.1 * inch),
        Paragraph(
            f"Eligibility filter: {excluded_count} player IDs mapped to Pakistan or Pakistan A "
            "squads are excluded from ranking candidates. The source has no nationality field, "
            "so squad membership is the available proxy; source and match records are retained.",
            styles["BodyText"],
        ),
        Paragraph(
            "EXPLORATORY only. This brief is not affiliated with or endorsed by Rajasthan Royals.",
            styles["BodyText"],
        ),
        PageBreak(),
    ]

    story.extend(
        _heading(
            "01 | Data scope and sample construction",
            "The workflow reads the supplied delivery-level file and match metadata, reconstructs "
            "the chase state before each second-innings delivery, then calculates player metrics "
            "from eligible high-pressure situations.",
            styles,
        )
    )
    story.extend(
        [
            Paragraph("Input inventory", styles["Heading3"]),
            _table(inventory_rows, [3.7 * inch, available_width - 3.7 * inch], styles),
            Spacer(1, 0.16 * inch),
            Paragraph("Match coverage", styles["Heading3"]),
            _table(
                coverage_rows,
                [1.25 * inch, 1.7 * inch, available_width - 2.95 * inch],
                styles,
            ),
            Spacer(1, 0.14 * inch),
            Paragraph("Selection rules", styles["Heading3"]),
            Paragraph(
                "Competition: IPL and T20I groups are ranked; Other is omitted. IPL is classified "
                "from competition-name tokens; T20I from the format field. The composite "
                "leaderboard standardizes within those groups before combining player evidence.",
                styles["BodyText"],
            ),
            Paragraph(
                "Chase reconstruction: second innings; target = first-innings total + 1; "
                "scheduled length = 120 legal balls. Revised-target matches are excluded because "
                "effective target timing is unavailable. Confirmed Super Over innings "
                "are excluded.",
                styles["BodyText"],
            ),
            Paragraph(
                f"The {excluded_count}-player Pakistan/Pakistan A exclusion applies to ranking "
                "candidates and dashboard profiles only. It does not delete or alter source rows.",
                styles["BodyText"],
            ),
            Paragraph(
                "Coverage note: unresolved_winner_rows counts delivery-state rows from the "
                "matches with undetermined winner status, not match IDs.",
                styles["BodyText"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        _heading(
            "02 | Pressure-state calculation",
            "Pressure is measured immediately before the current delivery. Current-ball runs, "
            "wickets, and legal-ball status affect the next delivery's state.",
            styles,
        )
    )
    story.extend(
        [
            Paragraph(
                "<b>P = 0.35R + 0.25W + 0.25D + 0.15S</b>",
                styles["Title"],
            ),
            Paragraph(
                "Each component is clipped to [0, 1]; component weights sum to 1.00. The score is "
                "a reproducible project index, not a source-confirmed scoring definition.",
                styles["BodyText"],
            ),
            Spacer(1, 0.12 * inch),
            _table(
                [
                    ["Component", "Operational definition", "Weight"],
                    [
                        "R | rate demand",
                        "RRR = 6 x runs needed / legal balls remaining; R = clip(RRR / 18, 0, 1).",
                        "0.35",
                    ],
                    [
                        "W | wickets lost",
                        "W = clip(wickets lost / 10, 0, 1); wickets in hand = 10 - wickets lost.",
                        "0.25",
                    ],
                    [
                        "D | chase difficulty",
                        "D = clip(runs needed / [balls remaining x 2 runs/ball x "
                        "wickets in hand / 10], 0, 1).",
                        "0.25",
                    ],
                    [
                        "S | innings stage",
                        "S = clip(legal balls already bowled / 120, 0, 1).",
                        "0.15",
                    ],
                ],
                [1.2 * inch, available_width - 1.65 * inch, 0.45 * inch],
                styles,
            ),
            Spacer(1, 0.18 * inch),
            Paragraph("Worked example", styles["Heading3"]),
            Paragraph(
                "Illustration: 48 runs needed, 24 legal balls remaining, 6 wickets lost, and 96 "
                "legal balls bowled. Wickets in hand = 4; RRR = 12.0; R = 12/18 = 0.667; "
                "W = 0.60; D = 48/(24 x 2 x 4/10) = 1.00 after clipping; S = 96/120 = 0.80.",
                styles["BodyText"],
            ),
            Paragraph(
                "P = (0.35 x 0.667) + (0.25 x 0.60) + (0.25 x 1.00) + (0.15 x 0.80) = 0.753",
                styles["BodyText"],
            ),
            Spacer(1, 0.12 * inch),
            Paragraph(
                "High pressure is P >= 0.60; the clutch band is P >= 0.80. Rankings use the high-"
                "pressure cut. The clutch cut is descriptive. States are live while runs are "
                "needed, balls remain, and wickets are in hand.",
                styles["BodyText"],
            ),
            Paragraph(
                "For revised-target matches, effective target timing is unavailable, so those "
                "matches are excluded from reconstructed chase analysis.",
                styles["BodyText"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        _heading(
            "03 | Player metrics and eligibility",
            "Pressure metrics use deliveries with P >= 0.60. The batter's normal comparison is "
            "lower-pressure balls during a live second-innings chase.",
            styles,
        )
    )
    story.extend(
        [
            Paragraph("Batter measures", styles["Heading3"]),
            _table(
                [
                    ["Measure", "Definition"],
                    [
                        "Pressure strike rate",
                        "100 x pressure batter runs / pressure balls faced. "
                        "Wides are excluded from balls faced.",
                    ],
                    [
                        "Strike-rate change",
                        "Shrunk pressure strike rate minus shrunk lower-pressure chase "
                        "strike rate.",
                    ],
                    [
                        "Boundary / dot / dismissal rate",
                        "Boundaries, zero-batter-run balls, and included striker "
                        "dismissals per pressure ball.",
                    ],
                    [
                        "Consistency",
                        "Share of qualifying pressure balls in innings whose pressure "
                        "strike rate meets or exceeds the phase-mix-weighted "
                        "competition baseline.",
                    ],
                ],
                [1.75 * inch, available_width - 1.75 * inch],
                styles,
            ),
            Spacer(1, 0.16 * inch),
            Paragraph("Bowler measures", styles["Heading3"]),
            _table(
                [
                    ["Measure", "Definition"],
                    [
                        "Pressure economy",
                        "6 x pressure runs charged to bowler / legal pressure balls; "
                        "lower is favorable.",
                    ],
                    [
                        "Economy improvement",
                        "Lower-pressure chase economy minus pressure economy; positive "
                        "values indicate lower economy under pressure.",
                    ],
                    [
                        "Dot / boundary / wickets",
                        "Legal zero-total-run balls, recorded boundaries, and wickets "
                        "meeting the configured credit list per legal pressure ball.",
                    ],
                    [
                        "Regularised average / SR",
                        "Pressure runs / (wickets + 1); legal pressure balls / "
                        "(wickets + 1). The +1 stabilizes low wicket counts.",
                    ],
                    [
                        "Consistency",
                        "Share of qualifying match-spell legal pressure balls in spells "
                        "with economy at or below the phase-mix-weighted baseline.",
                    ],
                ],
                [1.75 * inch, available_width - 1.75 * inch],
                styles,
            ),
            Spacer(1, 0.12 * inch),
            Paragraph(
                "Eligibility: batters need >= 60 pressure balls across >= 8 qualifying pressure "
                "innings. Bowlers need >= 60 legal pressure balls across >= 8 qualifying "
                "match-spells. Each innings/spell needs >= 6 pressure balls to contribute. A "
                "bowler spell is a player-match grouping, not an official scorecard spell.",
                styles["BodyText"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        _heading(
            "04 | Shrinkage and composite scoring",
            "Exposure-adjusted rates are combined only after within-group standardization.",
            styles,
        )
    )
    story.extend(
        [
            Paragraph("Step 1 - exposure-based shrinkage", styles["Heading3"]),
            Paragraph(
                "Shrunk rate = [n / (n + k)] x player rate + [k / (n + k)] x group baseline; "
                "k = 100 balls. At n=100, the observed rate and baseline each receive half "
                "the weight. A 180 SR on 50 balls with a 140 baseline shrinks to 153.3.",
                styles["BodyText"],
            ),
            Paragraph("Step 2 - within-group standardization", styles["Heading3"]),
            Paragraph(
                "Eligible player metrics are converted to z-scores within IPL and T20I groups. "
                "For players with both contexts, group z-scores are combined in proportion to "
                "pressure-ball exposure.",
                styles["BodyText"],
            ),
            Paragraph("Step 3 - signed weighted sum", styles["Heading3"]),
            Paragraph(
                "Positive weights reward higher metrics; negative weights reward lower ones. "
                "Pressure runs and pressure wickets are volume features.",
                styles["BodyText"],
            ),
            Paragraph("Batter composite weights", styles["Heading3"]),
            _table(
                weights_batter, [3.25 * inch, 0.8 * inch, available_width - 4.05 * inch], styles
            ),
            Spacer(1, 0.14 * inch),
            Paragraph("Bowler composite weights", styles["Heading3"]),
            _table(
                weights_bowler, [3.25 * inch, 0.8 * inch, available_width - 4.05 * inch], styles
            ),
            Spacer(1, 0.12 * inch),
            Paragraph(
                "Leaderboard scope: IPL, T20I means the player has observations in both. T20I-only "
                "scope is shown distinctly in the profile tables.",
                styles["BodyText"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        _heading(
            "05 | Repeatability and sensitivity",
            "Saved bootstrap and scenario files from a previous complete run restore the repeat "
            "signals without rerunning the expensive resampling workflow.",
            styles,
        )
    )
    story.extend(
        [
            _table(
                [
                    ["Check", "Procedure", "How to read it"],
                    [
                        "Match bootstrap",
                        "500 resamples with seed 42; valid match IDs sampled with "
                        "replacement; 90% percentile intervals.",
                        "Per-player Top-10 frequency and its valid-replicate "
                        "denominator appear in the profile tables.",
                    ],
                    [
                        "Scenario stability",
                        "16 alternate rankings per role across pressure cutoffs, weights, "
                        "shrinkage, normal baselines, and format scope.",
                        "Scenario retention is Top-10 appearances / valid scenarios.",
                    ],
                    [
                        "Feature sensitivity",
                        "Historical variants remove or normalize pressure runs / wickets "
                        "and regularised bowling measures.",
                        "Old sensitivity ranks are not presented as recalculated for "
                        "this filtered run.",
                    ],
                    [
                        "Split-half",
                        "Chronological and odd/even match-ID partitions.",
                        "Aggregate split-half findings are omitted because they reflect "
                        "the previous unfiltered candidate pool.",
                    ],
                ],
                [1.0 * inch, 2.4 * inch, available_width - 3.4 * inch],
                styles,
            ),
            Spacer(1, 0.18 * inch),
            Paragraph("Reuse and exclusion note", styles["Heading3"]),
            Paragraph(
                f"Repeatability source run: {robustness_source_run or 'none'}. The per-player "
                "bootstrap and scenario CSV rows for Pakistan/Pakistan A squad-mapped IDs were "
                "filtered out before display. Remaining values are historical estimates from "
                "the prior run and were not recalculated after the candidate exclusion.",
                styles["BodyText"],
            ),
            Paragraph(
                "Bootstrap frequency is conditional on valid player rankings, not an auction "
                "forecast. Scenario stability summarizes membership in the saved alternative "
                "runs; neither statistic measures player availability.",
                styles["BodyText"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        _heading(
            "06 | Batting profiles - composite Top 10",
            "Shrunk pressure strike rate is runs per 100 pressure balls. Scope and repeatability "
            "are shown beside exposure as contextual evidence.",
            styles,
        )
    )
    story.append(
        _table(
            _profile_rows(batter_top10, "batter", robustness),
            [
                0.4 * inch,
                1.05 * inch,
                1.0 * inch,
                0.75 * inch,
                0.75 * inch,
                1.15 * inch,
                available_width - 5.1 * inch,
            ],
            styles,
        )
    )
    story.extend(
        [
            Spacer(1, 0.16 * inch),
            Paragraph(
                f"{batter_leader} leads the filtered composite. {batter_ipl_name} is the "
                "highest-ranked IPL-only batter in this Top 10. Compare all profiles with a "
                "confirmed role, availability, fitness, current form, and auction value.",
                styles["BodyText"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        _heading(
            "07 | Bowling profiles - composite Top 10",
            "Shrunk pressure economy is runs per six legal pressure balls; lower is favorable. "
            "Wickets use the configured credit list.",
            styles,
        )
    )
    story.append(
        _table(
            _profile_rows(bowler_top10, "bowler", robustness),
            [
                0.4 * inch,
                1.05 * inch,
                1.0 * inch,
                0.75 * inch,
                0.75 * inch,
                1.15 * inch,
                available_width - 5.1 * inch,
            ],
            styles,
        )
    )
    story.extend(
        [
            Spacer(1, 0.16 * inch),
            Paragraph(
                f"{bowler_leader} leads the filtered composite and is the highest-ranked "
                f"IPL-only bowler in this Top 10. The repeat signal for {bowler_ipl_name} is "
                "historical context; confirm role and current availability separately.",
                styles["BodyText"],
            ),
            PageBreak(),
        ]
    )

    story.extend(
        _heading(
            "08 | Applying the profiles to RR planning",
            "A practical review moves from team requirement to player evidence, then to auction "
            "and value context.",
            styles,
        )
    )
    story.extend(
        [
            _table(
                [
                    ["Review step", "Decision input"],
                    [
                        "Squad roles",
                        "Compare confirmed retentions and role coverage; identify the "
                        "specific batting or bowling slot to address.",
                    ],
                    [
                        "Player role",
                        "Check recent, phase-specific evidence against the intended role. "
                        "These aggregate rankings describe pressure performance across "
                        "situations.",
                    ],
                    [
                        "Player readiness",
                        "Review current form, availability, fitness, workload, and role "
                        "transfer between formats.",
                    ],
                    [
                        "Auction value",
                        "Compare price expectations and alternatives with the role value RR needs.",
                    ],
                    [
                        "Data quality",
                        "As authoritative scoring documentation becomes available, "
                        "reconcile batter runs, extras, legal balls, dismissals, and "
                        "bowler charges.",
                    ],
                ],
                [1.25 * inch, available_width - 1.25 * inch],
                styles,
            ),
            Spacer(1, 0.2 * inch),
            Paragraph("Method record", styles["Heading3"]),
            Paragraph(
                f"Ranking run: {run_id}<br/>"
                f"Completed: {manifest.get('completed_at', '')[:10]}<br/>"
                f"Repeatability source run: {robustness_source_run or 'none'}<br/>"
                f"Excluded candidates: {excluded_count} IDs mapped to Pakistan/Pakistan A "
                "squads<br/>"
                f"Random seed: {manifest.get('random_seed', 42)}; bootstrap resamples: 500; "
                "percentile interval: 90%; shrinkage k: 100.",
                styles["BodyText"],
            ),
            Spacer(1, 0.18 * inch),
            Paragraph(
                "Scoring mappings are exploratory assumptions, not source-confirmed definitions. "
                "The source has no nationality field; roster membership is used as an eligibility "
                "proxy. Player availability and auction value must be confirmed from current "
                "official information.",
                styles["BodyText"],
            ),
            Spacer(1, 0.12 * inch),
            Paragraph(
                "Latest dashboard: https://proindra.github.io/SupeRRSelectorSeason2challenge/",
                styles["BodyText"],
            ),
            Paragraph(
                f"Prepared {datetime.now().strftime('%d %B %Y')}. This is a historical, "
                "exploratory report, not a player-selection recommendation.",
                styles["BodyText"],
            ),
        ]
    )

    BRIEF_PATH.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(BRIEF_PATH),
        pagesize=A4,
        rightMargin=0.48 * inch,
        leftMargin=0.48 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.58 * inch,
        title="RR IPL 2027 Pressure Brief",
    )
    document.build(story, onFirstPage=_page_chrome, onLaterPages=_page_chrome)

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
