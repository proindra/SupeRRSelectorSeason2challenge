from __future__ import annotations

from collections.abc import Callable

import pandas as pd
from scipy.stats import spearmanr


def _compare(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    player_column: str,
) -> dict[str, float | int | None]:
    merged = left[[player_column, "rank"]].merge(
        right[[player_column, "rank"]],
        on=player_column,
        how="inner",
        suffixes=("_left", "_right"),
        validate="one_to_one",
    )
    rho = None
    if len(merged) >= 2:
        statistic = spearmanr(merged["rank_left"], merged["rank_right"]).statistic
        rho = float(statistic) if pd.notna(statistic) else None
    left_top = set(left.nsmallest(10, "rank")[player_column])
    right_top = set(right.nsmallest(10, "rank")[player_column])
    return {
        "shared_players": int(len(merged)),
        "spearman_rank_correlation": rho,
        "top_10_overlap": int(len(left_top & right_top)),
    }


def split_half_checks(
    states: pd.DataFrame,
    evaluate: Callable[[pd.DataFrame], pd.DataFrame],
    *,
    player_column: str,
    date_column: str = "match_date",
    minimum_matches: int = 8,
) -> pd.DataFrame:
    matches = states[["match_id"] + ([date_column] if date_column in states else [])]
    matches = matches.drop_duplicates("match_id")
    if date_column in matches:
        matches[date_column] = pd.to_datetime(matches[date_column], errors="coerce", utc=True)
    if len(matches) < minimum_matches:
        return pd.DataFrame(
            [{"split": "all", "status": "insufficient_support", "matches": len(matches)}]
        )
    outputs = []
    if date_column in matches and matches[date_column].notna().all():
        ordered = matches.sort_values(date_column, kind="stable")["match_id"].tolist()
        midpoint = len(ordered) // 2
        split_sets = {
            "chronological": (set(ordered[:midpoint]), set(ordered[midpoint:])),
        }
    else:
        split_sets = {}
    ordered_ids = sorted(matches["match_id"].astype(str))
    split_sets["odd_even"] = (
        set(ordered_ids[::2]),
        set(ordered_ids[1::2]),
    )
    for name, (left_ids, right_ids) in split_sets.items():
        left_states = states.loc[states["match_id"].astype(str).isin(left_ids)]
        right_states = states.loc[states["match_id"].astype(str).isin(right_ids)]
        left = evaluate(left_states)
        right = evaluate(right_states)
        outputs.append(
            {
                "split": name,
                "status": "evaluated",
                "left_matches": int(len(left_ids)),
                "right_matches": int(len(right_ids)),
                **_compare(left, right, player_column=player_column),
            }
        )
    return pd.DataFrame(outputs)
