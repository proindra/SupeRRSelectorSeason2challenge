from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PressureWeights(StrictModel):
    required_rate: float = Field(ge=0, le=1)
    wickets_lost: float = Field(ge=0, le=1)
    chase_difficulty: float = Field(ge=0, le=1)
    innings_stage: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> PressureWeights:
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-8:
            raise ValueError("Pressure weights must sum to 1.")
        return self


class PressureSettings(StrictModel):
    weights: PressureWeights
    required_rate_cap: float = Field(gt=0)
    maximum_assumed_runs_per_ball: float = Field(gt=0)
    high_pressure_threshold: float = Field(ge=0, le=1)
    clutch_threshold: float = Field(ge=0, le=1)
    scheduled_legal_balls: int = Field(gt=0)
    exclude_super_overs: bool
    main_run_excludes_uncertain_revised_target_matches: bool


class SampleSettings(StrictModel):
    batter_pressure_balls: int = Field(gt=0)
    batter_pressure_innings: int = Field(gt=0)
    bowler_legal_pressure_balls: int = Field(gt=0)
    bowler_pressure_spells: int = Field(gt=0)
    minimum_balls_per_innings_or_spell: int = Field(gt=0)
    phase_support_balls: int = Field(gt=0)
    matchup_group_balls: int = Field(gt=0)


class ReliabilitySettings(StrictModel):
    default_k_balls: int = Field(gt=0)
    sensitivity_k: list[int]


class RobustnessSettings(StrictModel):
    pressure_thresholds: list[float]
    clutch_thresholds: list[float]
    bootstrap_replicates: int = Field(ge=500)
    bootstrap_confidence_level: float = Field(gt=0, lt=1)
    random_seed: int
    stability_flag_threshold: float = Field(ge=0, le=1)
    weight_perturbation: float = Field(ge=0, le=1)


class ScoringSettings(StrictModel):
    batter_runs_excludes_extras_confirmed: bool
    extras: dict[str, list[str]]
    dismissals: dict[str, list[str]]
    legal_delivery_categories_confirmed: bool
    target_timing_reconstructible: bool
    super_over_innings_verified: bool


class PhaseSettings(StrictModel):
    powerplay: tuple[int, int]
    middle: tuple[int, int]
    death: tuple[int, int]


class CompetitionGroupSettings(StrictModel):
    ipl_name_tokens: list[str]
    t20i_format: str


class AppConfig(StrictModel):
    version: str
    random_seed: int
    source_fields: dict[str, dict[str, str | None]]
    scoring: ScoringSettings
    pressure: PressureSettings
    samples: SampleSettings
    reliability: ReliabilitySettings
    robustness: RobustnessSettings
    phases: PhaseSettings
    competition_groups: CompetitionGroupSettings


def load_config(path: Path | str) -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        raw: Any = yaml.safe_load(file)
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration must be a YAML object: {config_path}")
    return AppConfig.model_validate(raw)
