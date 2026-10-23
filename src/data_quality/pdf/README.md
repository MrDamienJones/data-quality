# data_quality.pdf

PDF data quality checks. **Placeholder — no checks implemented yet.**

When you add them, mirror the `music` subpackage so consumers get a consistent
API across domains:

- `constants.py` — ranges, enums, lookup tables (single source of truth)
- `models.py` — Pydantic v2 models and validators
- `checks.py` — a `validate_*` function that takes an already-extracted dict of
  fields (keep file I/O in the consumer) and returns a
  `data_quality.core.ValidationResult`

Re-export the public API from `__init__.py` so consumers can write
`from data_quality.pdf import validate_...`.

Typical PDF targets to consider: required metadata (title/author), page count
bounds, presence of extractable text vs scanned-image-only, embedded-font
checks, file-size sanity, encryption/permission flags.
