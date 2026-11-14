from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from suprr.config import AppConfig


@dataclass
class PressureValidationResult:
    passed: bool
    status: str
    summary: dict[str, Any]
    outcome_gradient: list[dict[str, Any]]
    ablations: list[dict[str, Any]]
    correlations: dict[str, float | None]
    diagnostics: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _wilson_interval(successes: int, total: int) -> tuple[float | None, float | None]:
    if total == 0:
        return None, None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * np.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _fit_ablation(
    frame: pd.DataFrame,
    features: list[str],
    seed: int,
) -> dict[str, Any]:
    if len(frame) < 20 or frame["match_id"].nunique() < 10:
        return {"features": features, "status": "insufficient_support"}
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=seed)
    train_idx, test_idx = next(
        splitter.split(frame[features], frame["outcome"], groups=frame["match_id"])
    )
    train = frame.iloc[train_idx]
    test = frame.iloc[test_idx]
    if train["outcome"].nunique() < 2 or test["outcome"].nunique() < 2:
        return {"features": features, "status": "single_class_split"}
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, random_state=seed),
    )
    model.fit(train[features], train["outcome"])
    probabilities = model.predict_proba(test[features])[:, 1]
    return {
        "features": features,
        "status": "evaluated",
        "train_matches": int(train["match_id"].nunique()),
        "test_matches": int(test["match_id"].nunique()),
        "test_rows": int(len(test)),
        "auc": float(roc_auc_score(test["outcome"], probabilities)),
        "brier": float(brier_score_loss(test["outcome"], probabilities)),
    }


def validate_pressure_model(
    states: pd.DataFrame,
    matches: pd.DataFrame,
    config: AppConfig,
) -> PressureValidationResult:
    required_states = {
        "match_id",
        "competition_id",
        "pressure_score",
        "pressure_band",
        "is_high_pressure",
        "R",
        "W",
        "D",
        "S",
        "batting_team_id",
    }
    missing = required_states - set(states.columns)
    if missing:
        raise ValueError(f"Pressure validation is missing state fields: {sorted(missing)}")
    if not {"match_id", "winner_team_id"}.issubset(matches.columns):
        raise ValueError("Pressure validation requires match winners keyed by match_id.")

    data = states.loc[states["pressure_score"].notna()].drop(
        columns=["winner_team_id"], errors="ignore"
    )
    data = data.merge(
        matches[["match_id", "winner_team_id"]].drop_duplicates("match_id"),
        on="match_id",
        how="left",
        validate="many_to_one",
    )
    data["outcome"] = (
        data["winner_team_id"].notna() & data["winner_team_id"].eq(data["batting_team_id"])
    ).astype(int)
    unresolved = data["winner_team_id"].isna()
    data = data.loc[~unresolved].copy()

    total_valid = int(len(data))
    high_rate = float(data["is_high_pressure"].astype(bool).mean()) if total_valid else None
    group_columns = [column for column in ("competition_id", "season") if column in data.columns]
    pressure_share_by_group = (
        data.groupby(group_columns, dropna=False)["is_high_pressure"]
        .mean()
        .rename("high_pressure_share")
        .reset_index()
        .to_dict(orient="records")
        if group_columns
        else []
    )
    diagnostics: list[str] = []
    if high_rate is not None and not 0.10 <= high_rate <= 0.40:
        diagnostics.append(
            f"High-pressure delivery share is {high_rate:.1%}, outside the 10-40% diagnostic range."
        )

    band_order = ["0-.2", ".2-.4", ".4-.6", ".6-.8", ".8-1"]
    match_band = data[["match_id", "pressure_band", "outcome"]].drop_duplicates(
        ["match_id", "pressure_band"]
    )
    gradient: list[dict[str, Any]] = []
    band_midpoints: list[float] = []
    band_rates: list[float] = []
    for band in band_order:
        group = match_band.loc[match_band["pressure_band"].astype("string").eq(band)]
        delivery_rows = int(data["pressure_band"].astype("string").eq(band).sum())
        count = int(group["match_id"].nunique())
        wins = int(group.drop_duplicates("match_id")["outcome"].sum())
        low, high = _wilson_interval(wins, count)
        gradient.append(
            {
                "pressure_band": band,
                "delivery_rows": delivery_rows,
                "wins": wins,
                "distinct_matches": count,
                "win_rate": wins / count if count else None,
                "ci95_low": low,
                "ci95_high": high,
                "interpretation": "standalone" if count >= 30 else "sparse_exploratory",
            }
        )
        if count:
            band_midpoints.append([0.1, 0.3, 0.5, 0.7, 0.9][band_order.index(band)])
            band_rates.append(wins / count)

    component_columns = ["R", "W", "D", "S"]
    correlations = data[component_columns].corr(method="pearson")
    correlations_dict = {
        f"{left}_{right}": (
            float(correlations.loc[left, right])
            if pd.notna(correlations.loc[left, right])
            else None
        )
        for index, left in enumerate(component_columns)
        for right in component_columns[index + 1 :]
    }
    if correlations_dict["R_D"] is not None and abs(correlations_dict["R_D"]) > 0.90:
        diagnostics.append(
            f"R and D are highly correlated (r={correlations_dict['R_D']:.3f}); "
            "component redundancy requires interpretation."
        )

    match_level = data.groupby("match_id", as_index=False).agg(
        outcome=("outcome", "first"),
        R=("R", "mean"),
        W=("W", "mean"),
        D=("D", "mean"),
        S=("S", "mean"),
        pressure_score=("pressure_score", "mean"),
    )
    specifications = {
        "full_components": component_columns,
        "omit_R": ["W", "D", "S"],
        "omit_D": ["R", "W", "S"],
        "only_R": ["R"],
        "only_W": ["W"],
        "only_D": ["D"],
        "only_S": ["S"],
    }
    ablations = [
        {"name": name, **_fit_ablation(match_level, features, config.random_seed)}
        for name, features in specifications.items()
    ]
    evaluated = [item for item in ablations if item.get("status") == "evaluated"]
    full = next(
        (item for item in evaluated if item["name"] == "full_components"),
        None,
    )
    ablation_auc = [item["auc"] for item in evaluated if item["name"] != "full_components"]
    best_ablation_auc = max(ablation_auc, default=None)
    if full is None:
        diagnostics.append(
            "Full-model AUC could not be estimated from the available match support."
        )
    elif best_ablation_auc is None:
        diagnostics.append("No ablation AUC could be estimated from the available match support.")
    elif full["auc"] < best_ablation_auc - 0.01:
        diagnostics.append("Full model is more than 0.01 AUC below the best evaluated ablation.")

    gradient_rho: float | None = None
    if len(band_rates) >= 3:
        rho = spearmanr(band_midpoints, band_rates).statistic
        gradient_rho = float(rho) if np.isfinite(rho) else None
    if gradient_rho is None or gradient_rho >= 0:
        diagnostics.append("The pressure-band chase-win outcome gradient is not decreasing.")
    if unresolved.any():
        diagnostics.append(
            f"{int(unresolved.sum())} live chase rows have no verified winner and were excluded."
        )
    passed = (
        full is not None
        and best_ablation_auc is not None
        and full["auc"] >= best_ablation_auc - 0.01
        and gradient_rho is not None
        and gradient_rho < 0
    )
    return PressureValidationResult(
        passed=passed,
        status="PASS" if passed else "PRESSURE MODEL NOT VALIDATED",
        summary={
            "valid_delivery_rows": total_valid,
            "distinct_matches": int(data["match_id"].nunique()),
            "unresolved_winner_rows": int(unresolved.sum()),
            "high_pressure_delivery_share": high_rate,
            "high_pressure_share_by_competition_season": pressure_share_by_group,
            "gradient_spearman_rho": gradient_rho,
            "full_model_auc": full["auc"] if full else None,
            "best_ablation_auc": best_ablation_auc,
            "auc_tolerance": 0.01,
            "random_seed": config.random_seed,
        },
        outcome_gradient=gradient,
        ablations=ablations,
        correlations=correlations_dict,
        diagnostics=diagnostics,
    )
