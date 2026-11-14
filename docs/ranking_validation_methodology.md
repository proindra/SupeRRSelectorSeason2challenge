# Ranking Validation and Robustness Assessment

## Purpose and status labels

This module assesses the arithmetic consistency and statistical robustness of a
completed, assumption-based exploratory run. It is separate from the exploratory
pipeline and writes its outputs to that run's `validation/` subdirectory; it does not
rewrite the original ranking CSVs, manifests, or reports.

- **EXPLORATORY** identifies the input rankings and metrics. The source scoring
  semantics remain assumption-based and are not source-confirmed.
- **VALIDATED** is used only for individual mathematical consistency checks, such
  as recomputed rates, weighted-Z composite scores, rank order, and reproduction
  from saved pressure states. It does not mean the underlying cricket definitions
  are validated.
- **ROBUSTNESS-ASSESSED** identifies bootstrap and sensitivity outputs. It describes
  the extent of these specific checks, not scientific, causal, or external
  validation.

The overall report remains **ROBUSTNESS-ASSESSED — EXPLORATORY INPUTS** even when
every arithmetic check passes. The module refuses strict or otherwise non-exploratory
run manifests.

## Inputs and comparison groups

The validator reads `processed/pressure_states.parquet`, the run manifest, and the
full and Top-10 batter/bowler ranking CSVs from one completed exploratory run. It
filters to winning IPL and T20I matches, matching the existing ranking pipeline.
The competition classifier's `Other` group is excluded and shown in the source run's
data, not mixed into IPL/T20I rankings.

For each ranking role, the module recomputes player metrics and rankings with the
existing metric and ranking functions. It reports three views:

1. `IPL_T20I`: the existing combined ranking scope.
2. `IPL`: IPL-only baselines, eligibility, rankings, and robustness.
3. `T20I`: T20I-only baselines, eligibility, rankings, and robustness.

## Mathematical consistency checks

Checks include:

- uniqueness of player rows and preservation of the `EXPLORATORY` label;
- batter strike rate, strike-rate change, boundary rate, dot-ball rate, and
  dismissal rate identities;
- bowler economy, economy improvement, boundary and dot rates, regularised average
  and strike rate, and wickets-per-100-balls identities;
- `complete_metrics`, weighted-Z components, composite-score, rank, and Top-10
  ordering consistency;
- reproduction of exported player-level counts and rates, weighted-Z components,
  composite scores, and ranks by rerunning the existing metric and scoring code
  over the saved pre-delivery states.

Formula checks use a relative and absolute tolerance of `1e-8`. A failed check is
reported rather than silently corrected. The `mathematical_checks.csv` file names
each check and its row and failure counts. Competition-scoped bowling rates are
checked before aggregation; the combined profile uses the pipeline's legal-ball
exposure-weighted average across IPL and T20I, which is not generally equal to a
single formula applied to totals pooled across competitions.

## Match-cluster bootstrap

The bootstrap samples whole matches with replacement, separately within IPL and
T20I. Each duplicate draw receives a new match identifier before recalculating
metrics, so resampled copies are treated as separate matches. The default is 500
replicates with the configured seed and confidence level (90% by default).

For each player and role/scope, the validator reports percentile intervals for rank,
composite score, and the pressure metric, along with valid-replicate counts. The
batter pressure metric is pressure strike rate. The bowler pressure metric is the
project's regularised bowling strike rate. Pressure-metric intervals use replicates
where the metric is estimable; their valid count is kept separate from the total
replicate count.

Top-10 inclusion probability is the number of replicates with rank at most 10 divided
by the total number of replicates. A player absent or ineligible in a replicate is
not included in that replicate's numerator. A player is flagged as bootstrap-unstable
when the baseline rank is Top 10 and its estimated inclusion probability is below
80% by default. This flag is a descriptive screening threshold, not a significance
test.

## Sensitivity analysis

Each signed composite weight is changed individually by plus and minus the
configured perturbation (20% by default); weight signs are preserved and weights
are not renormalized. The module also varies, one at a time:

- minimum pressure balls / legal pressure balls;
- minimum pressure innings / spells;
- minimum balls per qualifying innings / spell.

Each threshold is set to 75% and 125% of baseline, rounded up to a positive integer.
The qualifying-innings/spells variants recalculate metrics; eligibility variants
rerun the ranking with the adjusted thresholds. Top-10 overlap, membership churn,
and per-player rank changes are exported. These one-factor checks do not optimize or
recommend weights or eligibility criteria.

The existing exploratory run's hypothetical scoring-mapping sensitivity is also
used to flag assumption-dependent combined-ranking players, when that file is
available. Those scenarios are explicitly hypothetical and are not source evidence
or replacements for the configured exploratory mapping.

A player is marked `ranking_unstable` if a baseline Top-10 player's bootstrap
inclusion probability falls below the configured threshold, or if any weight,
sample-threshold, or available scoring-mapping scenario changes Top-10 membership.
Mapping sensitivity additionally honors the existing run's significant-change flag
(Top-10 change or a rank shift of at least five places).

## Assumptions and limitations

- The saved pressure states already embody the configured exploratory scoring
  assumptions. In particular, interpretations of `runs`, total delivery runs,
  extras, legal balls, bowler-conceded runs, and `Stump` dismissals are not made
  source-confirmed by this module.
- Bootstrap intervals are conditional on the dataset, match exclusions, pressure
  states, scoring assumptions, metric definitions, competition classifier, and
  ranking weights. They are not causal estimates.
- Reproducing a calculation verifies implementation consistency, not the truth or
  suitability of its inputs or methodology.
- Weight and sample-threshold sensitivity measures model dependence; it does not
  prove that the baseline choice is correct.
- No independent scorecard comparison or external source validation is performed
  by this module.
- These outputs must not be presented as validated cricket-scoring semantics or
  scientifically validated player rankings.

## Reproducible execution

From the project root in PowerShell:

```powershell
uv run python scripts/validate_rankings.py `
  --run-dir artifacts/exploratory/0f34cc9f-0001-4a7b-bb8f-d4bfe41b70d4 `
  --replicates 500 --seed 42
```

The command requires at least 500 bootstrap replicates. Change the run ID to assess
another completed exploratory run. Outputs are isolated under
`artifacts/exploratory/<run-id>/validation/`:

- `mathematical_checks.csv`
- `ranking_input_issues.csv` for malformed labels, duplicate/missing IDs, and
  Top-10 file shape/order problems
- `scope_rankings.csv` and `scope_top10.csv` for combined, IPL-only, and T20I-only
  rankings
- `bootstrap_replicates.csv`
- `bootstrap_summary.csv`
- `sensitivity_scenarios.csv`
- `sensitivity_summary.csv`
- `player_instability.csv`
- `validation_report.md`
- `validation_manifest.json`

The `--output-dir` option can select a separate destination. The input run's
exploratory rankings are treated as read-only.
