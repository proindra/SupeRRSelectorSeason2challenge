from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from suprr.validation.audit import AuditResult
from suprr.validation.impact import (
    build_impact_matrix,
    build_manual_confirmation_rows,
    build_metric_dependencies,
    render_impact_markdown,
)


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_audit_report(
    audit: AuditResult,
    output_dir: Path,
    *,
    analysis_mode: str = "ASSUMPTION_BASED_EXPLORATORY",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_payload = audit.to_dict()
    audit_payload["status"] = "DIAGNOSTICS_ONLY"
    audit_payload["analysis_mode"] = analysis_mode
    audit_payload["output_label"] = "EXPLORATORY"
    checks = audit_payload["checks"]
    summary = checks.get("source_investigation_summary")
    if isinstance(summary, dict) and "primary_model_status" in summary:
        summary["primary_model_status"] = "ASSUMPTION_BASED_EXPLORATORY"
    for finding in audit_payload["findings"]:
        if finding["severity"] == "blocking":
            finding["severity"] = "high-priority"
    gates = [
        {
            **gate,
            "source_confirmation_needed": gate.get("status")
            in {"INFERRED", "UNRESOLVED", "UNASSESSED"},
        }
        for gate in audit.checks.get("gate_statuses", [])
    ]
    checks.pop("gate_statuses", None)
    checks["source_evidence"] = gates
    (output_dir / "data_audit.json").write_text(
        json.dumps(audit_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary = checks.get("source_investigation_summary", {})
    delivery_rows = int(audit.tables.get("deliveries", {}).get("rows", 0))
    metric_dependencies = build_metric_dependencies(gates)
    impact_rows = build_impact_matrix(gates, summary, delivery_rows, metric_dependencies)
    manual_rows = build_manual_confirmation_rows(summary, delivery_rows)
    super_over_exclusions = {
        "status": "CONFIRMED"
        if int(summary.get("super_over_unverified_innings_groups", 0)) == 0
        else "UNRESOLVED",
        "innings_groups": int(summary.get("super_over_innings_groups", 0)),
        "delivery_rows": int(summary.get("super_over_rows", 0)),
        "matches": int(summary.get("super_over_matches", 0)),
        "reason": (
            "Match-result text explicitly names a Super Over and ordinary innings 1 and 2 "
            "are present; provisional score equality is corroborative only."
        ),
    }
    revised_exclusions = {
        "status": "EXCLUDED_WITH_REASON"
        if int(summary.get("revised_match_count", 0))
        else "CONFIRMED",
        "matches": int(summary.get("revised_match_count", 0)),
        "reason": (
            "No effective-target delivery or per-delivery scheduled-balls timeline is "
            "available; exclude affected matches from the primary model."
        ),
    }
    status_payload = {
        "schema_version": 1,
        "workflow_status": "EXPLORATORY_ONLY",
        "analysis_mode": analysis_mode,
        "output_label": "EXPLORATORY",
        "diagnostic_findings": [finding.code for finding in audit.blockers],
        "source_evidence": gates,
        "metric_dependency_scope": "SOURCE_EVIDENCE_DEPENDENCIES",
        "confirmed_exclusions": {
            "super_overs": super_over_exclusions,
            "revised_conditions": revised_exclusions,
        },
        "metric_dependencies": metric_dependencies,
    }
    (output_dir / "audit_status.json").write_text(
        json.dumps(status_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_rows_csv(output_dir / "audit_impact_matrix.csv", impact_rows)
    (output_dir / "audit_impact_matrix.md").write_text(
        render_impact_markdown(impact_rows, metric_dependencies, summary),
        encoding="utf-8",
    )
    _write_rows_csv(output_dir / "manual_data_confirmation.csv", manual_rows)
    lines = [
        "# Data Audit",
        "",
        "**Workflow status:** EXPLORATORY_ONLY",
        f"**Run mode:** {analysis_mode}",
        "**Output label:** EXPLORATORY — configured assumptions do not establish "
        "source-confirmed semantics. Audit findings are diagnostic and do not gate this workflow.",
        "",
        "## File inventory",
        "",
        "| Table | Rows | Columns | Duplicate full rows |",
        "|---|---:|---:|---:|",
    ]
    for table, stats in audit.tables.items():
        lines.append(
            f"| `{table}` | {stats['rows']:,} | {stats['columns']} | "
            f"{stats['duplicate_full_rows']:,} |"
        )
    if gates:
        lines.extend(
            [
                "",
                "## Source evidence statuses",
                "",
                "| Evidence topic | Status | Source confirmation needed | Evidence |",
                "|---|---|---|---|",
            ]
        )
        for gate in gates:
            lines.append(
                f"| `{gate['gate_id']}` | **{gate['status']}** | "
                f"{'Yes' if gate['source_confirmation_needed'] else 'No'} | "
                f"{gate['evidence']} |"
            )
    lines.extend(["", "## Findings", ""])
    if not audit.findings:
        lines.append("No audit findings.")
    for finding in audit.findings:
        priority = (
            "HIGH-PRIORITY DIAGNOSTIC"
            if finding.severity == "blocking"
            else finding.severity.upper()
        )
        lines.append(
            f"- **{priority} — {finding.code}:** {finding.message} "
            f"Evidence: `{finding.evidence}`"
        )
    lines.extend(["", "## Required checks", ""])
    for key, value in checks.items():
        lines.append(f"- **{key}:** `{value}`")
    lines.extend(["", "## Detected schemas", ""])
    for table, columns in audit.schemas.items():
        lines.extend(
            [
                f"### `{table}`",
                "",
                "| Column | dtype | Nulls | Distinct non-null |",
                "|---|---|---:|---:|",
            ]
        )
        for column in columns:
            lines.append(
                f"| `{column['column']}` | {column['dtype']} | {column['null_count']:,} | "
                f"{column['distinct_non_null']:,} |"
            )
        lines.append("")
    (output_dir / "data_audit.md").write_text("\n".join(lines), encoding="utf-8")
