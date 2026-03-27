# Scripts

This directory is organized by intent so the top-level entrypoints stay easy to find.

## Top-level entrypoints

- `scripts/dev.ps1`: PowerShell helper for setup, API, CLI, tests, lint, and typecheck.
- `scripts/run_api.py`: API server launcher used by the docs.

## Subdirectories

- `scripts/db/`: active database setup, migration, and repair scripts.
- `scripts/tools/`: active developer utilities that operate on current code/data.
- `scripts/manual/`: one-off manual helpers and ad hoc verification scripts.
- `scripts/legacy/`: outdated or superseded scripts kept only for historical reference.

## Maintenance rules

- Default static checks exclude `deprecated/`, `scripts/manual/`, and `scripts/legacy/`.
- New reusable scripts should go in `db/` or `tools/`.
- One-off investigation helpers should go in `manual/`.
- Superseded scripts should move to `legacy/` instead of staying mixed with active tools.
