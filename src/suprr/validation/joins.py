from __future__ import annotations

import pandas as pd


def join_coverage(
    child: pd.DataFrame,
    parent: pd.DataFrame,
    child_columns: list[str],
    parent_columns: list[str],
) -> dict[str, int | float]:
    if len(child_columns) != len(parent_columns):
        raise ValueError("Child and parent join keys must have equal lengths.")
    child_keys = child[child_columns].copy()
    parent_keys = parent[parent_columns].copy().drop_duplicates()
    child_keys.columns = [f"key_{i}" for i in range(len(child_columns))]
    parent_keys.columns = child_keys.columns
    complete = child_keys.notna().all(axis=1)
    child_complete = child_keys.loc[complete]
    parent_index = pd.MultiIndex.from_frame(parent_keys)
    matched = pd.MultiIndex.from_frame(child_complete).isin(parent_index)
    match_count = int(matched.sum())
    checked = int(len(child_complete))
    return {
        "source_rows": int(len(child)),
        "checked_rows": checked,
        "matched_rows": match_count,
        "orphan_rows": checked - match_count,
        "incomplete_rows": int(len(child) - checked),
        "match_rate": (match_count / checked) if checked else 0.0,
        "target_unique_keys": int(len(parent_keys)),
    }
