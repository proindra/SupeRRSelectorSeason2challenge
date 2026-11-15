# Exploratory Scoring Assumptions

The pipeline uses the scoring mappings in `config/default.yaml` to calculate exploratory
rankings. These are working assumptions, not definitions confirmed by the dataset publisher or
an authoritative scoring codebook.

The current mappings treat `Overstep` as a no-ball, classify `Penalty` and `other` as team extras,
and map `Stump` to the `Stumped` dismissal category. The configured bowler-concession formula
charges wide/no-ball extras to the bowler and does not charge other extras. The source does not
provide a confirmed legal-delivery flag or a definitive description of every extras field.

Players mapped to Pakistan or Pakistan A squads are excluded from ranking candidates and dashboard
player profiles because they are ineligible for the IPL. The source has no nationality field, so
squad membership is used as the available proxy; source records and pressure states remain intact.

The source audit, reconciliation evidence, and unresolved mapping findings remain available under
`data/reports/` and in each exploratory run's `reports/` directory. They are diagnostic evidence;
the pipeline does not use them to block exploratory analysis. Dashboard charts and rankings must
remain labelled **EXPLORATORY** and must not be presented as source-validated results.

The effective target timeline is unavailable for revised-condition matches, so those matches
remain excluded. Confirmed Super Over innings are also excluded from the primary analysis.
