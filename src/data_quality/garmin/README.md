# data_quality.garmin

Garmin-file data quality checks. **Placeholder — no checks implemented yet.**

When you add them, mirror the `music` subpackage so consumers get a consistent
API across domains:

- `constants.py` — ranges, enums, lookup tables (single source of truth)
- `models.py` — Pydantic v2 models and validators
- `checks.py` — a `validate_*` function that takes an already-extracted dict of
  fields (keep file I/O in the consumer) and returns a
  `data_quality.core.ValidationResult`

Re-export the public API from `__init__.py` so consumers can write
`from data_quality.garmin import validate_...`.

Typical Garmin targets to consider: `.fit` / `.tcx` / `.gpx` activity files —
timestamp monotonicity, plausible GPS coordinates, heart-rate / cadence /
power ranges, elapsed-vs-moving-time consistency.
