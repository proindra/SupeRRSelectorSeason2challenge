from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd


def match_level_bootstrap(
    states: pd.DataFrame,
    evaluate: Callable[[pd.DataFrame], pd.DataFrame],
    *,
    player_column: str,
    score_column: str = "composite_score",
    replicates: int = 500,
    seed: int = 42,
) -> pd.DataFrame:
    if replicates < 500:
        raise ValueError("Match-level bootstrap requires at least 500 replicates.")
    matches = states["match_id"].dropna().drop_duplicates().to_numpy()
    if len(matches) < 2:
        raise ValueError("At least two distinct matches are required for bootstrap.")
    random = np.random.default_rng(seed)
    records: list[pd.DataFrame] = []
    for replicate in range(replicates):
        sampled = random.choice(matches, size=len(matches), replace=True)
        chunks = []
        for draw, match_id in enumerate(sampled):
            chunk = states.loc[states["match_id"].eq(match_id)].copy()
            chunk["match_id"] = f"bootstrap-{replicate}-{draw}"
            chunks.append(chunk)
        replicate_states = pd.concat(chunks, ignore_index=True)
        ranking = evaluate(replicate_states)
        required = {player_column, score_column, "rank"}
        missing = required - set(ranking.columns)
        if missing:
            raise ValueError(f"Bootstrap evaluator omitted columns: {sorted(missing)}")
        ranking = ranking[[player_column, score_column, "rank"]].copy()
        ranking["replicate"] = replicate
        records.append(ranking)
    return pd.concat(records, ignore_index=True)


def summarize_bootstrap(
    results: pd.DataFrame,
    *,
    player_column: str,
    confidence_level: float = 0.90,
) -> pd.DataFrame:
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between zero and one.")
    tail = (1 - confidence_level) / 2
    summary = results.groupby(player_column, as_index=False).agg(
        score_median=("composite_score", "median"),
        score_low=("composite_score", lambda values: values.quantile(tail)),
        score_high=("composite_score", lambda values: values.quantile(1 - tail)),
        rank_median=("rank", "median"),
        rank_low=("rank", lambda values: values.quantile(tail)),
        rank_high=("rank", lambda values: values.quantile(1 - tail)),
        top_10_frequency=("rank", lambda values: values.le(10).mean()),
        valid_replicates=("replicate", "nunique"),
    )
    return summary
