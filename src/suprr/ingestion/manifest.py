from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from suprr.schemas import SOURCE_FILES


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_data_manifest(
    raw_dir: Path | str, sources: dict[str, pd.DataFrame]
) -> list[dict[str, object]]:
    root = Path(raw_dir)
    manifest = []
    for table, filename in SOURCE_FILES.items():
        path = root / filename
        manifest.append(
            {
                "table": table,
                "filename": filename,
                "rows": int(len(sources[table])),
                "columns": list(map(str, sources[table].columns)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return manifest
