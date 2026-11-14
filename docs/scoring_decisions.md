# Scoring Decisions and Evidence

## Status and provenance

No cricket scoring definition is `SOURCE_CONFIRMED` in this snapshot. No scoring definition
was externally verified against a source-owner codebook or independent scorecard.

The local archive's Windows `Zone.Identifier` records:

- Download endpoint: <https://unstop.com/api/submissions_case/download/6af458274c1e8_data_pack.zip>
- Referrer: <https://unstop.com/competitions/1792758/submission/1673107>
- Archive SHA-256: `82DA62E94840E614EF136F0BB24168FE72B567C3EFF71BF6B58488AC9B2B7F7D`

The provided `Round 1 Problem Statement | SupeRR Selector Season 2` PDF describes historical
IPL and T20I delivery data from 2022 onward. It does not identify the original dataset
publisher, dataset version, scoring codebook, or scorecard provider. The Unstop submission
page did not expose documentation in the retrieval attempted for this investigation.
**Distribution through Unstop is evidenced; the original publisher and dataset version remain
unresolved.**

All six input CSVs were inspected. The available `matches.csv` has results and revised-condition
metadata, but no innings totals, batter scorecards, bowler figures, or target-effective-delivery
sequence. No independent scorecard data is available for reconciliation.

## Decisions by source field

Statuses:

- `SOURCE_CONFIRMED`: explicitly defined by the dataset publisher or codebook.
- `EXTERNALLY_VERIFIED`: confirmed by an independent authoritative source and cited.
- `INFERRED_FROM_DATA`: supported by observed data patterns, not authoritative documentation.
- `UNRESOLVED`: available evidence is insufficient to choose a safe mapping.

| Source field / raw label | Proposed canonical meaning | Evidence in this snapshot | Status | Batter impact | Bowler impact | Pressure impact | Decision |
|---|---|---|---|---|---|---|---|
| `runs` | Candidate batter runs off the bat, excluding extras | 23,283 four flags align with `runs=4`; 12,811 six flags align with `runs=6`; 474 extra-labeled rows have nonzero `runs`; no scorecard comparison | `INFERRED_FROM_DATA` | Runs, strike rate, boundary rate, dot rate | Downstream concession if used as a component | Innings totals and pre-delivery score | Do not use in validated mode until source definition or independent reconciliation |
| `extras1_runs` | Candidate extra-run amount | Populated with nonzero values on 7,714 `wide`, 576 `Overstep`, 529 `byes`, 2,747 `legbyes`, 264 `other`, and 1 `Penalty` row; source definition absent | `UNRESOLVED` | Attribution to batter is unknown | Attribution to bowler is unknown | Delivery and innings totals are unknown | Preserve as a raw numeric component only |
| `extras_2_runs` | Candidate secondary run amount / overthrow component | Nonzero values occur in multiple categories, including 21 `Overstep`, 14 `other`, and 1 `wide` row; source definition absent | `UNRESOLVED` | Could change batter attribution | Could change concession | Could change total and chase state | Do not call it overthrows without a source definition |
| `None` | No extras | Literal category occurs 189,167 times; no codebook defines the associated columns | `INFERRED_FROM_DATA` | No direct attribution established | No direct attribution established | Impacts total formula | Confirm source encoding before treating the string as zero extras |
| `wide` | Wide extra | Literal label occurs 7,714 times; `extras1_runs` is nonzero on each | `INFERRED_FROM_DATA` | Batter-run and balls-faced convention unconfirmed | Bowler charge unconfirmed | Legal-ball and total-run treatment unconfirmed | Conventional wide treatment is a proposal for manual review only |
| `Overstep` | Candidate no-ball | 576 rows; all have nonzero `extras1_runs`; 128 have a four/six flag | `INFERRED_FROM_DATA` | Batter runs/balls faced depend on mapping | Bowler credit depends on mapping | Legal-ball and score state depend on mapping | Candidate no-ball mapping is not source-confirmed |
| `byes` | Candidate byes | 529 rows; all have nonzero `extras1_runs` | `INFERRED_FROM_DATA` | Batter attribution depends on mapping | Bowler concession depends on mapping | Total and legal-ball treatment depend on mapping | Conventional bye treatment is a proposal for manual review only |
| `legbyes` | Candidate leg-byes | 2,748 rows; 2,747 have nonzero `extras1_runs`; one row also has nonzero `runs` | `INFERRED_FROM_DATA` | The anomalous `runs` value remains unexplained | Concession depends on mapping | Total and legal-ball treatment depend on mapping | Do not rewrite the anomalous row |
| `Penalty` | Unspecified penalty event | One row: `runs=0`, `extras1_runs=5`, `extras_2_runs=0`, no boundary or wicket flag | `UNRESOLVED` | Recipient and attribution unknown | Charge unknown | Award timing and ball effect unknown | Require source-owner confirmation; do not model as a standard delivery extra |
| `other` | Unspecified extra/event | 264 rows; all have nonzero `extras1_runs`; 14 have nonzero `extras_2_runs`; 3 have a wicket flag | `UNRESOLVED` | Batter attribution unknown | Concession unknown | Legal delivery and total unknown | Require source-owner definition for each event represented |
| `is_wicket` | Source wicket flag | Present for all delivery rows; all 214 `Stump` rows are true and have a dismissed-player ID | `INFERRED_FROM_DATA` | Dismissal denominator depends on event meaning | Wicket credit depends on event meaning | Wicket state affects pressure | Raw flag is not a substitute for dismissal reconciliation |
| `Stump` / `dismissal_type_id=5` | Possible alias for `Stumped` | 214 rows; all true `is_wicket`; all have dismissed-player IDs; no source enum lookup | `UNRESOLVED` | Dismissal rate and player outs | Bowler wickets, average, and strike rate | Wickets in hand and pressure state | Do not map to `Stumped` or bowler-credit it without confirmation |
| Legal-delivery classification | Legal ball vs wide/no-ball/etc. | No delivery-level legal-ball flag; raw extras labels are undocumented | `UNRESOLVED` | Balls faced and strike rate | Overs, economy, strike rate | Balls remaining and pressure | Requires a source-owner-confirmed rule for every raw extras category |
| Bowler runs conceded | Per-delivery bowler charge | Depends on total runs and extras attribution; no independent bowler figures supplied | `UNRESOLVED` | No direct effect | Economy, average, and pressure economy | Bowler pressure metrics | Do not infer by summing raw fields |

## Conventional proposals for manual review

These are not source-confirmed and were not applied to the validated pipeline:

1. Treat `runs` as batter runs excluding extras, and reconstruct a candidate delivery total as
   `runs + extras1_runs + extras_2_runs`.
2. Treat `wide` as a wide and `Overstep` as a no-ball; both would be illegal deliveries under a
   conventional T20 scoring interpretation.
3. Treat byes and leg-byes as team extras, not batter runs or bowler-conceded runs; count them as
   legal deliveries only when the delivery is otherwise legal.
4. Do not assign the `Penalty` row or `other` category until their source-specific meaning,
   beneficiary, bowler attribution, and legal-ball effect are established.
5. Treat `Stump` as `Stumped` only if the source owner confirms that alias; then use the selected
   dismissal credit rule explicitly.

No external cricket-law page was successfully retrieved during this investigation. These
proposals are therefore labelled **MANUAL REVIEW**, not `EXTERNALLY_VERIFIED`.

## Reconciliation decision

The output files `data/reports/innings_reconciliation.csv` and
`data/reports/scorecard_reconciliation.csv` contain candidate raw-field sums and explicit
missing-reference statuses. They do not establish score agreement. The source does not contain
independent innings totals, targets with effective-delivery timing, batter scorecards, or bowler
figures. The project therefore presents these interpretations as exploratory assumptions only.
