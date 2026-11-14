from __future__ import annotations

from suprr.validation.impact import (
    build_impact_matrix,
    build_manual_confirmation_rows,
    build_metric_dependencies,
)


def test_unconfirmed_source_evidence_is_reported_without_workflow_gates():
    gates = [
        {
            "gate_id": "batter_runs_semantics",
            "status": "INFERRED",
        },
        {
            "gate_id": "total_delivery_runs",
            "status": "UNRESOLVED",
        },
        {
            "gate_id": "extras_classification",
            "status": "UNRESOLVED",
        },
        {
            "gate_id": "legal_delivery_rules",
            "status": "UNRESOLVED",
        },
        {
            "gate_id": "bowler_runs_conceded",
            "status": "UNRESOLVED",
        },
        {
            "gate_id": "stump_dismissal",
            "status": "UNRESOLVED",
        },
        {
            "gate_id": "super_over_classification",
            "status": "CONFIRMED",
        },
        {
            "gate_id": "revised_conditions",
            "status": "EXCLUDED_WITH_REASON",
        },
    ]

    metrics = build_metric_dependencies(gates)
    by_id = {metric["metric_id"]: metric for metric in metrics}

    assert by_id["strike_rate"]["status"] == "SOURCE_CONFIRMATION_NEEDED"
    assert by_id["strike_rate"]["unconfirmed_dependencies"] == ["batter_runs_semantics"]
    assert by_id["pressure_state"]["status"] == "SOURCE_CONFIRMATION_NEEDED"
    assert by_id["bowler_runs_conceded"]["status"] == "SOURCE_CONFIRMATION_NEEDED"
    assert by_id["batter_dismissal_rate"]["status"] == "SOURCE_CONFIRMATION_NEEDED"
    assert all(not metric["status"].startswith("VALIDATED") for metric in metrics)


def test_confirmed_exclusions_are_not_reported_as_validated_metrics():
    gates = [
        {
            "gate_id": "legal_delivery_rules",
            "status": "CONFIRMED",
        },
        {
            "gate_id": "super_over_classification",
            "status": "CONFIRMED",
        },
        {
            "gate_id": "revised_conditions",
            "status": "EXCLUDED_WITH_REASON",
        },
    ]

    metrics = {row["metric_id"]: row for row in build_metric_dependencies(gates)}

    assert metrics["balls_remaining"]["status"] == "EXCLUDED_WITH_REASON"
    assert metrics["balls_remaining"]["excluded_dependencies"] == ["revised_conditions"]


def test_manual_confirmation_decision_fields_are_blank_until_confirmed():
    rows = build_manual_confirmation_rows(
        {
            "extras_by_name": {
                "Overstep": {"rows": 576},
                "Penalty": {"rows": 1},
                "other": {"rows": 264},
            },
            "stump_rows": 214,
            "unlabeled_dismissal_metadata_rows": 12,
            "revised_match_count": 34,
            "super_over_rows": 38,
        },
        delivery_rows=200999,
    )

    assert rows
    assert all(row["Decision"] == "" for row in rows)
    assert all(row["Decision source"] == "" for row in rows)
    assert all(row["Decision date"] == "" for row in rows)
    assert next(row for row in rows if row["Issue ID"] == "extras_Overstep")[
        "Affected row count"
    ] == "576"


def test_impact_matrix_retains_gate_status_and_record_counts():
    gates = [
        {
            "gate_id": "stump_dismissal",
            "status": "UNRESOLVED",
            "affected_rows": 214,
        }
    ]
    summary = {"stump_rows": 214}
    metrics = build_metric_dependencies(gates)

    matrix = build_impact_matrix(gates, summary, 200999, metrics)
    stump = next(row for row in matrix if row["gate_id"] == "stump_dismissal")

    assert stump["status"] == "UNRESOLVED"
    assert stump["source_confirmation_needed"]
    assert stump["affected_record_count"] == 214
    assert "dismissal_type_id" in stump["affected_source_fields"]
    assert stump["affected_ranking_track"] == "multiple"
