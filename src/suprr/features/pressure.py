from __future__ import annotations

import numpy as np

from suprr.config import AppConfig


def pressure_components(
    runs_needed_before: float,
    legal_balls_remaining_before: float,
    wickets_lost_before: float,
    legal_balls_bowled_before: float,
    scheduled_legal_balls: float,
    config: AppConfig,
) -> dict[str, float] | None:
    wickets_in_hand = 10 - wickets_lost_before
    if runs_needed_before <= 0 or legal_balls_remaining_before <= 0 or wickets_in_hand <= 0:
        return None
    r = min(
        max(
            (runs_needed_before * 6 / legal_balls_remaining_before)
            / config.pressure.required_rate_cap,
            0.0,
        ),
        1.0,
    )
    w = min(max(wickets_lost_before / 10, 0.0), 1.0)
    max_expected_runs = (
        legal_balls_remaining_before
        * config.pressure.maximum_assumed_runs_per_ball
        * wickets_in_hand
        / 10
    )
    d = min(max(runs_needed_before / max_expected_runs, 0.0), 1.0)
    s = min(max(legal_balls_bowled_before / scheduled_legal_balls, 0.0), 1.0)
    weights = config.pressure.weights
    score = (
        weights.required_rate * r
        + weights.wickets_lost * w
        + weights.chase_difficulty * d
        + weights.innings_stage * s
    )
    if not np.isfinite(score) or not 0 <= score <= 1:
        raise ArithmeticError(f"Invalid pressure score: {score}")
    return {"R": r, "W": w, "D": d, "S": s, "pressure_score": score}
