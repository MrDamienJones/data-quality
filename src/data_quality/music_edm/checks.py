"""Read-only music metadata checks, decoupled from file I/O.

The original pipeline validator read tags from disk with mutagen and stat'd the
file. Here the caller does that I/O and passes in:

- ``fields``: a dict of already-extracted canonical fields
- ``filename_stem``: the file name without extension (for filename-drift check)
- ``file_size_bytes``: the file size, or ``None`` if unknown/unreadable

This keeps the shared library free of mutagen and ``pathlib`` I/O so the same
checks run anywhere — a pipeline, a notebook, a test, a different repo.

``validate_metadata`` runs the same 16 checks as the pipeline and returns a
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


def categorize_issue(issue: str) -> tuple[str, str]:
    """Return ``(code, field)`` for an issue.

    Structured :class:`ValidationIssue` values carry their own code. Plain
    strings (e.g. from older logs or mocks) are classified from their text.
    """
    if isinstance(issue, ValidationIssue):
        return issue.code, issue.field

    text = issue.lower()
    if "discogs" in text:
        return "discogs_missing", "discogs_id"
    if "could not read metadata" in text:
        return "unreadable", "file"
    if "missing" in text:
        return "missing_fields", issue.replace("Missing fields: ", "")
    if "bpm" in text and "track" in text:
        return "bpm_track_mismatch", "track_number"
    if "camelot" in text:
        return "invalid_camelot", "album"
    if "corrupt" in text:
        return "corrupted_field", "initialkey"
    if "key" in text and "match" in text:
        return "key_album_mismatch", "initialkey"
    if "key" in text and "notation" in text:
        return "invalid_key", "initialkey"
    if "subtitle" in text:
        return "subtitle_drift", "subtitle"
    if "filename" in text:
        return "filename_drift", "filename"
    if "album_artist" in text:
        return "artist_field_mismatch", "album_artist"
    if "parenthes" in text:
        return "title_format", "title"
    if "publisher" in text or "grouping" in text:
        return "publisher_grouping", "grouping"
    if "pydantic" in text:
        parts = issue.split(":", 2)
        return "pydantic_error", parts[1].strip() if len(parts) > 2 else "unknown"
    if "small file" in text or "file size" in text:
        return "file_size", "file_size"
    if "range" in text:
        return "value_out_of_range", "bpm" if "bpm" in text else "year"
    return "pydantic_error", "unknown"


def validate_metadata(
    fields: dict[str, Any],
    filename_stem: str,
    file_size_bytes: int | None = None,
) -> ValidationResult:
    """Run all music metadata checks on an extracted dict of fields.

    Args:
        fields: canonical field values (see ``EXPECTED_FIELDS``). Missing keys
            are treated as ``None``.
        filename_stem: the file name without its extension, used for the
            filename-drift check.
        file_size_bytes: the size of the source file in bytes, or ``None`` if
            it is unknown or the file was unreadable.

    Returns:
        A :class:`ValidationResult` with ``passed`` and structured ``issues``.
    """
    # Lazy import to break the checks <-> registry cycle (registry imports
    # EXPECTED_FIELDS from this module).
    from .registry import validate_row

    return validate_row(
        fields,
        filename_stem=filename_stem,
        file_size_bytes=file_size_bytes,
        _resolve_all=True,
    )
