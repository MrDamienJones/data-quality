"""PDF data quality checks (placeholder).

No checks are implemented yet. When you add them, follow the ``music_edm``
subpackage layout:

- ``constants.py`` — ranges, enums, lookup tables (single source of truth)
- ``models.py``    — Pydantic v2 models and validators
- ``checks.py``    — a ``validate_*`` function that takes an already-extracted
  dict of fields (keep file I/O in the consumer) and returns a
  :class:`data_quality.core.result.ValidationResult`

Re-export the public API from this ``__init__`` so consumers can
``from data_quality.pdf import validate_...``.
"""

__all__: list[str] = []
