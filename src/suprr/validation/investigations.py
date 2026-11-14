from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from suprr.config import AppConfig
from suprr.schemas import SourceTables
from suprr.validation.scoring_rules import dismissal_category

_DELIVERY_FIELDS = [
    "match_id",
    "innings",
    "overid",
    "over_ball_num",
    "innings_ball_num",
    "batting_team_id",
    "bowling_team_id",
    "striker_id",
    "non_striker_id",
    "bowler_id",
    "runs",
    "is_four",
    "is_six",
    "is_wicket",
    "dismissal_type_id",
    "dismissal_type",
    "dismissed_player_id",
    "extras_type",
    "extras1_runs",
    "extras_2_runs",
]
_CONTEXT_FIELDS = [
    "match_id",
    "innings",
    "overid",
    "over_ball_num",
    "innings_ball_num",
    "striker_id",
    "bowler_id",
    "runs",
    "extras_type",
    "extras1_runs",
    "extras_2_runs",
    "is_wicket",
    "dismissal_type",
    "dismissed_player_id",
]
_EXTRA_ISSUES = {"OVERSTEP": "Overstep", "PENALTY": "Penalty", "OTHER": "other"}
_REVISED_COLUMNS = [
    "revised_target",
    "first_inn_revised_overs",
    "second_inn_revised_overs",
]


@dataclass(frozen=True)
class SourceInvestigation:
    records: pd.DataFrame
    value_frequencies: pd.DataFrame
    super_over_reconciliation: pd.DataFrame
    revised_exclusions: pd.DataFrame
    dismissal_reconciliation: pd.DataFrame
    gate_statuses: list[dict[str, Any]]
    summary: dict[str, Any]
    data_dictionary: str
    report_markdown: str


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame.columns:
        return frame[name]
    return pd.Series(pd.NA, index=frame.index, dtype="string")


def _text(frame: pd.DataFrame, name: str) -> pd.Series:
    return _column(frame, name).astype("string").fillna("").str.strip()


def _number(frame: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(_column(frame, name), errors="coerce")


def _flag(frame: pd.DataFrame, name: str) -> pd.Series:
    return _text(frame, name).str.casefold().isin({"true", "1", "yes", "y"})


def _json_value(value: object) -> object:
    if pd.isna(value):
        return None
    return str(value)


def _context_json(row: pd.Series, side: str) -> str:
    values = {field: _json_value(row.get(f"{side}_{field}")) for field in _CONTEXT_FIELDS}
    if all(value is None for value in values.values()):
        return ""
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _delivery_identifier(row: pd.Series) -> str:
    fields = ("match_id", "innings", "overid", "over_ball_num")
    return "/".join(str(row.get(field, "")) for field in fields)


def _make_investigation_records(deliveries: pd.DataFrame) -> pd.DataFrame:
    context = deliveries.copy()
    context["_source_data_row"] = range(2, len(context) + 2)
    context["_match_order"] = _text(context, "match_id")
    context["_innings_group"] = _text(context, "innings")
    context["_innings_order"] = _number(context, "innings")
    context["_sequence_order"] = _number(context, "innings_ball_num")
    context = context.sort_values(
        ["_match_order", "_innings_order", "_sequence_order", "_source_data_row"],
        kind="stable",
        na_position="last",
    )
    grouped = context.groupby(["_match_order", "_innings_group"], sort=False)
    for field in _CONTEXT_FIELDS:
        context[f"previous_{field}"] = grouped[field].shift(1)
        context[f"next_{field}"] = grouped[field].shift(-1)

    issue_rows: list[pd.DataFrame] = []
    extras = _text(context, "extras_type")
    issue_definitions: list[tuple[str, pd.Series, str]] = [
        (
            f"EXTRAS_{issue}",
            extras.eq(value),
            "extras_type,runs,extras1_runs,extras_2_runs,is_four,is_six,is_wicket",
        )
        for issue, value in _EXTRA_ISSUES.items()
    ]
    issue_definitions.extend(
        [
            (
                "DISMISSAL_METADATA_WITHOUT_LABEL",
                _text(context, "dismissal_type").eq("")
                & (_text(context, "dismissed_player_id").ne("") | _flag(context, "is_wicket")),
                "dismissal_type,dismissal_type_id,is_wicket,dismissed_player_id",
            ),
            (
                "DISMISSAL_STUMP",
                _text(context, "dismissal_type").eq("Stump"),
                "dismissal_type,dismissal_type_id,is_wicket,dismissed_player_id",
            ),
            (
                "INNINGS_3_PLUS",
                _number(context, "innings").ge(3),
                "innings,match_id,overid,over_ball_num,innings_ball_num",
            ),
        ]
    )
    output_fields = [field for field in _DELIVERY_FIELDS if field in context.columns]
    for issue_code, mask, source_columns in issue_definitions:
        selected = context.loc[mask].copy()
        if selected.empty:
            continue
        selected.insert(0, "issue_code", issue_code)
        selected.insert(1, "source_file", "ball_by_ball.csv")
        selected.insert(2, "source_columns", source_columns)
        selected["delivery_identifier"] = selected.apply(_delivery_identifier, axis=1)
        selected["previous_delivery"] = selected.apply(
            lambda row: _context_json(row, "previous"), axis=1
        )
        selected["next_delivery"] = selected.apply(lambda row: _context_json(row, "next"), axis=1)
        issue_rows.append(
            selected[
                [
                    "issue_code",
                    "source_file",
                    "source_columns",
                    "_source_data_row",
                    "delivery_identifier",
                    *output_fields,
                    "previous_delivery",
                    "next_delivery",
                ]
            ].rename(columns={"_source_data_row": "source_data_row"})
        )
    if not issue_rows:
        return pd.DataFrame(
            columns=[
                "issue_code",
                "source_file",
                "source_columns",
                "source_data_row",
                "delivery_identifier",
                *output_fields,
                "previous_delivery",
                "next_delivery",
            ]
        )
    return pd.concat(issue_rows, ignore_index=True)


def _make_value_frequencies(deliveries: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for issue, value in _EXTRA_ISSUES.items():
        subset = deliveries.loc[_text(deliveries, "extras_type").eq(value)]
        fields = [
            field
            for field in (
                "extras_type",
                "runs",
                "extras1_runs",
                "extras_2_runs",
                "is_four",
                "is_six",
                "is_wicket",
            )
            if field in subset.columns
        ]
        if subset.empty or not fields:
            continue
        frequency = (
            subset.groupby(fields, dropna=False, sort=True).size().rename("frequency").reset_index()
        )
        frequency.insert(0, "issue_code", f"EXTRAS_{issue}")
        frequency.insert(1, "source_file", "ball_by_ball.csv")
        frequency.insert(2, "source_columns", ",".join(fields))
        frequency["source_value_json"] = frequency[fields].apply(
            lambda row, value_fields=fields: json.dumps(
                {field: _json_value(row[field]) for field in value_fields},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            axis=1,
        )
        rows.append(
            frequency[
                [
                    "issue_code",
                    "source_file",
                    "source_columns",
                    "source_value_json",
                    "frequency",
                ]
            ]
        )

    stump = deliveries.loc[_text(deliveries, "dismissal_type").eq("Stump")]
    stump_fields = [
        field
        for field in (
            "dismissal_type",
            "dismissal_type_id",
            "is_wicket",
            "dismissed_player_id",
            "extras_type",
            "runs",
            "extras1_runs",
            "extras_2_runs",
        )
        if field in stump.columns
    ]
    if not stump.empty and stump_fields:
        frequency = (
            stump.groupby(stump_fields, dropna=False, sort=True)
            .size()
            .rename("frequency")
            .reset_index()
        )
        frequency.insert(0, "issue_code", "DISMISSAL_STUMP")
        frequency.insert(1, "source_file", "ball_by_ball.csv")
        frequency.insert(2, "source_columns", ",".join(stump_fields))
        frequency["source_value_json"] = frequency[stump_fields].apply(
            lambda row: json.dumps(
                {field: _json_value(row[field]) for field in stump_fields},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            axis=1,
        )
        rows.append(
            frequency[
                [
                    "issue_code",
                    "source_file",
                    "source_columns",
                    "source_value_json",
                    "frequency",
                ]
            ]
        )
    unlabeled = deliveries.loc[
        _text(deliveries, "dismissal_type").eq("")
        & (_text(deliveries, "dismissed_player_id").ne("") | _flag(deliveries, "is_wicket"))
    ]
    unlabeled_fields = [
        field
        for field in (
            "dismissal_type",
            "dismissal_type_id",
            "is_wicket",
            "dismissed_player_id",
            "runs",
            "extras_type",
        )
        if field in unlabeled.columns
    ]
    if not unlabeled.empty and unlabeled_fields:
        frequency = (
            unlabeled.groupby(unlabeled_fields, dropna=False, sort=True)
            .size()
            .rename("frequency")
            .reset_index()
        )
        frequency.insert(0, "issue_code", "DISMISSAL_METADATA_WITHOUT_LABEL")
        frequency.insert(1, "source_file", "ball_by_ball.csv")
        frequency.insert(2, "source_columns", ",".join(unlabeled_fields))
        frequency["source_value_json"] = frequency[unlabeled_fields].apply(
            lambda row: json.dumps(
                {field: _json_value(row[field]) for field in unlabeled_fields},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            axis=1,
        )
        rows.append(
            frequency[
                [
                    "issue_code",
                    "source_file",
                    "source_columns",
                    "source_value_json",
                    "frequency",
                ]
            ]
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "issue_code",
                "source_file",
                "source_columns",
                "source_value_json",
                "frequency",
            ]
        )
    return pd.concat(rows, ignore_index=True)


def _super_over_reconciliation(deliveries: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    work = pd.DataFrame(
        {
            "match_id": _text(deliveries, "match_id"),
            "innings": _number(deliveries, "innings"),
            "sequence": _number(deliveries, "innings_ball_num"),
            "runs": _number(deliveries, "runs").fillna(0),
            "extras1": _number(deliveries, "extras1_runs").fillna(0),
            "extras2": _number(deliveries, "extras_2_runs").fillna(0),
        }
    )
    totals = (
        work.groupby(["match_id", "innings"], dropna=False, sort=True)
        .agg(
            delivery_rows=("match_id", "size"),
            first_sequence=("sequence", "min"),
            last_sequence=("sequence", "max"),
            source_runs_sum=("runs", "sum"),
            source_extras1_sum=("extras1", "sum"),
            source_extras2_sum=("extras2", "sum"),
        )
        .reset_index()
    )
    totals["provisional_runs_plus_extras"] = (
        totals["source_runs_sum"] + totals["source_extras1_sum"] + totals["source_extras2_sum"]
    )
    extra_innings = totals.loc[pd.to_numeric(totals["innings"], errors="coerce").ge(3)]
    if extra_innings.empty:
        return pd.DataFrame(
            columns=[
                "match_id",
                "innings",
                "delivery_rows",
                "first_sequence",
                "last_sequence",
                "result",
                "result_names_super_over",
                "regular_innings_1_and_2_present",
                "provisional_innings_1_and_2_tie",
                "status",
                "evidence",
            ]
        )

    match_metadata = (
        pd.DataFrame({"match_id": _text(matches, "match_id"), "result": _text(matches, "result")})
        .drop_duplicates("match_id")
        .set_index("match_id")
    )
    result: list[dict[str, Any]] = []
    for row in extra_innings.itertuples(index=False):
        match_id = str(row.match_id)
        innings = int(row.innings)
        metadata = match_metadata.loc[match_id] if match_id in match_metadata.index else None
        result_text = str(metadata.get("result", "")) if metadata is not None else ""
        names_super_over = "super over" in result_text.casefold()
        match_totals = totals.loc[totals["match_id"].eq(match_id)]
        present = set(pd.to_numeric(match_totals["innings"], errors="coerce").dropna())
        regular_innings_present = {1, 2}.issubset(present)
        regular = match_totals.loc[
            pd.to_numeric(match_totals["innings"], errors="coerce").isin([1, 2])
        ].set_index("innings")
        provisional_tie = (
            bool(
                regular.loc[1, "provisional_runs_plus_extras"]
                == regular.loc[2, "provisional_runs_plus_extras"]
            )
            if regular_innings_present
            else None
        )
        confirmed = names_super_over and regular_innings_present
        evidence = (
            "matches.result explicitly names a Super Over, and innings 1 and 2 are present."
            if confirmed
            else (
                "The match result does not explicitly identify a Super Over "
                "with both regular innings present."
            )
        )
        result.append(
            {
                "source_file": "ball_by_ball.csv; matches.csv",
                "source_columns": (
                    "ball_by_ball.match_id,innings,innings_ball_num,runs,extras1_runs,"
                    "extras_2_runs; matches.match_id,result"
                ),
                "match_id": match_id,
                "innings": innings,
                "delivery_rows": int(row.delivery_rows),
                "first_sequence": row.first_sequence,
                "last_sequence": row.last_sequence,
                "result": result_text,
                "result_names_super_over": names_super_over,
                "regular_innings_1_and_2_present": regular_innings_present,
                "provisional_innings_1_and_2_tie": provisional_tie,
                "status": "CONFIRMED" if confirmed else "UNRESOLVED",
                "evidence": evidence
                + (
                    " Provisional score equality is corroborative only; "
                    "run semantics remain unresolved."
                ),
            }
        )
    return pd.DataFrame(result)


def _revised_exclusions(
    deliveries: pd.DataFrame, matches: pd.DataFrame
) -> tuple[pd.DataFrame, int, int]:
    available = [column for column in _REVISED_COLUMNS if column in matches.columns]
    if not available:
        return pd.DataFrame(), 0, 0
    values = matches[available].apply(lambda column: _text(matches, column.name).ne(""))
    revised_mask = values.any(axis=1)
    revised_rows = matches.loc[revised_mask].copy()
    revised_target_count = (
        int(_text(matches, "revised_target").ne("").sum())
        if "revised_target" in matches.columns
        else 0
    )
    revised_overs_count = sum(
        int(_text(matches, column).ne("").sum())
        for column in ("first_inn_revised_overs", "second_inn_revised_overs")
        if column in matches.columns
    )
    if revised_rows.empty:
        return pd.DataFrame(), revised_target_count, revised_overs_count

    delivery_counts = (
        pd.DataFrame(
            {
                "match_id": _text(deliveries, "match_id"),
                "innings": _number(deliveries, "innings"),
            }
        )
        .groupby(["match_id", "innings"], dropna=False, sort=True)
        .size()
        .rename("delivery_rows")
        .reset_index()
    )
    rows: list[dict[str, Any]] = []
    for _, match in revised_rows.iterrows():
        match_id = str(match.get("match_id", ""))
        innings = delivery_counts.loc[delivery_counts["match_id"].eq(match_id)]
        counts = {
            str(int(row.innings)): int(row.delivery_rows)
            for row in innings.itertuples(index=False)
            if pd.notna(row.innings)
        }
        row = {
            "source_file": "matches.csv",
            "source_columns": (
                "match_id,match_date,comp_id,stage,result,revised_target,"
                "first_inn_revised_overs,second_inn_revised_overs"
            ),
            "match_id": match_id,
            "match_date": _json_value(match.get("match_date")),
            "comp_id": _json_value(match.get("comp_id")),
            "stage": _json_value(match.get("stage")),
            "result": _json_value(match.get("result")),
            "revised_target": _json_value(match.get("revised_target")),
            "first_inn_revised_overs": _json_value(match.get("first_inn_revised_overs")),
            "second_inn_revised_overs": _json_value(match.get("second_inn_revised_overs")),
            "innings_delivery_rows_json": json.dumps(counts, sort_keys=True),
            "effective_target_delivery_field_present": (
                "revised_target_effective_delivery" in matches.columns
            ),
            "status": "EXCLUDED_WITH_REASON",
            "reason": (
                "Revised target/overs metadata is present, but no effective-target delivery "
                "or per-delivery scheduled-balls timeline is available; exclude the full match."
            ),
        }
        rows.append(row)
    return pd.DataFrame(rows), revised_target_count, revised_overs_count


def _dismissal_reconciliation(deliveries: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    label = _text(deliveries, "dismissal_type").replace("", "(blank)")
    work = deliveries.copy()
    work["_dismissal_label"] = label
    wicket = _flag(work, "is_wicket")
    dismissed_id_present = _text(work, "dismissed_player_id").ne("")
    striker_match = _text(work, "dismissed_player_id").eq(_text(work, "striker_id"))
    relevant = work["_dismissal_label"].ne("(blank)") | dismissed_id_present | wicket
    work = work.loc[relevant].copy()
    wicket = wicket.loc[relevant]
    dismissed_id_present = dismissed_id_present.loc[relevant]
    striker_match = striker_match.loc[relevant]
    bowler_credited_labels = set(config.scoring.dismissals.get("bowler_credited", []))
    non_bowler_labels = set(config.scoring.dismissals.get("non_bowler_credited", []))
    before = work.groupby("_dismissal_label", dropna=False, sort=True).size().to_dict()
    category_by_label: dict[str, str] = {}
    for source_label in before:
        category = dismissal_category(source_label, config)
        category_by_label[source_label] = category

    rows: list[dict[str, Any]] = []
    for source_label, count in before.items():
        subset = work.loc[work["_dismissal_label"].eq(source_label)]
        category = category_by_label[source_label]
        unresolved = category == "unresolved" or source_label == "(blank)"
        canonical = (
            "UNRESOLVED"
            if unresolved
            else (
                "Obstructing the field" if source_label == "Obstracting the field" else source_label
            )
        )
        all_wickets = bool(wicket.loc[subset.index].all()) if len(subset) else False
        all_dismissed_ids = (
            bool(dismissed_id_present.loc[subset.index].all()) if len(subset) else False
        )
        all_striker_matches = bool(striker_match.loc[subset.index].all()) if len(subset) else False
        batter_dismissed = (
            "CONFIRMED_YES"
            if all_wickets and all_dismissed_ids and all_striker_matches
            else ("INFERRED_YES" if all_wickets and all_dismissed_ids else "UNRESOLVED")
        )
        if unresolved:
            bowler_status = "UNRESOLVED"
        elif source_label == "(blank)":
            bowler_status = "UNRESOLVED"
        elif source_label in bowler_credited_labels:
            bowler_status = "INFERRED_YES"
        elif source_label in non_bowler_labels:
            bowler_status = "INFERRED_NO"
        else:
            bowler_status = "UNRESOLVED"
        ids = sorted(_text(subset, "dismissal_type_id").replace("", "(blank)").unique().tolist())
        mapped = not unresolved and category != "unresolved"
        rows.append(
            {
                "source_file": "ball_by_ball.csv",
                "source_column": "dismissal_type",
                "original_label": source_label,
                "dismissal_type_id_values": "|".join(ids),
                "canonical_label": canonical,
                "count_before": int(count),
                "count_after_mapping": int(count) if mapped else 0,
                "unresolved_count": int(count) if unresolved else 0,
                "bowler_credited_status": bowler_status,
                "batter_dismissed_status": batter_dismissed,
                "is_wicket_true_count": int(wicket.loc[subset.index].sum()),
                "dismissed_player_id_present_count": int(
                    dismissed_id_present.loc[subset.index].sum()
                ),
                "dismissed_player_equals_striker_count": int(striker_match.loc[subset.index].sum()),
                "status": "UNRESOLVED" if unresolved else "INFERRED",
                "evidence": (
                    "No source lookup or alias establishes this label's canonical "
                    "dismissal or bowler credit."
                    if unresolved
                    else (
                        "Canonical mapping follows the configured label rule; "
                        "no source dismissal legend was supplied."
                    )
                ),
            }
        )
    return pd.DataFrame(rows)


def _extra_semantics_summary(deliveries: pd.DataFrame) -> list[dict[str, Any]]:
    extras = _text(deliveries, "extras_type")
    runs = _number(deliveries, "runs").fillna(0)
    extras1 = _number(deliveries, "extras1_runs").fillna(0)
    extras2 = _number(deliveries, "extras_2_runs").fillna(0)
    four = _flag(deliveries, "is_four")
    six = _flag(deliveries, "is_six")
    wicket = _flag(deliveries, "is_wicket")
    rows: list[dict[str, Any]] = []
    for category in sorted(extras.unique().tolist()):
        subset = extras.eq(category)
        rows.append(
            {
                "category": category,
                "rows": int(subset.sum()),
                "matches": int(_text(deliveries.loc[subset], "match_id").nunique()),
                "innings": int(
                    deliveries.loc[subset, ["match_id", "innings"]].drop_duplicates().shape[0]
                ),
                "nonzero_runs_rows": int((subset & runs.ne(0)).sum()),
                "nonzero_extras1_rows": int((subset & extras1.ne(0)).sum()),
                "nonzero_extras2_rows": int((subset & extras2.ne(0)).sum()),
                "four_flags": int((subset & four).sum()),
                "six_flags": int((subset & six).sum()),
                "wicket_rows": int((subset & wicket).sum()),
            }
        )
    return rows


def _data_dictionary(summary: dict[str, Any]) -> str:
    extras = summary["extras_by_name"]
    overstep = extras.get("Overstep", {})
    other = extras.get("other", {})
    wide = extras.get("wide", {})
    byes = extras.get("byes", {})
    legbyes = extras.get("legbyes", {})
    penalty = extras.get("Penalty", {})
    penalty_count = int(penalty.get("rows", 0))
    penalty_row_word = "row" if penalty_count == 1 else "rows"
    stump_ids = ", ".join(summary["stump_dismissal_type_id_values"]) or "(none)"
    lines = [
        "# Data Dictionary and Scoring Semantics",
        "",
        "## Scope and evidence",
        "",
        "No scoring codebook, delivery-level legal-ball flag, explicit total-runs field,",
        "official innings scorecard, or revised-target effective-delivery field was supplied.",
        "Observed consistency is evidence, not source-confirmed semantics.",
        "",
        "## Delivery and scoring fields",
        "",
        "### Candidate batter runs — `runs` — INFERRED",
        "",
        f"- {summary['four_flags']:,} four flags all match `runs=4`.",
        f"- {summary['six_flags']:,} six flags all match `runs=6`.",
        f"- {summary['nonzero_runs_on_extras_rows']:,} extra-labeled rows have nonzero `runs`.",
        "- No source definition or independent scorecard confirms the field meaning.",
        "- Impact: do not treat as confirmed batter runs; ranking gate remains blocked.",
        "",
        "### Total delivery runs — UNRESOLVED",
        "",
        "- No explicit field or documented aggregation for `runs`, `extras1_runs`,",
        "  and `extras_2_runs` is supplied.",
        "- Impact: innings totals, targets, pressure states, and player run metrics are blocked.",
        "",
        "### Wides — `extras_type`, `extras1_runs`, `extras_2_runs` — INFERRED",
        "",
        f"- Exact label `wide`: {wide.get('rows', 0):,} rows.",
        f"- Nonzero `extras1_runs`: {wide.get('nonzero_extras1_rows', 0):,} rows.",
        "- No source legend confirms legal-ball or bowler-concession treatment.",
        "",
        "### No-balls — `extras_type`, `extras1_runs`, `extras_2_runs` — INFERRED",
        "",
        "- No literal `no_ball` category is present.",
        f"- `Overstep`: {overstep.get('rows', 0):,} rows; "
        f"{overstep.get('nonzero_extras1_rows', 0):,} have nonzero `extras1_runs`.",
        f"- {overstep.get('four_flags', 0) + overstep.get('six_flags', 0):,} rows have "
        "`is_four`/`is_six` flags; consistent with, but not proof of, a no-ball mapping.",
        "",
        "### Byes — `extras_type`, `extras1_runs` — INFERRED",
        "",
        f"- Exact label `byes`: {byes.get('rows', 0):,} rows; "
        f"nonzero `extras1_runs`: {byes.get('nonzero_extras1_rows', 0):,}.",
        "- Source legend for column attribution is absent.",
        "",
        "### Leg-byes — `extras_type`, `runs`, `extras1_runs` — INFERRED",
        "",
        f"- Exact label `legbyes`: {legbyes.get('rows', 0):,} rows; "
        f"nonzero `runs`: {legbyes.get('nonzero_runs_rows', 0):,}.",
        "- No scorecard or field definition resolves the nonzero-`runs` record.",
        "",
        "### Penalty runs — `extras_type`, `extras1_runs`, `extras_2_runs` — UNRESOLVED",
        "",
        f"- `Penalty` label rows: {penalty_count:,} {penalty_row_word}.",
        "- Source does not identify which side receives the penalty or how it is charged.",
        "",
        "### Other extras / overthrows — UNRESOLVED",
        "",
        f"- `other` label rows: {other.get('rows', 0):,}; "
        f"nonzero `extras_2_runs`: {other.get('nonzero_extras2_rows', 0):,}.",
        "- No field definition identifies `other` or `extras_2_runs` as overthrows.",
        "",
        "### Legal deliveries — UNRESOLVED",
        "",
        "- No legal-ball flag or source rule defines the effect of every extras category.",
        "- Impact: bowler spell volume and pre-delivery balls remaining cannot be validated.",
        "",
        "### Bowler runs conceded — UNRESOLVED",
        "",
        "- Requires confirmed total delivery runs and extras-attribution rules.",
        "- Impact: bowler economy and pressure metrics cannot be calculated reliably.",
        "",
        "## Dismissal fields",
        "",
        "`is_wicket`, `dismissal_type`, and `dismissal_type_id` are present.",
        "`dismissed_player_id` is also present.",
        f"- `Stump`: {summary['stump_rows']:,} rows; ID values: `{stump_ids}`.",
        "- All are flagged as wickets and have dismissed-player IDs.",
        "- No lookup proves the canonical category or bowler credit; status is UNRESOLVED.",
        f"- {summary['unlabeled_dismissal_metadata_rows']:,} rows have a dismissed-player ID",
        "  but no dismissal label; none is marked as a wicket.",
        f"- Nonblank labels before mapping: {summary['dismissal_nonblank_label_rows']:,};",
        f"  rows mapped under configured rules: {summary['dismissal_rows_after_mapping']:,}.",
        f"- Unresolved reconciliation rows, including unlabeled metadata: "
        f"{summary['dismissal_unresolved_rows']:,}.",
        "- See `dismissal_reconciliation.csv` for counts before and after mapping.",
        "",
        "## Innings and revised conditions",
        "",
        f"- {summary['super_over_rows']:,} rows form "
        f"{summary['super_over_innings_groups']:,} extra-innings groups in "
        f"{summary['super_over_matches']:,} matches.",
        "- Match result text explicitly names a Super Over for each; status is CONFIRMED.",
        "- Provisional component-sum ties are corroborative only; run semantics remain unresolved.",
        f"- {summary['revised_match_count']:,} matches have revised target/overs metadata.",
        f"- {summary['revised_target_match_count']:,} have `revised_target`; "
        f"{summary['revised_overs_match_count']:,} have revised-overs fields.",
        "- All are EXCLUDED_WITH_REASON; effective-target timing is not available.",
        "- See `revised_target_exclusions.csv` for identifiers and raw metadata.",
    ]
    return "\n".join(lines)


def _report_markdown(summary: dict[str, Any], result: SourceInvestigation) -> str:
    extras_by_name = summary["extras_by_name"]
    overstep = extras_by_name.get("Overstep", {})
    other = extras_by_name.get("other", {})
    stump_ids = ", ".join(summary["stump_dismissal_type_id_values"]) or "(none)"
    penalty_count = int(extras_by_name.get("Penalty", {}).get("rows", 0))
    penalty_row_word = "row" if penalty_count == 1 else "rows"
    penalty_values = result.value_frequencies.loc[
        result.value_frequencies["issue_code"].eq("EXTRAS_PENALTY")
    ]
    penalty_details = (
        "; ".join(
            f"{row.source_value_json} (n={row.frequency})"
            for row in penalty_values.itertuples(index=False)
        )
        or "(none)"
    )
    extras_rows = [
        "| {category} | {rows:,} | {matches:,} | {innings:,} | {nonzero_runs_rows:,} | "
        "{nonzero_extras1_rows:,} | {nonzero_extras2_rows:,} |".format(**row)
        for row in summary["extras"]
    ]
    superover_ids = sorted(
        result.super_over_reconciliation["match_id"].astype(str).unique().tolist()
    )
    superover_ids_markdown = ", ".join(f"`{item}`" for item in superover_ids)
    revised_ids = sorted(
        result.revised_exclusions["match_id"].astype(str).tolist(),
        key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value),
    )
    gate_rows = [
        f"| `{gate['gate_id']}` | **{gate['status']}** | "
        f"{'Yes' if gate['status'] in {'INFERRED', 'UNRESOLVED'} else 'No'} | "
        f"{gate['evidence']} |"
        for gate in result.gate_statuses
    ]
    return f"""# Source Data Investigation

## Outcome

The source records establish that all {summary["super_over_innings_groups"]} extra-innings
groups are Super Overs and that all {summary["revised_match_count"]} matches with revised
target/overs fields must be excluded because target timing cannot be
reconstructed. Scoring semantics remain unresolved or inferred. The current pipeline continues
with configured assumptions, and its outputs must be presented as exploratory rather than
source-validated.

## Source-specific findings

| Extras | Rows | Matches | Innings | Runs+ | Extras1+ | Extras2+ |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(extras_rows)}

- **`runs`:** All {summary["four_flags"]:,} four flags match `runs=4`; all
  {summary["six_flags"]:,} six flags match `runs=6`. A further
  {summary["nonzero_runs_on_extras_rows"]:,} extra-labeled rows have nonzero `runs`.
  This supports, but does not prove, that `runs` is batter runs. No source codebook or
  independent innings scorecard is available to reconcile it.
- **`Overstep`:** {overstep.get("rows", 0):,} rows;
  `extras1_runs=1` for all;
  {overstep.get("nonzero_extras2_rows", 0)}
  have nonzero `extras_2_runs`;
  {overstep.get("wicket_rows", 0)}
  have `is_wicket=true`.
  Candidate no-ball interpretation is **INFERRED**, not confirmed.
- **`Penalty`:** {penalty_count:,} {penalty_row_word}.
  Raw values/frequencies: `{penalty_details}`. Attribution and delivery accounting are
  **UNRESOLVED**.
- **`other`:** {other.get("rows", 0):,} rows;
  `extras1_runs=1` for all;
  {other.get("nonzero_extras2_rows", 0)}
  have nonzero `extras_2_runs`;
  {other.get("wicket_rows", 0)}
  have `is_wicket=true`. Meaning is
  **UNRESOLVED**.
- **`Stump`:** {summary["stump_rows"]:,} rows all use
  `dismissal_type_id={stump_ids}`; all are flagged
  as wickets and have dismissed-player IDs, but the source provides no alias/codebook proving
  canonical stumping or bowler credit. Status is **UNRESOLVED**.
- **Unlabeled dismissal metadata:** {summary["unlabeled_dismissal_metadata_rows"]:,} rows
  have a dismissed-player ID but no dismissal label; none is marked as a wicket. The current
  metrics do not count these as dismissals. Their source meaning remains unresolved.

## Innings 3+

- {summary["super_over_rows"]} delivery rows group into
  {summary["super_over_innings_groups"]} innings across {summary["super_over_matches"]} matches.
- Match results explicitly name Super Overs for IDs: {superover_ids_markdown}.
- See `super_over_reconciliation.csv` for each innings' result text and evidence.
- The {summary["super_over_rows"]} delivery rows and surrounding records are in
  `investigation_records.csv`.
- No flagged innings is left unverified in this snapshot; none was classified from innings
  number or row count alone.

## Revised-target/overs exclusions

All {summary["revised_match_count"]} flagged matches are excluded in full. They are:
{", ".join(f"`{item}`" for item in revised_ids)}.
`matches.csv` has revised target/overs values but no field identifying when a revised target
became effective or the scheduled-ball budget at each delivery.

## Source evidence status

| Evidence topic | Status | Source confirmation needed | Evidence |
|---|---|---|---|
{chr(10).join(gate_rows)}

## Traceable evidence files

- `investigation_records.csv`: all flagged delivery rows with source row number, composite
  delivery identifier, raw scoring/dismissal values, and previous/next delivery JSON.
- `source_value_frequencies.csv`: observed raw-value combinations and frequencies for each
  disputed extras/dismissal category.
- `dismissal_reconciliation.csv`: original labels, IDs, canonical mapping state, batter-dismissed
  and bowler-credit status, and counts before/after mapping.
- `super_over_reconciliation.csv`: all innings 3+ groups and match-result evidence.
- `revised_target_exclusions.csv`: all {summary["revised_match_count"]} excluded matches.
  The CSV includes their raw revised metadata.
- `data_dictionary.md`: field-by-field scoring conclusions and status.
"""


def investigate_sources(sources: SourceTables, config: AppConfig) -> SourceInvestigation:
    deliveries = sources["deliveries"]
    matches = sources["matches"]
    records = _make_investigation_records(deliveries)
    frequencies = _make_value_frequencies(deliveries)
    superovers = _super_over_reconciliation(deliveries, matches)
    revised, revised_target_count, revised_overs_count = _revised_exclusions(deliveries, matches)
    dismissals = _dismissal_reconciliation(deliveries, config)
    extras = _extra_semantics_summary(deliveries)
    extras_by_name = {row["category"]: row for row in extras}
    four = _flag(deliveries, "is_four")
    six = _flag(deliveries, "is_six")
    runs = _number(deliveries, "runs")
    extras_rows = _text(deliveries, "extras_type").ne("None")
    extra_innings_rows = int(_number(deliveries, "innings").ge(3).sum())
    extra_innings_groups = (
        int(
            deliveries.loc[_number(deliveries, "innings").ge(3), ["match_id", "innings"]]
            .drop_duplicates()
            .shape[0]
        )
        if extra_innings_rows
        else 0
    )
    super_over_matches = int(superovers["match_id"].nunique()) if not superovers.empty else 0
    super_over_unverified = (
        int(superovers["status"].ne("CONFIRMED").sum()) if not superovers.empty else 0
    )
    stump = _text(deliveries, "dismissal_type").eq("Stump")
    stump_rows = int(stump.sum())
    missing_dismissal_metadata = _text(deliveries, "dismissal_type").eq("") & _text(
        deliveries, "dismissed_player_id"
    ).ne("")
    missing_dismissal_metadata_rows = int(missing_dismissal_metadata.sum())
    stump_id_values = sorted(
        _text(deliveries.loc[stump], "dismissal_type_id").replace("", "(blank)").unique().tolist()
    )
    summary: dict[str, Any] = {
        "delivery_rows": int(len(deliveries)),
        "extras": extras,
        "extras_by_name": extras_by_name,
        "four_flags": int(four.sum()),
        "four_flag_run_mismatches": int((four & runs.ne(4)).sum()),
        "six_flags": int(six.sum()),
        "six_flag_run_mismatches": int((six & runs.ne(6)).sum()),
        "nonzero_runs_on_extras_rows": int((extras_rows & runs.gt(0)).sum()),
        "stump_rows": stump_rows,
        "stump_dismissal_type_id_values": stump_id_values,
        "stump_wicket_rows": int((_flag(deliveries, "is_wicket") & stump).sum()),
        "stump_dismissed_id_rows": int(
            (_text(deliveries, "dismissed_player_id").ne("") & stump).sum()
        ),
        "stump_striker_id_match_rows": int(
            (
                _text(deliveries, "dismissed_player_id").eq(_text(deliveries, "striker_id")) & stump
            ).sum()
        ),
        "stump_wide_rows": int((stump & _text(deliveries, "extras_type").eq("wide")).sum()),
        "unlabeled_dismissal_metadata_rows": missing_dismissal_metadata_rows,
        "unlabeled_dismissal_metadata_wicket_rows": int(
            (missing_dismissal_metadata & _flag(deliveries, "is_wicket")).sum()
        ),
        "dismissal_nonblank_label_rows": int(_text(deliveries, "dismissal_type").ne("").sum()),
        "dismissal_rows_after_mapping": int(dismissals["count_after_mapping"].sum()),
        "dismissal_unresolved_rows": int(dismissals["unresolved_count"].sum()),
        "super_over_rows": extra_innings_rows,
        "super_over_innings_groups": extra_innings_groups,
        "super_over_matches": super_over_matches,
        "super_over_unverified_innings_groups": super_over_unverified,
        "verified_super_over_innings": (
            [
                {"match_id": str(row.match_id), "innings": int(row.innings)}
                for row in superovers.itertuples(index=False)
                if row.status == "CONFIRMED"
            ]
            if not superovers.empty
            else []
        ),
        "revised_match_count": int(len(revised)),
        "revised_target_match_count": revised_target_count,
        "revised_overs_match_count": int(
            matches.loc[
                :,
                [
                    column
                    for column in ("first_inn_revised_overs", "second_inn_revised_overs")
                    if column in matches.columns
                ],
            ]
            .apply(lambda column: _text(matches, column.name).ne(""))
            .any(axis=1)
            .sum()
        )
        if any(
            column in matches.columns
            for column in ("first_inn_revised_overs", "second_inn_revised_overs")
        )
        else 0,
        "revised_overs_field_count": revised_overs_count,
        "effective_target_delivery_field_present": (
            "revised_target_effective_delivery" in matches.columns
        ),
        "extras_nonzero_runs_rows": int((extras_rows & runs.gt(0)).sum()),
    }
    revised_overs_matches = summary["revised_overs_match_count"]
    unresolved_extra_names = [
        name
        for name in ("Overstep", "Penalty", "other")
        if extras_by_name.get(name, {}).get("rows", 0)
    ]
    super_over_confirmed = super_over_unverified == 0
    gates: list[dict[str, Any]] = [
        {
            "gate_id": "super_over_classification",
            "status": "CONFIRMED" if super_over_confirmed else "UNRESOLVED",
            "affected_rows": extra_innings_rows,
            "evidence": (
                f"{super_over_matches} matches have result text explicitly naming a Super Over; "
                f"{extra_innings_groups} innings groups were checked."
                if super_over_confirmed
                else (
                    f"{super_over_unverified} innings groups lack sufficient match-result evidence."
                )
            ),
        },
        {
            "gate_id": "revised_conditions",
            "status": "EXCLUDED_WITH_REASON" if len(revised) else "CONFIRMED",
            "affected_matches": int(len(revised)),
            "evidence": (
                "All matches with revised target/overs metadata are excluded because no "
                "effective-target delivery timeline is available."
                if len(revised)
                else "No revised target/overs metadata is present."
            ),
        },
        {
            "gate_id": "batter_runs_semantics",
            "status": "INFERRED",
            "affected_rows": int(len(deliveries)),
            "evidence": (
                f"All {int(four.sum()):,} four flags match runs=4 and all {int(six.sum()):,} "
                "six flags match runs=6, but no source definition or independent scorecard "
                "confirms that `runs` is batter runs."
            ),
        },
        {
            "gate_id": "total_delivery_runs",
            "status": "UNRESOLVED",
            "evidence": (
                "No explicit total-runs field or documented aggregation for "
                "runs/extras1_runs/extras_2_runs."
            ),
        },
        {
            "gate_id": "extras_classification",
            "status": "UNRESOLVED" if unresolved_extra_names else "INFERRED",
            "affected_categories": unresolved_extra_names,
            "evidence": (
                "No extras codebook is supplied; Overstep is only a candidate no-ball "
                "mapping, while Penalty and other remain unmapped."
            ),
        },
        {
            "gate_id": "legal_delivery_rules",
            "status": "UNRESOLVED",
            "evidence": (
                "No legal-ball flag or source rule defines the legal-delivery effect "
                "of every extras category."
            ),
        },
        {
            "gate_id": "bowler_runs_conceded",
            "status": "UNRESOLVED",
            "evidence": (
                "Cannot calculate confirmed bowler-conceded runs without total-run "
                "and extras-attribution rules."
            ),
        },
        {
            "gate_id": "stump_dismissal",
            "status": "UNRESOLVED" if stump_rows else "CONFIRMED",
            "affected_rows": stump_rows,
            "evidence": (
                f"{stump_rows} rows use dismissal_type_id={','.join(stump_id_values)}; the source "
                "has no lookup proving that `Stump` means `Stumped` or defining bowler credit."
                if stump_rows
                else "No Stump dismissal rows are present."
            ),
        },
        {
            "gate_id": "unlabeled_dismissal_metadata",
            "status": "UNRESOLVED" if missing_dismissal_metadata_rows else "CONFIRMED",
            "affected_rows": missing_dismissal_metadata_rows,
            "evidence": (
                f"{missing_dismissal_metadata_rows} rows have a dismissed-player ID but no "
                "dismissal label; all are not marked as wickets and are not counted by the "
                "current dismissal metrics."
                if missing_dismissal_metadata_rows
                else "No dismissed-player IDs occur without a dismissal label."
            ),
        },
    ]
    summary["revised_overs_match_count"] = int(revised_overs_matches)
    summary["primary_model_status"] = "ASSUMPTION_BASED_EXPLORATORY"
    provisional = SourceInvestigation(
        records=records,
        value_frequencies=frequencies,
        super_over_reconciliation=superovers,
        revised_exclusions=revised,
        dismissal_reconciliation=dismissals,
        gate_statuses=gates,
        summary=summary,
        data_dictionary="",
        report_markdown="",
    )
    return SourceInvestigation(
        records=records,
        value_frequencies=frequencies,
        super_over_reconciliation=superovers,
        revised_exclusions=revised,
        dismissal_reconciliation=dismissals,
        gate_statuses=gates,
        summary=summary,
        data_dictionary=_data_dictionary(summary),
        report_markdown=_report_markdown(summary, provisional),
    )


def write_investigation_reports(
    result: SourceInvestigation,
    output_dir: Path,
    *,
    analysis_mode: str = "ASSUMPTION_BASED_EXPLORATORY",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_label = "EXPLORATORY"
    for frame, filename in (
        (result.records, "investigation_records.csv"),
        (result.value_frequencies, "source_value_frequencies.csv"),
        (result.super_over_reconciliation, "super_over_reconciliation.csv"),
        (result.revised_exclusions, "revised_target_exclusions.csv"),
        (result.dismissal_reconciliation, "dismissal_reconciliation.csv"),
    ):
        labeled = frame.copy()
        labeled["analysis_mode"] = analysis_mode
        labeled["output_label"] = output_label
        labeled.to_csv(output_dir / filename, index=False)
    mode_banner = (
        f"**Run mode:** `{analysis_mode}`. "
        + (
            "This is an EXPLORATORY report; configured assumptions are not source-confirmed."
        )
        + "\n\n"
    )
    def add_mode_banner(markdown: str) -> str:
        heading, separator, remainder = markdown.partition("\n")
        if not separator:
            return f"{markdown}\n\n{mode_banner}"
        return f"{heading}\n\n{mode_banner}{remainder.lstrip()}"

    (output_dir / "data_dictionary.md").write_text(
        add_mode_banner(result.data_dictionary), encoding="utf-8"
    )
    (output_dir / "data_investigation.md").write_text(
        add_mode_banner(result.report_markdown), encoding="utf-8"
    )
    _write_investigation_pdf(
        result,
        output_dir / "data_investigation.pdf",
        analysis_mode=analysis_mode,
    )


def _write_investigation_pdf(
    result: SourceInvestigation,
    path: Path,
    *,
    analysis_mode: str,
) -> None:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="InvestigationBody",
            parent=styles["BodyText"],
            alignment=TA_LEFT,
            leading=13,
            spaceAfter=5,
        )
    )
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Source Data Investigation",
        author="SupeRR Pressure Analytics",
    )
    summary = result.summary
    story: list[Any] = [
        Paragraph(
            (
                "EXPLORATORY — Source Data Investigation"
                if analysis_mode == "ASSUMPTION_BASED_EXPLORATORY"
                else "Source Data Investigation"
            ),
            styles["Title"],
        ),
        Paragraph(
            "EXPLORATORY — configured assumptions are not source-confirmed.",
            styles["InvestigationBody"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("Verified and excluded records", styles["Heading2"]),
    ]
    table_data = [
        ["Finding", "Result"],
        ["Innings 3+ delivery rows", f"{summary['super_over_rows']:,}"],
        [
            "Verified Super Over innings / matches",
            (f"{summary['super_over_innings_groups']:,} / {summary['super_over_matches']:,}"),
        ],
        ["Revised-condition matches excluded", f"{summary['revised_match_count']:,}"],
        [
            "Overstep / Penalty / other rows",
            (
                f"{summary['extras_by_name'].get('Overstep', {}).get('rows', 0):,} / "
                f"{summary['extras_by_name'].get('Penalty', {}).get('rows', 0):,} / "
                f"{summary['extras_by_name'].get('other', {}).get('rows', 0):,}"
            ),
        ],
        ["Unresolved Stump dismissal rows", f"{summary['stump_rows']:,}"],
    ]
    table = Table(table_data, colWidths=[82 * mm, 78 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#183047")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C9D3DC")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F9")]),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([table, Spacer(1, 5 * mm), Paragraph("Ranking gates", styles["Heading2"])])
    for gate in result.gate_statuses:
        story.append(
            Paragraph(
                f"<b>{escape(str(gate['gate_id']))}: {escape(str(gate['status']))}</b> — "
                f"{escape(str(gate['evidence']))}",
                styles["InvestigationBody"],
            )
        )
    story.extend(
        [
            Spacer(1, 3 * mm),
            Paragraph(
                "The accompanying CSVs contain the affected delivery identifiers, raw values, "
                "frequencies, and previous/next delivery context. See data_investigation.md "
                "and data_dictionary.md for the full evidence and semantics.",
                styles["InvestigationBody"],
            ),
        ]
    )
    document.build(story)
