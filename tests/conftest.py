from __future__ import annotations

from pathlib import Path

import pytest

from suprr.config import AppConfig, load_config


@pytest.fixture
def config() -> AppConfig:
    root = Path(__file__).resolve().parents[1]
    original = load_config(root / "config" / "default.yaml")
    scoring = original.scoring.model_copy(
        update={
            "batter_runs_excludes_extras_confirmed": True,
            "legal_delivery_categories_confirmed": True,
            "super_over_innings_verified": True,
            "target_timing_reconstructible": False,
            "extras": {
                "none": ["None"],
                "wide": ["wide"],
                "no_ball": ["no_ball"],
                "byes": ["byes"],
                "leg_byes": ["legbyes"],
                "penalty": ["Penalty"],
                "unresolved": [],
            },
            "dismissals": {
                **original.scoring.dismissals,
                "bowler_credited": [
                    dismissal
                    for dismissal in original.scoring.dismissals["bowler_credited"]
                    if dismissal != "Stump"
                ],
                "unresolved": ["Stump"],
            },
        }
    )
    samples = original.samples.model_copy(
        update={
            "batter_pressure_balls": 18,
            "batter_pressure_innings": 2,
            "bowler_legal_pressure_balls": 4,
            "bowler_pressure_spells": 1,
            "minimum_balls_per_innings_or_spell": 6,
        }
    )
    pressure = original.pressure.model_copy(update={"scheduled_legal_balls": 120})
    return original.model_copy(
        update={"scoring": scoring, "samples": samples, "pressure": pressure}
    )
