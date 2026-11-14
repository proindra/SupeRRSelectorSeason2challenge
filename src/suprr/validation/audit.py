from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from suprr.config import AppConfig
from suprr.ingestion.mapping import validate_required_mappings
from suprr.schemas import SourceTables
from suprr.validation.investigations import SourceInvestigation, investigate_sources
from suprr.validation.joins import join_coverage
from suprr.validation.scoring_rules import dismissal_category, extra_category


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any]


@dataclass
class AuditResult:
    status: str
    findings: list[Finding]
    tables: dict[str, dict[str, Any]]
    checks: dict[str, Any]
    schemas: dict[str, list[dict[str, Any]]]

    @property
    def blockers(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "blocking"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [asdict(finding) for finding in self.findings],
            "tables": self.tables,
            "checks": self.checks,
            "schemas": self.schemas,
        }


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def audit_sources(
    sources: SourceTables,
    config: AppConfig,
    investigation: SourceInvestigation | None = None,
) -> AuditResult:
    findings: list[Finding] = []
    tables: dict[str, dict[str, Any]] = {}
    schemas: dict[str, list[dict[str, Any]]] = {}
    checks: dict[str, Any] = {}
    if investigation is None:
        investigation = investigate_sources(sources, config)
    checks["gate_statuses"] = investigation.gate_statuses
    checks["source_investigation_summary"] = investigation.summary
    checks["super_over_reconciliation"] = {
        "delivery_rows": investigation.summary["super_over_rows"],
        "innings_groups": investigation.summary["super_over_innings_groups"],
        "matches": investigation.summary["super_over_matches"],
        "unverified_innings_groups": investigation.summary["super_over_unverified_innings_groups"],
        "verified_innings": investigation.summary["verified_super_over_innings"],
    }

    def add(code: str, severity: str, message: str, **evidence: Any) -> None:
        findings.append(Finding(code, severity, message, evidence))

    for name, frame in sources.items():
        tables[name] = {
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "duplicate_full_rows": int(frame.duplicated().sum()),
        }
        schemas[name] = [
            {
                "column": str(column),
                "dtype": str(frame[column].dtype),
                "null_count": int(frame[column].isna().sum()),
                "distinct_non_null": int(frame[column].nunique(dropna=True)),
            }
            for column in frame.columns
        ]
        if tables[name]["duplicate_full_rows"]:
            add(
                f"{name.upper()}_DUPLICATE_ROWS",
                "warning",
                f"{name} contains duplicate full rows; no rows were removed.",
                duplicate_rows=tables[name]["duplicate_full_rows"],
            )

    mapping_errors = validate_required_mappings(sources, config)
    for error in mapping_errors:
        add("COLUMN_MAPPING", "blocking", error)
    if mapping_errors:
        return AuditResult(
            status="BLOCKED",
            findings=findings,
            tables=tables,
            checks=checks,
            schemas=schemas,
        )

    deliveries = sources["deliveries"]
    matches = sources["matches"]
    player_map = sources["player_team_mapping"]
    lineup = sources["playing_eleven"]
    teams = sources["teams"]

    checks["matches_match_id_unique"] = bool(
        matches["match_id"].notna().all() and matches["match_id"].is_unique
    )
    checks["matches_duplicate_match_ids"] = int(matches["match_id"].duplicated(keep=False).sum())
    if not checks["matches_match_id_unique"]:
        add(
            "DUPLICATE_MATCH_ID",
            "blocking",
            "matches.match_id is not unique.",
            duplicate_ids=checks["matches_duplicate_match_ids"],
        )

    checks["delivery_match_join"] = join_coverage(deliveries, matches, ["match_id"], ["match_id"])
    if checks["delivery_match_join"]["orphan_rows"]:
        add(
            "ORPHAN_DELIVERY_MATCH",
            "blocking",
            "Some deliveries reference match IDs missing from matches.csv.",
            **checks["delivery_match_join"],
        )
    match_competition = matches[["match_id", "comp_id"]].drop_duplicates()
    delivery_context = deliveries.merge(
        match_competition,
        on="match_id",
        how="left",
        validate="many_to_one",
    )
    player_keys = player_map[["comp_id", "team_id", "player_id"]].drop_duplicates()
    checks["striker_mapping_coverage"] = join_coverage(
        delivery_context,
        player_keys,
        ["comp_id", "batting_team_id", "striker_id"],
        ["comp_id", "team_id", "player_id"],
    )
    checks["bowler_mapping_coverage"] = join_coverage(
        delivery_context,
        player_keys,
        ["comp_id", "bowling_team_id", "bowler_id"],
        ["comp_id", "team_id", "player_id"],
    )
    for role in ["striker", "bowler"]:
        coverage = checks[f"{role}_mapping_coverage"]
        missing_rows = coverage["orphan_rows"] + coverage["incomplete_rows"]
        if missing_rows:
            add(
                f"UNMAPPED_{role.upper()}_IDS",
                "blocking",
                f"Some delivery rows have {role} IDs without a competition/team/player mapping.",
                **coverage,
            )

    delivery_key = ["match_id", "innings", "overid", "over_ball_num"]
    duplicate_delivery_count = int(deliveries.duplicated(delivery_key, keep=False).sum())
    checks["duplicate_delivery_candidates"] = {
        "key": delivery_key,
        "rows_in_duplicate_groups": duplicate_delivery_count,
    }
    if duplicate_delivery_count:
        add(
            "DUPLICATE_DELIVERIES",
            "blocking",
            "Duplicate delivery-key candidates exist and require investigation.",
            **checks["duplicate_delivery_candidates"],
        )

    innings = _numeric(deliveries["innings"])
    checks["innings_values"] = sorted(int(value) for value in innings.dropna().unique())
    checks["innings_3_plus_rows"] = int(innings.ge(3).sum())
    if investigation.summary["super_over_unverified_innings_groups"]:
        add(
            "SUPER_OVER_CLASSIFICATION",
            "blocking",
            "Some innings 3+ lack explicit match-result evidence that they are super overs.",
            innings_values=checks["innings_values"],
            rows=checks["innings_3_plus_rows"],
            unverified_innings_groups=investigation.summary["super_over_unverified_innings_groups"],
        )

    overs = _numeric(deliveries["overid"])
    over_min = float(overs.min()) if overs.notna().any() else None
    over_max = float(overs.max()) if overs.notna().any() else None
    over_base = 1 if over_min == 1 else (0 if over_min == 0 else None)
    checks["over_number_convention"] = {
        "source_column": "overid",
        "minimum": over_min,
        "maximum": over_max,
        "inferred_base": over_base,
        "inference": "one-based"
        if over_base == 1
        else ("zero-based" if over_base == 0 else "ambiguous"),
    }
    if over_base is None:
        add(
            "OVER_NUMBER_CONVENTION",
            "blocking",
            "Could not infer a zero-based or one-based over-number convention.",
            **checks["over_number_convention"],
        )

    extras = deliveries["extras_type"].dropna().astype(str).str.strip()
    extras_values = sorted(extras.unique().tolist())
    extra_counts = extras.value_counts(dropna=False).to_dict()
    extra_categories = {value: extra_category(value, config) for value in extras_values}
    checks["extras"] = {
        "distinct_values": extras_values,
        "counts": {str(key): int(value) for key, value in extra_counts.items()},
        "classification": extra_categories,
        "known_classes": ["none", "wide", "no_ball", "byes", "leg_byes", "penalty"],
    }
    unresolved_extras = sorted(
        value for value, category in extra_categories.items() if category == "unresolved"
    )
    if unresolved_extras:
        add(
            "UNKNOWN_EXTRAS_CATEGORIES",
            "blocking",
            "Extras categories are unclassified; legal-ball and bowler-run rules are ambiguous.",
            categories=unresolved_extras,
        )
    if not config.scoring.legal_delivery_categories_confirmed:
        add(
            "LEGAL_DELIVERY_RULES_UNCONFIRMED",
            "blocking",
            "The source-to-cricket mapping for legal delivery categories is not confirmed.",
        )
    if not config.scoring.batter_runs_excludes_extras_confirmed:
        add(
            "BATTER_RUNS_SEMANTICS_UNCONFIRMED",
            "blocking",
            "The source `runs` field has not been confirmed to exclude extras.",
            source_column="runs",
            extras_columns=["extras1_runs", "extras_2_runs"],
        )

    dismissal = deliveries["dismissal_type"].dropna().astype(str).str.strip()
    dismissal = dismissal[dismissal != ""]
    dismissal_values = sorted(dismissal.unique().tolist())
    dismissal_categories = {value: dismissal_category(value, config) for value in dismissal_values}
    dismissed_ids_present = deliveries["dismissed_player_id"].notna()
    checks["dismissals"] = {
        "distinct_values": dismissal_values,
        "classification": dismissal_categories,
        "rows_with_dismissed_player_id": int(dismissed_ids_present.sum()),
    }
    unresolved_dismissals = sorted(
        value for value, category in dismissal_categories.items() if category == "unresolved"
    )
    if unresolved_dismissals:
        add(
            "UNKNOWN_DISMISSAL_CATEGORIES",
            "blocking",
            "Dismissal categories are not fully mapped to batter and bowler credit rules.",
            categories=unresolved_dismissals,
        )

    four = deliveries["is_four"].astype("string").str.strip().str.lower().eq("true")
    six = deliveries["is_six"].astype("string").str.strip().str.lower().eq("true")
    batter_runs = _numeric(deliveries["runs"])
    checks["run_semantics_evidence"] = {
        "four_flags": int(four.sum()),
        "four_flag_run_mismatches": int((four & batter_runs.ne(4)).sum()),
        "six_flags": int(six.sum()),
        "six_flag_run_mismatches": int((six & batter_runs.ne(6)).sum()),
        "nonzero_runs_on_extras_rows": int(
            (
                deliveries["extras_type"].notna()
                & deliveries["extras_type"].astype(str).str.strip().ne("None")
                & batter_runs.gt(0)
            ).sum()
        ),
    }

    match_id_counts = deliveries.groupby("match_id", dropna=False)["innings"].nunique()
    checks["matches_with_multiple_innings"] = int(match_id_counts.ge(2).sum())
    innings_totals = (
        deliveries.assign(
            _runs=batter_runs.fillna(0)
            + _numeric(deliveries["extras1_runs"]).fillna(0)
            + _numeric(deliveries["extras_2_runs"]).fillna(0)
        )
        .groupby(["match_id", "innings"], dropna=False)["_runs"]
        .sum()
    )
    checks["provisional_innings_totals"] = {
        "available": int(len(innings_totals)),
        "status": "provisional only; source run semantics are unconfirmed",
    }

    revised_target = _numeric(matches["revised_target"])
    revised_overs_columns = ["first_inn_revised_overs", "second_inn_revised_overs"]
    revised_overs = (
        pd.concat(
            [_numeric(matches[column]) for column in revised_overs_columns],
            axis=1,
        )
        .notna()
        .any(axis=1)
    )
    revised_any = revised_target.notna() | revised_overs
    checks["revised_target_coverage"] = {
        "revised_target_rows": int(revised_target.notna().sum()),
        "revised_overs_rows": int(revised_overs.sum()),
        "any_revised_rows": int(revised_any.sum()),
        "target_timing_reconstructible": config.scoring.target_timing_reconstructible,
    }
    if revised_any.any():
        add(
            "REVISED_TARGETS_EXCLUDED",
            "warning",
            "Matches with revised targets/overs are excluded from the primary model "
            "unless effective target timing is verified.",
            matches=int(revised_any.sum()),
        )

    checks["winner_coverage"] = {
        "rows": int(len(matches)),
        "non_null_winner": int(matches["win_team_id"].notna().sum()),
        "nonblank_result": int(matches["result"].notna().sum()),
    }

    checks["team_mapping_coverage"] = {
        "mapping_comp_team_unique": bool(not player_map.duplicated(["comp_id", "team_id"]).any()),
        "team_lookup_comp_team_unique": bool(not teams.duplicated(["comp_id", "team_id"]).any()),
        "team_mapping_to_teams": join_coverage(
            player_map, teams, ["comp_id", "team_id"], ["comp_id", "team_id"]
        ),
    }
    match_comp = matches[["match_id", "comp_id"]].drop_duplicates()
    playing_join = lineup.merge(match_comp, on="match_id", how="left", validate="many_to_one")
    mapping_keys = player_map[["comp_id", "team_id", "player_id"]].drop_duplicates()
    checks["playing_eleven_duplicate_keys"] = int(
        lineup.duplicated(["match_id", "team_id", "player_id"], keep=False).sum()
    )
    checks["playing_eleven_player_mapping"] = join_coverage(
        playing_join,
        mapping_keys,
        ["comp_id", "team_id", "player_id"],
        ["comp_id", "team_id", "player_id"],
    )
    if checks["playing_eleven_duplicate_keys"]:
        add(
            "DUPLICATE_PLAYING_ELEVEN_KEYS",
            "warning",
            "Duplicate playing-eleven match/team/player keys exist; rows were retained.",
            rows_in_duplicate_groups=checks["playing_eleven_duplicate_keys"],
        )
    if checks["playing_eleven_player_mapping"]["orphan_rows"]:
        add(
            "PLAYING_ELEVEN_MAPPING_ORPHANS",
            "warning",
            "Some playing-eleven rows lack a competition/team/player mapping.",
            **checks["playing_eleven_player_mapping"],
        )

    checks["player_mapping_key_unique"] = {
        "competition_team_player": not player_map.duplicated(
            ["comp_id", "team_id", "player_id"]
        ).any(),
        "competition_player": not player_map.duplicated(["comp_id", "player_id"]).any(),
    }
    checks["innings_total_reconciliation"] = {
        "result": "not fully verifiable",
        "reason": "No explicit innings totals are supplied; runs semantics are unconfirmed.",
        "matches_with_two_innings": int(checks["matches_with_multiple_innings"]),
    }

    status = (
        "BLOCKED" if any(item.severity == "blocking" for item in findings) else "PASS_WITH_WARNINGS"
    )
    if not findings:
        status = "PASS"
    return AuditResult(
        status=status,
        findings=findings,
        tables=tables,
        checks=checks,
        schemas=schemas,
    )
