"""Read-only music metadata checks, decoupled from file I/O.

The original pipeline validator read tags from disk with mutagen. Here the
caller does that I/O and passes in:

- ``fields``: a dict of already-extracted canonical fields
- ``filename_stem``: the file name without extension (for filename-drift check)

This keeps the shared library free of mutagen and ``pathlib`` I/O so the same
checks run anywhere — a pipeline, a notebook, a test, a different repo.

``validate_metadata`` runs every check in the registry and returns a
:class:`~data_quality.core.result.ValidationResult`.
"""

from __future__ import annotations

from typing import Any

from ..core.result import ValidationIssue, ValidationResult

# Canonical field names the checks expect in the input dict.
EXPECTED_FIELDS = (
    "bpm",
    "track_number",
    "title",
    "artist",
    "album",
    "initialkey",
    "encodedby",
    "album_artist",
    "album_artist_sort",
    "subtitle",
    "publisher",
    "grouping",
    "year",
    "discogs_id",
)


# Plain-string classification: each check's message starts with a fixed
# prefix, so matching the start of the message cannot be misled by track data
# inside it (a title such as "Missing (Mix)" or an artist named "Camelot").
# Longer prefixes that share a start come first.
_MESSAGE_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("Could not read metadata", "unreadable", "file"),
    ("Missing fields: ", "missing_fields", ""),
    ("BPM out of range", "value_out_of_range", "bpm"),
    ("Track number out of range", "value_out_of_range", "track_number"),
    ("Year out of range", "value_out_of_range", "year"),
    ("Discogs ID out of range", "value_out_of_range", "discogs_id"),
    ("Discogs ID missing", "discogs_missing", "discogs_id"),
    ("BPM (", "bpm_track_mismatch", "track_number"),
    ("Album '", "invalid_camelot", "album"),
    ("Corrupted initialkey", "corrupted_field", "initialkey"),
    ("Initial key '", "invalid_key", "initialkey"),
    ("Key '", "key_album_mismatch", "initialkey"),
    ("Subtitle drift", "subtitle_drift", "subtitle"),
    ("Filename case drift", "filename_case_drift", "filename"),
    ("Filename drift", "filename_drift", "filename"),
    ("album_artist_sort '", "artist_field_mismatch", "album_artist_sort"),
    ("album_artist '", "artist_field_mismatch", "album_artist"),
    ("Title missing parentheses", "title_format", "title"),
    ("Publisher contains", "bracketed_numbers", "publisher"),
    ("Grouping contains", "bracketed_numbers", "grouping"),
    ("Publisher '", "publisher_grouping", "grouping"),
)


def categorize_issue(issue: str) -> tuple[str, str]:
    """Return ``(code, field)`` for an issue.

    Structured :class:`ValidationIssue` values carry their own code. Plain
    strings (e.g. from older logs) are classified by the fixed prefix that
    starts each check's message. An unrecognised string is
    ``("pydantic_error", "unknown")``.
    """
    if isinstance(issue, ValidationIssue):
        return issue.code, issue.field

    for prefix, code, field in _MESSAGE_PREFIXES:
        if issue.startswith(prefix):
            if code == "missing_fields":
                return code, issue.removeprefix(prefix)
            return code, field
    if issue.startswith("Pydantic: "):
        parts = issue.split(":", 2)
        return "pydantic_error", parts[1].strip() if len(parts) > 2 else "unknown"
    return "pydantic_error", "unknown"


def validate_metadata(
    fields: dict[str, Any],
    filename_stem: str,
) -> ValidationResult:
    """Run all music metadata checks on an extracted dict of fields.

    Args:
        fields: canonical field values (see ``EXPECTED_FIELDS``). Missing keys
            are treated as ``None``. Int fields accept integer strings such as
            ``"128"``; a value that cannot be read as an integer is reported
            as a ``pydantic_error`` issue.
        filename_stem: the file name without its extension, used for the
            filename-drift check.

    Returns:
        A :class:`ValidationResult` with ``passed`` and structured ``issues``.
    """
    # Lazy import to break the checks <-> registry cycle (registry imports
    # EXPECTED_FIELDS from this module).
    from .registry import validate_row

    return validate_row(
        fields,
        filename_stem=filename_stem,
        _resolve_all=True,
    )
