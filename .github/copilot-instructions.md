# Project instructions

- Preserve source CSVs and their original headers; normalize only in canonical in-memory tables.
- Keep assumptions in `config/default.yaml` and validate them through `suprr.config`.
- A failed audit or pressure validation gate must block final ranking exports and PDF results.
- Rank only data-derived player IDs joined to verified competition-scoped mappings.
- Run `uv run pytest` and `uv run ruff check .` after code changes.
