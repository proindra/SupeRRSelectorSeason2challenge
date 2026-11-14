from __future__ import annotations

import argparse
from pathlib import Path

from suprr.pipeline import run_pipeline


def main() -> int:
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run the cricket pressure analytics pipeline.")
    parser.add_argument(
        "--raw-dir", type=Path, help="Directory containing the six required CSV files."
    )
    parser.add_argument("--config", type=Path, help="Path to the YAML configuration.")
    parser.add_argument(
        "--full-robustness",
        action="store_true",
        help=(
            "Run sensitivity, scoring-mapping, scenario, match-bootstrap, and split-half "
            "analyses. This may be expensive."
        ),
    )
    arguments = parser.parse_args()
    result = run_pipeline(
        project_dir,
        raw_dir=arguments.raw_dir,
        config_path=arguments.config,
        full_robustness=arguments.full_robustness,
    )
    print(f"Run {result['run_id']}: {result['status']}")
    if result.get("output_dir"):
        print(f"Output directory: {result['output_dir']}")
    for blocker in result.get("blockers", []):
        print(f"BLOCKER: {blocker}")
    return 0 if result["status"] == "EXPLORATORY_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
