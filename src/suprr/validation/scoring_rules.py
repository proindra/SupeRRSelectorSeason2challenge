from __future__ import annotations

from suprr.config import AppConfig


def extra_category(value: object, config: AppConfig) -> str:
    normalized = str(value).strip()
    if normalized in config.scoring.extras.get("unresolved", []):
        return "unresolved"
    for category, values in config.scoring.extras.items():
        if category != "unresolved" and normalized in values:
            return category
    return "unresolved"


def dismissal_category(value: object, config: AppConfig) -> str:
    normalized = str(value).strip()
    if normalized in config.scoring.dismissals.get("unresolved", []):
        return "unresolved"
    for category, values in config.scoring.dismissals.items():
        if category != "unresolved" and normalized in values:
            return category
    return "unresolved"
