from __future__ import annotations

from pathlib import Path

import pandas as pd

from suprr.schemas import SOURCE_FILES, SourceTables


class InputFilesError(ValueError):
    """Raised when a required source file is missing or cannot be read."""


def normalize_frame(frame: pd.DataFrame, source_name: str = "CSV") -> pd.DataFrame:
    original = list(frame.columns)
    normalized = [str(column).strip() for column in original]
    if len(set(normalized)) != len(normalized):
        raise InputFilesError(
            f"{source_name} has column names that collide after trimming whitespace."
        )
    result = frame.copy()
    result.columns = normalized
    for column in result.columns:
        if pd.api.types.is_string_dtype(result[column].dtype) or result[column].dtype == object:
            result[column] = result[column].astype("string").str.strip()
            result[column] = result[column].replace("", pd.NA)
    return result


def load_csv(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(
            path,
            dtype="string",
            keep_default_na=False,
            encoding="utf-8-sig",
            low_memory=False,
        )
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        raise InputFilesError(f"Could not read {path.name}: {error}") from error
    return normalize_frame(frame, path.name)


def load_source_files(raw_dir: Path | str) -> SourceTables:
    root = Path(raw_dir)
    missing = [filename for filename in SOURCE_FILES.values() if not (root / filename).is_file()]
    if missing:
        raise InputFilesError(
            f"Missing required CSV files under {root}: {', '.join(sorted(missing))}"
        )
    return {table: load_csv(root / filename) for table, filename in SOURCE_FILES.items()}


def inspect_schema(sources: SourceTables) -> dict[str, list[dict[str, object]]]:
    report: dict[str, list[dict[str, object]]] = {}
    for table, frame in sources.items():
        report[table] = [
            {
                "column": str(column),
                "dtype": str(frame[column].dtype),
                "null_count": int(frame[column].isna().sum()),
                "distinct_non_null": int(frame[column].nunique(dropna=True)),
            }
            for column in frame.columns
        ]
    return report
