from __future__ import annotations

from typing import Any

_METRIC_DEPENDENCIES: tuple[dict[str, Any], ...] = (
    {
        "metric_id": "batter_runs",
        "metric": "Batter runs",
        "ranking_track": "batter",
        "required_gates": ["batter_runs_semantics"],
    },
    {
        "metric_id": "strike_rate",
        "metric": "Strike rate",
        "ranking_track": "batter",
        "required_gates": ["batter_runs_semantics"],
    },
    {
        "metric_id": "boundary_rate",
        "metric": "Boundary rate",
        "ranking_track": "batter",
        "required_gates": ["batter_runs_semantics"],
    },
    {
        "metric_id": "dot_rate",
        "metric": "Dot rate",
        "ranking_track": "batter",
        "required_gates": ["batter_runs_semantics", "extras_classification"],
    },
    {
        "metric_id": "innings_totals",
        "metric": "Innings totals",
        "ranking_track": "pressure",
        "required_gates": [
            "batter_runs_semantics",
            "total_delivery_runs",
            "extras_classification",
        ],
    },
    {
        "metric_id": "targets",
        "metric": "Targets",
        "ranking_track": "pressure",
        "required_gates": ["total_delivery_runs"],
    },
    {
        "metric_id": "pressure_state",
        "metric": "Pressure state",
        "ranking_track": "pressure",
        "required_gates": [
            "batter_runs_semantics",
            "total_delivery_runs",
            "extras_classification",
            "legal_delivery_rules",
            "super_over_classification",
            "revised_conditions",
        ],
    },
    {
        "metric_id": "batter_attribution",
        "metric": "Batter run attribution",
        "ranking_track": "batter",
        "required_gates": ["batter_runs_semantics", "extras_classification"],
    },
    {
        "metric_id": "legal_deliveries",
        "metric": "Legal deliveries",
        "ranking_track": "multiple",
        "required_gates": ["extras_classification", "legal_delivery_rules"],
    },
    {
        "metric_id": "balls_remaining",
        "metric": "Balls remaining",
        "ranking_track": "pressure",
        "required_gates": [
            "legal_delivery_rules",
            "super_over_classification",
            "revised_conditions",
        ],
    },
    {
        "metric_id": "overs",
        "metric": "Overs bowled",
        "ranking_track": "bowler",
        "required_gates": ["legal_delivery_rules"],
    },
    {
        "metric_id": "bowler_runs_conceded",
        "metric": "Bowler runs conceded",
        "ranking_track": "bowler",
        "required_gates": [
            "total_delivery_runs",
            "extras_classification",
            "bowler_runs_conceded",
        ],
    },
    {
        "metric_id": "economy",
        "metric": "Economy",
        "ranking_track": "bowler",
        "required_gates": [
            "legal_delivery_rules",
            "total_delivery_runs",
            "extras_classification",
            "bowler_runs_conceded",
        ],
    },
    {
        "metric_id": "bowling_average",
        "metric": "Bowling average",
        "ranking_track": "bowler",
        "required_gates": ["bowler_runs_conceded", "stump_dismissal"],
    },
    {
        "metric_id": "bowling_strike_rate",
        "metric": "Bowling strike rate",
        "ranking_track": "bowler",
        "required_gates": ["legal_delivery_rules", "stump_dismissal"],
    },
    {
        "metric_id": "batter_dismissal_rate",
        "metric": "Batter dismissal rate",
        "ranking_track": "batter",
        "required_gates": ["stump_dismissal"],
    },
    {
        "metric_id": "bowler_wickets",
        "metric": "Bowler-credited wickets",
        "ranking_track": "bowler",
        "required_gates": ["stump_dismissal"],
    },
)

_GATE_IMPACTS: tuple[dict[str, Any], ...] = (
    {
        "gate_id": "super_over_classification",
        "source_fields": "ball_by_ball.csv:match_id,innings; matches.csv:match_id,result",
        "record_kind": "deliveries",
        "record_description": (
            "All innings 3+ rows; confirmed groups and identifiers are in "
            "super_over_reconciliation.csv."
        ),
        "count_key": "super_over_rows",
        "metric_ids": ["pressure_state", "balls_remaining"],
        "additional_metrics": (
            "Batter, bowler, and pressure statistics from these rows (excluded from "
            "primary ranking inputs)"
        ),
        "ranking_track": "multiple",
        "impact_scope": "direct exclusion from all tracks; downstream ranking eligibility",
        "evidence_needed": (
            "No additional evidence for this snapshot; retain the explicit match-result "
            "Super Over evidence and ordinary innings 1/2 presence."
        ),
    },
    {
        "gate_id": "revised_conditions",
        "source_fields": (
            "matches.csv:revised_target,first_inn_revised_overs,"
            "second_inn_revised_overs,result"
        ),
        "record_kind": "matches",
        "record_description": (
            "All deliveries in the affected matches; match IDs and per-innings row counts "
            "are in revised_target_exclusions.csv."
        ),
        "count_key": "revised_match_count",
        "metric_ids": ["pressure_state", "balls_remaining"],
        "additional_metrics": (
            "Batter, bowler, and pressure statistics from these matches (excluded from "
            "primary ranking inputs)"
        ),
        "ranking_track": "multiple",
        "impact_scope": "direct exclusion from all tracks; downstream ranking eligibility",
        "evidence_needed": (
            "Effective target and scheduled legal balls at each delivery, or an authoritative "
            "delivery timeline that reconstructs both."
        ),
    },
    {
        "gate_id": "batter_runs_semantics",
        "source_fields": "ball_by_ball.csv:runs,is_four,is_six,extras_type",
        "record_kind": "deliveries",
        "record_description": (
            "All delivery rows; run/flag comparisons and extra-labeled exceptions are "
            "summarized in the investigation reports."
        ),
        "count_key": "delivery_rows",
        "metric_ids": [
            "batter_runs",
            "strike_rate",
            "boundary_rate",
            "dot_rate",
            "innings_totals",
            "pressure_state",
            "batter_attribution",
        ],
        "ranking_track": "multiple",
        "impact_scope": "direct metric input; downstream totals and pressure",
        "evidence_needed": (
            "Source-owner data dictionary or scorecard reconciliation confirming whether "
            "`runs` is batter-only, and how extra-labeled rows are represented."
        ),
    },
    {
        "gate_id": "total_delivery_runs",
        "source_fields": "ball_by_ball.csv:runs,extras1_runs,extras_2_runs",
        "record_kind": "deliveries",
        "record_description": (
            "All delivery rows; exact disputed extras rows and surrounding context are in "
            "investigation_records.csv."
        ),
        "count_key": "delivery_rows",
        "metric_ids": ["innings_totals", "targets", "pressure_state", "bowler_runs_conceded"],
        "ranking_track": "multiple",
        "impact_scope": "direct score input; downstream targets, pressure, and bowling metrics",
        "evidence_needed": (
            "Authoritative definition of each runs column and a documented total-runs "
            "reconciliation against official innings totals."
        ),
    },
    {
        "gate_id": "extras_classification",
        "source_fields": (
            "ball_by_ball.csv:extras_type,runs,extras1_runs,extras_2_runs,"
            "is_four,is_six,is_wicket"
        ),
        "record_kind": "deliveries",
        "record_description": (
            "Overstep, Penalty, and other rows; exact delivery IDs and context are in "
            "investigation_records.csv."
        ),
        "count_key": "unresolved_extras_rows",
        "metric_ids": [
            "dot_rate",
            "innings_totals",
            "pressure_state",
            "batter_attribution",
            "legal_deliveries",
            "bowler_runs_conceded",
            "economy",
        ],
        "ranking_track": "multiple",
        "impact_scope": "direct extras attribution; downstream scoring and legal-ball metrics",
        "evidence_needed": (
            "Source extras codebook mapping every raw label and run column to batter runs, "
            "team extras, bowler charge, and legal-ball effect."
        ),
    },
    {
        "gate_id": "legal_delivery_rules",
        "source_fields": "ball_by_ball.csv:extras_type,extras1_runs,extras_2_runs",
        "record_kind": "deliveries",
        "record_description": (
            "All deliveries need a legal-ball decision; disputed extras categories are "
            "listed in investigation_records.csv."
        ),
        "count_key": "delivery_rows",
        "metric_ids": [
            "legal_deliveries",
            "balls_remaining",
            "overs",
            "economy",
            "bowling_strike_rate",
            "pressure_state",
        ],
        "ranking_track": "multiple",
        "impact_scope": "direct legal-ball count; downstream overs, economy, and pressure",
        "evidence_needed": (
            "Source-owner rule or explicit legal-delivery flag covering every extras label, "
            "including Overstep, Penalty, and other."
        ),
    },
    {
        "gate_id": "bowler_runs_conceded",
        "source_fields": (
            "ball_by_ball.csv:runs,extras_type,extras1_runs,extras_2_runs,bowler_id"
        ),
        "record_kind": "deliveries",
        "record_description": (
            "All deliveries with a bowler assignment; unresolved extras attribution is "
            "documented in investigation_records.csv and source_value_frequencies.csv."
        ),
        "count_key": "delivery_rows",
        "metric_ids": ["bowler_runs_conceded", "economy", "bowling_average"],
        "ranking_track": "bowler",
        "impact_scope": "direct bowler-run input; downstream economy and average",
        "evidence_needed": (
            "Authoritative bowler-concession formula by delivery type, reconciled against "
            "official bowler figures."
        ),
    },
    {
        "gate_id": "stump_dismissal",
        "source_fields": (
            "ball_by_ball.csv:dismissal_type,dismissal_type_id,is_wicket,"
            "dismissed_player_id,bowler_id"
        ),
        "record_kind": "deliveries",
        "record_description": (
            "214 Stump rows; exact delivery IDs and context are in investigation_records.csv."
        ),
        "count_key": "stump_rows",
        "metric_ids": [
            "batter_dismissal_rate",
            "bowler_wickets",
            "bowling_average",
            "bowling_strike_rate",
        ],
        "ranking_track": "multiple",
        "impact_scope": "direct dismissal classification; downstream wicket-based metrics",
        "evidence_needed": (
            "Source lookup for dismissal_type_id=5 and confirmation of canonical meaning "
            "and bowler-credit status."
        ),
    },
    {
        "gate_id": "unlabeled_dismissal_metadata",
        "source_fields": (
            "ball_by_ball.csv:dismissal_type,dismissal_type_id,is_wicket,"
            "dismissed_player_id"
        ),
        "record_kind": "deliveries",
        "record_description": (
            "12 rows have a dismissed-player ID but no dismissal label; see the "
            "DISMISSAL_METADATA_WITHOUT_LABEL records in investigation_records.csv."
        ),
        "count_key": "unlabeled_dismissal_metadata_rows",
        "metric_ids": [],
        "ranking_track": "multiple",
        "impact_scope": "direct metadata anomaly; no current derived-metric impact",
        "evidence_needed": (
            "Source-owner explanation of why dismissed_player_id is populated when the "
            "dismissal label is blank and is_wicket is false."
        ),
    },
)

_MANUAL_CONFIRMATIONS: tuple[dict[str, Any], ...] = (
    {
        "issue_id": "batter_runs_semantics",
        "source_label": "runs",
        "count_key": "delivery_rows",
        "current": "INFERRED as batter runs; not confirmed.",
        "candidate": "Batter-only runs excluding extras.",
        "available": (
            "All four/six flags match runs=4/6; 474 extra-labeled rows have nonzero runs."
        ),
        "missing": "Source data dictionary and independent official scorecard reconciliation.",
        "question": (
            "Does runs contain batter-only runs on every delivery, including rows with extras?"
        ),
    },
    {
        "issue_id": "total_delivery_runs",
        "source_label": "runs, extras1_runs, extras_2_runs",
        "count_key": "delivery_rows",
        "current": "UNRESOLVED; no authoritative total-delivery-runs field or aggregation.",
        "candidate": "A source-owner-defined aggregation, not assumed by this audit.",
        "available": "Raw values and delivery context for disputed categories.",
        "missing": "Field definitions and reconciliation against official innings totals.",
        "question": (
            "Which fields and aggregation produce total runs for a delivery, and how do "
            "the two extras-run columns contribute?"
        ),
    },
    {
        "issue_id": "extras_Overstep",
        "source_label": "extras_type=Overstep",
        "count_key": "overstep_rows",
        "current": "Candidate no-ball mapping is INFERRED, not confirmed.",
        "candidate": "No-ball, subject to source-owner confirmation.",
        "available": "576 rows; extras1_runs is nonzero on all; 128 have four/six flags.",
        "missing": "Source extras codebook and delivery-rule definition.",
        "question": (
            "Does Overstep mean no-ball, and how are its runs, batter attribution, and "
            "legal-ball effect recorded?"
        ),
    },
    {
        "issue_id": "extras_Penalty",
        "source_label": "extras_type=Penalty",
        "count_key": "penalty_rows",
        "current": "UNRESOLVED; one row has extras1_runs=5.",
        "candidate": "Penalty extras, with recipient and bowler charge unspecified.",
        "available": "One raw record and its surrounding delivery context.",
        "missing": "Penalty type/recipient semantics and scoring attribution.",
        "question": (
            "What does this Penalty represent, which side receives the runs, and are they "
            "charged to the bowler?"
        ),
    },
    {
        "issue_id": "extras_other",
        "source_label": "extras_type=other",
        "count_key": "other_rows",
        "current": "UNRESOLVED; do not treat as overthrows or assign runs.",
        "candidate": "Source-defined category or categories.",
        "available": "264 rows, raw value frequencies, and surrounding deliveries.",
        "missing": "Codebook for other and the meaning of extras_2_runs.",
        "question": (
            "What events does other encode, and what is the scoring and legal-ball rule for each?"
        ),
    },
    {
        "issue_id": "legal_delivery_rules",
        "source_label": "extras_type and extras-run columns",
        "count_key": "delivery_rows",
        "current": "UNRESOLVED; no explicit legal-ball flag or complete source rule.",
        "candidate": "Official source-owner rule by raw delivery/extras category.",
        "available": "Raw category counts and exact context for disputed extras.",
        "missing": (
            "Legal-delivery definition for every category, including Overstep, Penalty, other."
        ),
        "question": (
            "Which delivery categories consume a legal ball in this source, and "
            "are there exceptions?"
        ),
    },
    {
        "issue_id": "bowler_runs_conceded",
        "source_label": "runs, extras_type, extras1_runs, extras_2_runs",
        "count_key": "delivery_rows",
        "current": "UNRESOLVED; bowler charges cannot be derived reliably.",
        "candidate": (
            "A source-owner-defined attribution rule reconciled with official bowler figures."
        ),
        "available": "Bowler IDs and delivery-level raw scoring columns.",
        "missing": "Bowler charge rules for each extras type and total-run definition.",
        "question": "Which delivery runs are charged to the bowler for each extras category?",
    },
    {
        "issue_id": "stump_dismissal",
        "source_label": "dismissal_type=Stump; dismissal_type_id=5",
        "count_key": "stump_rows",
        "current": "UNRESOLVED; deliberately excluded from canonical and bowler-credit mapping.",
        "candidate": "Stumped is a candidate only; bowler credit is not assumed.",
        "available": "214 rows; all have is_wicket=true and dismissed_player_id populated.",
        "missing": "Lookup for ID 5 and source confirmation of bowler-credit treatment.",
        "question": (
            "What does dismissal_type_id=5 mean, and is this dismissal credited to the bowler?"
        ),
    },
    {
        "issue_id": "unlabeled_dismissal_metadata",
        "source_label": "dismissal_type blank; dismissed_player_id populated",
        "count_key": "unlabeled_dismissal_metadata_rows",
        "current": "UNRESOLVED metadata anomaly; all 12 rows have is_wicket=false.",
        "candidate": "Non-dismissal metadata, subject to confirmation.",
        "available": "12 affected rows and surrounding delivery context.",
        "missing": "Source explanation for the populated dismissed_player_id.",
        "question": (
            "Do these rows represent dismissals, or is dismissed_player_id populated "
            "for another reason?"
        ),
    },
    {
        "issue_id": "revised_conditions",
        "source_label": "revised_target, first_inn_revised_overs, second_inn_revised_overs",
        "count_key": "revised_match_count",
        "current": "EXCLUDED_WITH_REASON from the primary model.",
        "candidate": (
            "Include only if effective target and scheduled balls are known at each delivery."
        ),
        "available": (
            "Revised metadata, match results, and per-innings delivery counts for 34 matches."
        ),
        "missing": "Effective-target delivery and scheduled-ball timeline.",
        "question": (
            "Can the effective target and scheduled legal-ball budget at each delivery be "
            "supplied for these matches?"
        ),
    },
    {
        "issue_id": "super_over_classification",
        "source_label": "innings=3/4 and matches.result",
        "count_key": "super_over_rows",
        "current": "CONFIRMED Super Overs; excluded from the primary model.",
        "candidate": "Not applicable; retain explicit result-text evidence.",
        "available": "38 rows in 12 groups across six matches; result text names Super Over.",
        "missing": "No additional evidence is currently required.",
        "question": (
            "Can the source owner confirm that result text is the authoritative Super Over "
            "indicator for this dataset?"
        ),
    },
)


def build_metric_dependencies(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gate_by_id = {str(gate["gate_id"]): gate for gate in gates}
    results: list[dict[str, Any]] = []
    for spec in _METRIC_DEPENDENCIES:
        gate_ids = list(spec["required_gates"])
        unconfirmed = [
            gate_id
            for gate_id in gate_ids
            if gate_id not in gate_by_id
            or gate_by_id[gate_id].get("status") in {"INFERRED", "UNRESOLVED"}
        ]
        excluded = [
            gate_id
            for gate_id in gate_ids
            if gate_id in gate_by_id
            and gate_by_id[gate_id].get("status") == "EXCLUDED_WITH_REASON"
        ]
        if unconfirmed:
            status = "SOURCE_CONFIRMATION_NEEDED"
        elif excluded:
            status = "EXCLUDED_WITH_REASON"
        else:
            status = "SOURCE_EVIDENCE_AVAILABLE"
        results.append(
            {
                **spec,
                "status": status,
                "unconfirmed_dependencies": unconfirmed,
                "excluded_dependencies": excluded,
            }
        )
    return results


def build_impact_matrix(
    gates: list[dict[str, Any]],
    summary: dict[str, Any],
    delivery_rows: int,
    metric_dependencies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gate_by_id = {str(gate["gate_id"]): gate for gate in gates}
    dependent_metrics: dict[str, list[str]] = {}
    metric_status_by_id = {
        str(metric["metric_id"]): str(metric["status"]) for metric in metric_dependencies
    }
    for metric in metric_dependencies:
        for gate_id in metric["required_gates"]:
            dependent_metrics.setdefault(str(gate_id), []).append(
                f"{metric['metric']}={metric_status_by_id[str(metric['metric_id'])]} "
                f"(unconfirmed: {', '.join(metric['unconfirmed_dependencies']) or 'none'}; "
                f"excluded: {', '.join(metric['excluded_dependencies']) or 'none'})"
            )

    extras = summary.get("extras_by_name", {})
    summary_counts = {
        "delivery_rows": delivery_rows,
        "super_over_rows": int(summary.get("super_over_rows", 0)),
        "revised_match_count": int(summary.get("revised_match_count", 0)),
        "unresolved_extras_rows": sum(
            int(extras.get(label, {}).get("rows", 0))
            for label in ("Overstep", "Penalty", "other")
        ),
        "overstep_rows": int(extras.get("Overstep", {}).get("rows", 0)),
        "penalty_rows": int(extras.get("Penalty", {}).get("rows", 0)),
        "other_rows": int(extras.get("other", {}).get("rows", 0)),
        "stump_rows": int(summary.get("stump_rows", 0)),
        "unlabeled_dismissal_metadata_rows": int(
            summary.get("unlabeled_dismissal_metadata_rows", 0)
        ),
    }
    rows: list[dict[str, Any]] = []
    for spec in _GATE_IMPACTS:
        gate = gate_by_id.get(spec["gate_id"], {})
        count_key = str(spec["count_key"])
        count = summary_counts[count_key]
        metric_names = [
            next(
                str(metric["metric"])
                for metric in metric_dependencies
                if metric["metric_id"] == metric_id
            )
            for metric_id in spec["metric_ids"]
        ]
        if spec.get("additional_metrics"):
            metric_names.append(str(spec["additional_metrics"]))
        rows.append(
            {
                "gate_id": spec["gate_id"],
                "status": gate.get("status", "UNASSESSED"),
                "source_confirmation_needed": gate.get("status")
                in {"INFERRED", "UNRESOLVED", "UNASSESSED"},
                "affected_source_fields": spec["source_fields"],
                "affected_record_kind": spec["record_kind"],
                "affected_record_count": count,
                "affected_delivery_records": spec["record_description"],
                "affected_derived_metrics": "; ".join(metric_names),
                "affected_ranking_track": spec["ranking_track"],
                "impact_scope": spec["impact_scope"],
                "evidence_needed": spec["evidence_needed"],
                "dependent_metric_statuses": "; ".join(
                    dependent_metrics.get(spec["gate_id"], [])
                ),
            }
        )
    return rows


def build_manual_confirmation_rows(
    summary: dict[str, Any], delivery_rows: int
) -> list[dict[str, str]]:
    extras = summary.get("extras_by_name", {})
    counts = {
        "delivery_rows": delivery_rows,
        "overstep_rows": int(extras.get("Overstep", {}).get("rows", 0)),
        "penalty_rows": int(extras.get("Penalty", {}).get("rows", 0)),
        "other_rows": int(extras.get("other", {}).get("rows", 0)),
        "stump_rows": int(summary.get("stump_rows", 0)),
        "unlabeled_dismissal_metadata_rows": int(
            summary.get("unlabeled_dismissal_metadata_rows", 0)
        ),
        "revised_match_count": int(summary.get("revised_match_count", 0)),
        "super_over_rows": int(summary.get("super_over_rows", 0)),
    }
    return [
        {
            "Issue ID": str(spec["issue_id"]),
            "Raw source label or field": str(spec["source_label"]),
            "Affected row count": str(counts[str(spec["count_key"])]),
            "Affected count unit": (
                "matches" if spec["count_key"] == "revised_match_count" else "delivery rows"
            ),
            "Current interpretation": str(spec["current"]),
            "Candidate interpretation": str(spec["candidate"]),
            "Evidence available": str(spec["available"]),
            "Evidence missing": str(spec["missing"]),
            "Exact question requiring source-owner confirmation": str(spec["question"]),
            "Decision": "",
            "Decision source": "",
            "Decision date": "",
        }
        for spec in _MANUAL_CONFIRMATIONS
    ]


def render_impact_markdown(
    rows: list[dict[str, Any]],
    metric_dependencies: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    lines = [
        "# Audit Impact and Metric Dependencies",
        "",
        "This report summarizes source evidence relevant to the saved exploratory metrics. "
        "Unconfirmed mappings are assumptions, not execution gates.",
        "",
        "## Confirmed exclusions",
        "",
        (
            f"- Super Overs: {summary.get('super_over_innings_groups', 0)} confirmed innings "
            f"groups, {summary.get('super_over_rows', 0)} delivery rows across "
            f"{summary.get('super_over_matches', 0)} matches. See "
            "`super_over_reconciliation.csv` for each match/innings and evidence."
        ),
        (
            f"- Revised conditions: {summary.get('revised_match_count', 0)} matches excluded "
            "because effective-target timing and per-delivery scheduled balls are unavailable. "
            "See `revised_target_exclusions.csv`."
        ),
        "",
        "## Source evidence by metric",
        "",
        "| Derived metric | Ranking track | Evidence topics | Status | "
        "Unconfirmed evidence | Exclusions |",
        "|---|---|---|---|---|---|",
    ]
    for metric in metric_dependencies:
        lines.append(
            f"| {metric['metric']} | {metric['ranking_track']} | "
            f"{', '.join(f'`{gate}`' for gate in metric['required_gates'])} | "
            f"**{metric['status']}** | "
            f"{', '.join(metric['unconfirmed_dependencies']) or 'None'} | "
            f"{', '.join(metric['excluded_dependencies']) or 'None'} |"
        )
    lines.extend(["", "## Source evidence details", ""])
    for row in rows:
        derived_metrics = row["affected_derived_metrics"] or "None in current metrics"
        lines.extend(
            [
                f"### `{row['gate_id']}` — {row['status']}",
                "",
                f"- Source confirmation needed: **{row['source_confirmation_needed']}**",
                f"- Affected source fields: {row['affected_source_fields']}",
                (
                    f"- Affected records: {row['affected_record_count']:,} "
                    f"{row['affected_record_kind']}; {row['affected_delivery_records']}"
                ),
                f"- Derived metrics: {derived_metrics}",
                f"- Ranking track: {row['affected_ranking_track']}",
                f"- Impact: {row['impact_scope']}",
                f"- Evidence needed: {row['evidence_needed']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Evidence dependencies",
            "",
            "- Batter runs semantics -> batter runs, strike rate, boundary rate, dot rate.",
            "- Total delivery runs -> innings totals, targets, pressure state.",
            "- Extras classification -> batter attribution, bowler runs conceded, "
            "legal deliveries.",
            "- Legal deliveries -> balls remaining, overs, economy, bowling strike rate.",
            "- Bowler runs conceded -> economy and bowling average.",
            "- Dismissal mapping -> batter dismissal rate and bowler wickets.",
            "",
        ]
    )
    return "\n".join(lines)
