from __future__ import annotations

import pandas as pd

from suprr.config import AppConfig


def phase_for_over(over_number: int | float, config: AppConfig, over_base: int = 1) -> str:
    display_over = int(over_number) + (1 if over_base == 0 else 0)
    if config.phases.powerplay[0] <= display_over <= config.phases.powerplay[1]:
        return "powerplay"
    if config.phases.middle[0] <= display_over <= config.phases.middle[1]:
        return "middle"
    if config.phases.death[0] <= display_over <= config.phases.death[1]:
        return "death"
    return "outside_scheduled_phases"


def add_phase(frame: pd.DataFrame, config: AppConfig, over_base: int = 1) -> pd.DataFrame:
    result = frame.copy()
    result["phase"] = result["over_number"].map(
        lambda value: phase_for_over(value, config, over_base)
    )
    return result
