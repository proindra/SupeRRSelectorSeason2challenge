from __future__ import annotations

import pandas as pd


def pooled_rate(
    frame: pd.DataFrame,
    group_columns: list[str],
    numerator: str,
    denominator: str,
    output_name: str,
) -> pd.DataFrame:
    totals = frame.groupby(group_columns, dropna=False, as_index=False).agg(
        _numerator=(numerator, "sum"),
        _denominator=(denominator, "sum"),
    )
    totals[output_name] = totals["_numerator"] / totals["_denominator"].where(
        totals["_denominator"].ne(0)
    )
    return totals.drop(columns=["_numerator", "_denominator"])
