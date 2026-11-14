from __future__ import annotations

import argparse
from pathlib import Path

from suprr.validation.ranking_quality import validate_exploratory_rankings


def main() -> int:
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Assess mathematical consistency and robustness of a completed exploratory ranking run."
        )
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Completed exploratory run directory under artifacts/exploratory/.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_dir / "config" / "default.yaml",
        help="YAML configuration used by the analytics pipeline.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Validation output directory; defaults to <run-dir>/validation/.",
    )
    parser.add_argument(
        "--replicates",
        type=int,
        default=500,
        help="Stratified match-bootstrap replicates (minimum 500).",
    )
    parser.add_argument("--seed", type=int, help="Override the configured random seed.")
    parser.add_argument(
        "--top10-probability-threshold",
        type=float,
        default=0.80,
        help="Flag baseline Top-10 players below this bootstrap inclusion probability.",
    )
    arguments = parser.parse_args()
    run_dir = arguments.run_dir
    config_path = arguments.config
    output_dir = arguments.output_dir
    if not run_dir.is_absolute():
        run_dir = project_dir / run_dir
    if not config_path.is_absolute():
        config_path = project_dir / config_path
    if output_dir is not None and not output_dir.is_absolute():
        output_dir = project_dir / output_dir

    result = validate_exploratory_rankings(
        run_dir,
        config_path=config_path,
        output_dir=output_dir,
        replicates=arguments.replicates,
        seed=arguments.seed,
        top10_probability_threshold=arguments.top10_probability_threshold,
    )
    print(f"Assessment: {result['overall_status']}")
    print(f"Mathematical checks: {result['mathematical_status']}")
    print(f"Output directory: {result['output_dir']}")
    return 0 if result["mathematical_status"] == "VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
