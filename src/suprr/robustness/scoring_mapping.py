from __future__ import annotations

from dataclasses import dataclass

from suprr.config import AppConfig


@dataclass(frozen=True)
class ScoringMappingScenario:
    scenario_id: str
    description: str
    config: AppConfig


def hypothetical_scoring_mappings(config: AppConfig) -> tuple[ScoringMappingScenario, ...]:
    scenarios = []

    extras = {category: list(values) for category, values in config.scoring.extras.items()}
    extras["no_ball"] = [value for value in extras.get("no_ball", []) if value != "Overstep"]
    extras["other"] = [*extras.get("other", []), "Overstep"]
    scoring = config.scoring.model_copy(update={"extras": extras})
    scenarios.append(
        ScoringMappingScenario(
            scenario_id="overstep_as_legal_other",
            description=(
                "Hypothetically treat Overstep as a legal, non-bowler-charged other extra "
                "instead of a no-ball."
            ),
            config=config.model_copy(update={"scoring": scoring}),
        )
    )

    dismissals = {
        category: list(values) for category, values in config.scoring.dismissals.items()
    }
    dismissals["bowler_credited"] = [
        value for value in dismissals.get("bowler_credited", []) if value != "Stump"
    ]
    scoring = config.scoring.model_copy(update={"dismissals": dismissals})
    scenarios.append(
        ScoringMappingScenario(
            scenario_id="stump_not_bowler_credited",
            description=(
                "Hypothetically retain Stump as a batter dismissal but do not credit it "
                "to the bowler."
            ),
            config=config.model_copy(update={"scoring": scoring}),
        )
    )
    return tuple(scenarios)
