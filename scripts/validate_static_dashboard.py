from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = PROJECT_ROOT / "site"
DATA_PATH = SITE_ROOT / "data" / "dashboard.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> None:
    payload: dict[str, Any] = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    _require(payload.get("manifest", {}).get("status") == "EXPLORATORY_COMPLETE",
             "Static site data must come from a completed exploratory run.")
    _require(payload.get("manifest", {}).get("output_label") == "EXPLORATORY",
             "Static site data must retain its exploratory label.")
    for role in ("batter", "bowler"):
        ranking = payload.get("rankings", {}).get(role, {})
        _require(bool(ranking.get("full")), f"Missing full {role} rankings.")
        _require(bool(ranking.get("top10")), f"Missing saved {role} Top 10.")
        _require(
            all(1 <= int(row.get("rank") or 0) <= 10 for row in ranking["top10"]),
            f"Invalid saved Top 10 rank in {role} results.",
        )
    _require(bool(payload.get("quality", {}).get("source_evidence")),
             "Missing source-evidence diagnostics.")
    _require(bool(payload.get("pressure_validation", {}).get("outcome_gradient")),
             "Missing saved pressure outcome gradient.")
    for relative_path in ("index.html", "styles.css", "app.js"):
        _require((SITE_ROOT / relative_path).is_file(), f"Missing site asset: {relative_path}")
    print(
        "Static dashboard data is valid: "
        f"{len(payload['rankings']['batter']['full'])} batters, "
        f"{len(payload['rankings']['bowler']['full'])} bowlers, "
        f"run {payload['manifest']['run_id']}."
    )


if __name__ == "__main__":
    main()
