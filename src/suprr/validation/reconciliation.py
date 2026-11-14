from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from suprr.exports import write_csv
from suprr.schemas import SourceTables


def _source_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series(pd.NA, index=frame.index, dtype="string")


def _numbers(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_source_column(frame, column), errors="coerce")


def _flags(frame: pd.DataFrame, column: str) -> pd.Series:
    return (
        _source_column(frame, column)
        .astype("string")
        .str.strip()
        .str.casefold()
        .isin({"true", "1", "yes", "y"})
    )


def build_reconciliation(
    sources: SourceTables,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    deliveries = sources["deliveries"].copy()
    matches = sources["matches"].copy()
    required = {"match_id", "innings", "striker_id", "bowler_id"}
    missing = sorted(required - set(deliveries.columns))
    if missing:
        raise ValueError(f"Delivery source is missing reconciliation fields: {missing}")
    if "match_id" not in matches.columns:
        raise ValueError("Match source is missing `match_id` for reconciliation.")

    deliveries["match_id"] = deliveries["match_id"].astype("string")
    deliveries["innings"] = deliveries["innings"].astype("string")
    deliveries["_raw_runs"] = _numbers(deliveries, "runs")
    deliveries["_extras1"] = _numbers(deliveries, "extras1_runs")
    deliveries["_extras2"] = _numbers(deliveries, "extras_2_runs")
    deliveries["_candidate_total"] = (
        deliveries["_raw_runs"].fillna(0)
        + deliveries["_extras1"].fillna(0)
        + deliveries["_extras2"].fillna(0)
    )
    deliveries["_wicket_flag"] = _flags(deliveries, "is_wicket").astype("int64")
    innings = (
        deliveries.groupby(["match_id", "innings"], as_index=False, dropna=False)
        .agg(
            delivery_count=("match_id", "size"),
            raw_runs_field_sum=("_raw_runs", "sum"),
            extras1_runs_sum=("_extras1", "sum"),
            extras_2_runs_sum=("_extras2", "sum"),
            additive_total_candidate=("_candidate_total", "sum"),
            raw_is_wicket_flag_count=("_wicket_flag", "sum"),
        )
    )
    matches["match_id"] = matches["match_id"].astype("string")
    metadata_columns = [
        column
        for column in (
            "match_id",
            "result",
            "revised_target",
            "first_inn_revised_overs",
            "second_inn_revised_overs",
        )
        if column in matches.columns
    ]
    metadata = matches[metadata_columns].drop_duplicates("match_id")
    innings = innings.merge(
        metadata,
        on="match_id",
        how="left",
        validate="many_to_one",
    )
    first_totals = innings.loc[innings["innings"].eq("1"), [
        "match_id",
        "additive_total_candidate",
    ]].rename(columns={"additive_total_candidate": "first_innings_total_candidate"})
    innings = innings.merge(
        first_totals,
        on="match_id",
        how="left",
        validate="many_to_one",
    )
    innings["chase_target_candidate"] = (
        innings["first_innings_total_candidate"] + 1
    ).where(innings["innings"].eq("2"))
    innings["independent_scorecard_total"] = pd.NA
    innings["independent_effective_target"] = pd.NA
    innings["score_comparison_status"] = "NOT_COMPARABLE_NO_INDEPENDENT_SCORECARD"
    innings["target_comparison_status"] = "NOT_COMPARABLE_NO_EFFECTIVE_TARGET_TIMELINE"
    innings["interpretation_status"] = "CANDIDATE_COMPONENT_SUM_ONLY"
    innings["notes"] = (
        "`runs + extras1_runs + extras_2_runs` is an arithmetic candidate, not a confirmed "
        "team total. No independent scorecard totals or effective-target delivery timeline "
        "are present in the supplied source files."
    )

    scorecard_rows: list[dict[str, Any]] = []
    for row in innings.itertuples(index=False):
        match_id = str(row.match_id)
        innings_id = str(row.innings)
        for metric, value, status in (
            ("innings_total_candidate", row.additive_total_candidate, "NO_INDEPENDENT_SCORECARD"),
            ("raw_wicket_flag_count", row.raw_is_wicket_flag_count, "NO_INDEPENDENT_SCORECARD"),
            ("extras1_component_sum", row.extras1_runs_sum, "NO_INDEPENDENT_SCORECARD"),
            ("extras2_component_sum", row.extras_2_runs_sum, "NO_INDEPENDENT_SCORECARD"),
        ):
            scorecard_rows.append(
                _scorecard_record(
                    "innings",
                    match_id,
                    innings_id,
                    None,
                    metric,
                    value,
                    status,
                )
            )
        if pd.notna(row.chase_target_candidate):
            scorecard_rows.append(
                _scorecard_record(
                    "innings",
                    match_id,
                    innings_id,
                    None,
                    "chase_target_candidate",
                    row.chase_target_candidate,
                    "NO_EFFECTIVE_TARGET_OR_SCORECARD",
                )
            )

    batter_runs = (
        deliveries.groupby(["match_id", "innings", "striker_id"], as_index=False, dropna=False)
        .agg(raw_runs_field_sum=("_raw_runs", "sum"))
    )
    for row in batter_runs.itertuples(index=False):
        scorecard_rows.append(
            _scorecard_record(
                "batter",
                str(row.match_id),
                str(row.innings),
                str(row.striker_id),
                "raw_runs_field_sum",
                row.raw_runs_field_sum,
                "NO_INDEPENDENT_SCORECARD",
            )
        )

    bowlers = deliveries[["match_id", "innings", "bowler_id"]].drop_duplicates()
    for row in bowlers.itertuples(index=False):
        scorecard_rows.append(
            _scorecard_record(
                "bowler",
                str(row.match_id),
                str(row.innings),
                str(row.bowler_id),
                "bowler_conceded_runs",
                None,
                "NOT_CALCULABLE_SCORING_RULES_UNRESOLVED",
            )
        )
    scorecard = pd.DataFrame(scorecard_rows)
    return innings, scorecard


def _scorecard_record(
    entity_type: str,
    match_id: str,
    innings: str,
    player_id: str | None,
    metric: str,
    candidate_value: object,
    status: str,
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "match_id": match_id,
        "innings": innings,
        "player_id": player_id,
        "metric": metric,
        "delivery_candidate_value": candidate_value,
        "independent_scorecard_value": pd.NA,
        "difference": pd.NA,
        "comparison_status": status,
    }


def _scoring_evidence_markdown(
    sources: SourceTables,
    innings_reconciliation: pd.DataFrame,
    scorecard_reconciliation: pd.DataFrame,
    analysis_mode: str,
) -> str:
    deliveries = sources["deliveries"]
    extras_counts = (
        _source_column(deliveries, "extras_type")
        .astype("string")
        .fillna("(blank)")
        .str.strip()
        .value_counts(dropna=False)
        .sort_index()
    )
    extras_table = "\n".join(
        f"| `{label}` | {int(count):,} |" for label, count in extras_counts.items()
    )
    unresolved_rows = int(
        _source_column(deliveries, "extras_type")
        .astype("string")
        .isin({"Overstep", "Penalty", "other"})
        .sum()
    )
    stump_rows = int(_source_column(deliveries, "dismissal_type").eq("Stump").sum())
    independent_rows = int(
        scorecard_reconciliation["independent_scorecard_value"].notna().sum()
    )
    return f"""# Scoring Semantics Evidence

**Run mode:** `{analysis_mode}`. Exploratory outputs, if permitted, remain assumptions-based
and are not validated results.

## Provenance and source-document search

- The local archive's Windows `Zone.Identifier` records the download endpoint
  `https://unstop.com/api/submissions_case/download/6af458274c1e8_data_pack.zip` and
  referrer `https://unstop.com/competitions/1792758/submission/1673107`.
- The provided two-page `Round 1 Problem Statement | SupeRR Selector Season 2` PDF
  describes historical IPL and T20I delivery data from 2022 onward, but does not name
  the data publisher, dataset version, scoring codebook, or scorecard source.
- The Unstop submission page was retrieved but exposed only a wait/bootstrap page in this
  environment. No official scoring documentation was available from that page.
- Dataset publisher: **UNRESOLVED**. Distribution through Unstop is evidenced; that does not
  establish the original data publisher.
- Dataset version: **UNRESOLVED**. No version identifier is present in the archive contents
  or supplied documentation.

## Raw extras frequencies

| `extras_type` | Delivery rows |
|---|---:|
{extras_table}

`Overstep`, `Penalty`, and `other` account for {unresolved_rows:,} rows whose source scoring,
legal-ball, and bowler-credit rules are not documented. Full raw value combinations and counts
are in `source_value_frequencies.csv`; affected delivery identifiers and previous/next delivery
context are in `investigation_records.csv`.

## Scoring fields

- `runs`: four/six flags align with `runs=4`/`runs=6`, but this is internal consistency evidence
  only. Nonzero `runs` values also occur on extra-labeled deliveries. No source definition or
  independent scorecard confirms batter-run attribution.
- `extras1_runs` and `extras_2_runs`: values are available, but the source does not define their
  meaning or how they contribute to team totals, batter attribution, or bowler concession.
- `Stump`: {stump_rows:,} rows carry the label. The source does not define its canonical dismissal
  category or bowler-credit treatment.
- Legal-delivery classification and bowler-conceded runs remain unresolved.

## Independent reconciliation availability

- Reconstructed innings groups: {len(innings_reconciliation):,}.
- Scorecard comparison rows with an independent reference value: {independent_rows:,}.
- No independent scorecard values are present in any of the six supplied CSVs. Therefore the
  candidate sums in `innings_reconciliation.csv` and `scorecard_reconciliation.csv` are not
  reconciled scores. Target metadata lacks an effective-delivery timeline.
- This source-evidence reconciliation does not establish scoring semantics. When exploratory
  assumptions are configured and pressure validation passes, the pipeline writes
  separate hypothetical scoring-mapping sensitivity outputs. Those alternatives are not
  source-confirmed and are not a substitute for independent scorecards.
- Results based on these assumptions must not be interpreted as source-validated.

## Traceable files

- `innings_reconciliation.csv`: raw component sums, arithmetic candidate totals, raw wicket-flag
  counts, and target candidates; all labeled as unverified.
- `scorecard_reconciliation.csv`: candidate innings and batter values, unavailable bowler
  concessions, and explicit missing-reference statuses.
- `source_value_frequencies.csv` and `investigation_records.csv`: raw frequencies, row IDs, and
  delivery context for disputed categories.
- `data_investigation.md` and `data_dictionary.md`: existing per-category analysis and gate state.
"""


def write_reconciliation_reports(
    sources: SourceTables,
    output_dir: Path | str,
    *,
    analysis_mode: str = "ASSUMPTION_BASED_EXPLORATORY",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    destination = Path(output_dir)
    innings, scorecard = build_reconciliation(sources)
    output_label = "EXPLORATORY"
    for frame in (innings, scorecard):
        frame["analysis_mode"] = analysis_mode
        frame["output_label"] = output_label
    write_csv(destination / "innings_reconciliation.csv", innings)
    write_csv(destination / "scorecard_reconciliation.csv", scorecard)
    (destination / "scoring_semantics_evidence.md").write_text(
        _scoring_evidence_markdown(sources, innings, scorecard, analysis_mode),
        encoding="utf-8",
    )
    return innings, scorecard
