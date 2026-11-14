from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from suprr.config import load_config
from suprr.pipeline import _write_run_manifest
from suprr.validation.audit import AuditResult
from suprr.validation.report import write_audit_report


def test_default_scoring_mappings_are_exploratory_assumptions() -> None:
    root = Path(__file__).resolve().parents[1]
    scoring = load_config(root / "config" / "default.yaml").scoring

    assert scoring.extras["no_ball"] == ["Overstep"]
    assert scoring.extras["penalty"] == ["Penalty"]
    assert scoring.extras["other"] == ["other"]
    assert scoring.dismissals["unresolved"] == []
    assert not scoring.batter_runs_excludes_extras_confirmed
    assert not scoring.legal_delivery_categories_confirmed


def test_run_manifest_records_exploratory_scope(
    config, tmp_path: Path
) -> None:
    now = datetime.now(UTC).isoformat()
    manifest = _write_run_manifest(
        tmp_path,
        run_id="exploratory-run",
        config=config,
        data_fingerprint="fingerprint",
        data_manifest=[],
        status="EXPLORATORY_COMPLETE",
        started_at=now,
        completed_at=now,
    )

    assert manifest["output_label"] == "EXPLORATORY"
    assert manifest["analysis_mode"] == "ASSUMPTION_BASED_EXPLORATORY"


def test_audit_export_is_diagnostic_and_does_not_claim_to_gate_results(
    tmp_path: Path,
) -> None:
    audit = AuditResult(
        status="BLOCKED",
        findings=[],
        tables={},
        checks={
            "gate_statuses": [
                {
                    "gate_id": "extras_classification",
                    "status": "UNRESOLVED",
                    "evidence": "Source definition is unavailable.",
                }
            ],
            "source_investigation_summary": {},
        },
        schemas={},
    )

    write_audit_report(audit, tmp_path)

    status = json.loads((tmp_path / "audit_status.json").read_text(encoding="utf-8"))
    exported_audit = json.loads((tmp_path / "data_audit.json").read_text(encoding="utf-8"))

    assert status["workflow_status"] == "EXPLORATORY_ONLY"
    assert status["source_evidence"][0]["source_confirmation_needed"]
    assert "audit_status" not in status
    assert set(status["source_evidence"][0]) == {
        "gate_id",
        "status",
        "evidence",
        "source_confirmation_needed",
    }
    assert exported_audit["status"] == "DIAGNOSTICS_ONLY"
