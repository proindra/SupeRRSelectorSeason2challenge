from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from suprr.config import AppConfig
from suprr.schemas import CanonicalTables, SourceTables


class MappingError(ValueError):
    """Raised when required canonical columns are not explicitly mapped."""


def canonicalize_sources(
    sources: SourceTables,
    config: AppConfig,
    overrides: Mapping[str, Mapping[str, str | None]] | None = None,
) -> CanonicalTables:
    canonical: CanonicalTables = {}
    overrides = overrides or {}
    for table, mappings in config.source_fields.items():
        if table not in sources:
            raise MappingError(f"No source table loaded for mapping group {table!r}.")
        source = sources[table]
        selected = dict(mappings)
        selected.update(overrides.get(table, {}))
        mapped: dict[str, pd.Series] = {}
        for canonical_name, source_name in selected.items():
            if source_name is None:
                continue
            if source_name not in source.columns:
                raise MappingError(
                    f"{table}.{canonical_name} maps to missing source column {source_name!r}."
                )
            mapped[canonical_name] = source[source_name]
        canonical[table] = pd.DataFrame(mapped, index=source.index)
        canonical[table]["_source_row"] = source.index.astype("int64")
    return canonical


def normalize_source_mappings(
    sources: SourceTables,
    config: AppConfig,
    overrides: Mapping[str, Mapping[str, str | None]],
) -> SourceTables:
    normalized: SourceTables = dict(sources)
    for table, defaults in config.source_fields.items():
        if table not in sources:
            raise MappingError(f"No source table loaded for mapping group {table!r}.")
        selected = dict(defaults)
        selected.update(overrides.get(table, {}))
        targets: dict[str, str] = {}
        selected_columns: set[str] = set()
        for canonical_name, default_source in defaults.items():
            source_name = selected.get(canonical_name)
            if source_name is None:
                continue
            if source_name not in sources[table].columns:
                raise MappingError(
                    f"{table}.{canonical_name} maps to missing source column {source_name!r}."
                )
            if source_name in selected_columns:
                raise MappingError(
                    f"Source column {table}.{source_name!r} is mapped to multiple canonical fields."
                )
            selected_columns.add(source_name)
            if default_source is not None:
                targets[source_name] = default_source
        if len(set(targets.values())) != len(targets):
            raise MappingError(f"{table} has multiple source columns mapped to one field.")
        drops = [
            target
            for target in targets.values()
            if target in sources[table].columns and target not in selected_columns
        ]
        frame = sources[table].drop(columns=drops).copy()
        renames = {
            source_name: target for source_name, target in targets.items() if source_name != target
        }
        frame = frame.rename(columns=renames)
        if frame.columns.duplicated().any():
            duplicates = frame.columns[frame.columns.duplicated()].tolist()
            raise MappingError(
                f"{table} mapping creates duplicate normalized columns: {duplicates}."
            )
        normalized[table] = frame
    return normalized


def validate_required_mappings(
    sources: SourceTables,
    config: AppConfig,
    overrides: Mapping[str, Mapping[str, str | None]] | None = None,
) -> list[str]:
    errors = []
    overrides = overrides or {}
    required = {
        "deliveries": {
            "match_id",
            "innings",
            "over_number",
            "ball_number",
            "striker_id",
            "bowler_id",
            "batter_runs",
            "wicket_flag",
            "extras_type",
        },
        "matches": {"match_id", "competition_id", "team1_id", "team2_id"},
        "competitions": {"competition_id", "format", "season"},
        "player_team_mapping": {"competition_id", "team_id", "player_id", "player_name"},
    }
    for table, fields in required.items():
        if table not in sources:
            errors.append(f"Required source table {table!r} is missing.")
            continue
        mapping = dict(config.source_fields.get(table, {}))
        mapping.update(overrides.get(table, {}))
        for field in sorted(fields):
            source_column = mapping.get(field)
            if source_column is None:
                errors.append(f"Canonical field {table}.{field} is not mapped.")
            elif source_column not in sources[table].columns:
                errors.append(
                    f"Canonical field {table}.{field} maps to missing source column "
                    f"{source_column!r}."
                )
    return errors
