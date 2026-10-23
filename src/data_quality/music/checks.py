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

import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from ..core.result import ValidationIssue, ValidationResult
from .constants import (
    BPM_MAX,
    BPM_MIN,
    CAMELOT_KEYS,
    CAMELOT_NOTATIONS,
    INITIALKEY_NOTATIONS,
    MIN_FILE_SIZE_BYTES,
    YEAR_MIN,
)
from .models import AudioMetadata, generate_filename

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


def categorize_issue(issue: str) -> Tuple[str, str]:
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
    fields: Dict[str, Any],
    filename_stem: str,
    file_size_bytes: Optional[int] = None,
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
    result = ValidationResult()
    result.fields = {name: fields.get(name) for name in EXPECTED_FIELDS}

    bpm = result.fields["bpm"]
    track = result.fields["track_number"]
    title = result.fields["title"]
    artist = result.fields["artist"]
    album = result.fields["album"]
    key = result.fields["initialkey"]
    encodedby = result.fields["encodedby"]
    album_artist = result.fields["album_artist"]
    album_artist_sort = result.fields["album_artist_sort"]
    subtitle = result.fields["subtitle"]
    publisher = result.fields["publisher"]
    grouping = result.fields["grouping"]
    year = result.fields["year"]
    discogs = result.fields["discogs_id"]
    current_year = datetime.now().year

    # 1. Required fields present
    required = {
        "title": title,
        "artist": artist,
        "album": album,
        "initialkey": key,
        "encodedby": encodedby,
        "album_artist": album_artist,
        "album_artist_sort": album_artist_sort,
        "subtitle": subtitle,
        "year": year,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        result.add_issue(
            f"Missing fields: {', '.join(missing)}",
            "missing_fields",
            ", ".join(missing),
        )

    # 2. BPM range
    if bpm is not None and (bpm < BPM_MIN or bpm > BPM_MAX):
        result.add_issue(
            f"BPM out of range: {bpm} (must be {BPM_MIN}-{BPM_MAX})",
            "value_out_of_range",
            "bpm",
        )

    # 3. Year range
    if year is not None and (year < YEAR_MIN or year > current_year):
        result.add_issue(
            f"Year out of range: {year} (must be {YEAR_MIN}-{current_year})",
            "value_out_of_range",
            "year",
        )

    # 4. BPM / track number match
    if bpm and track and bpm != track:
        result.add_issue(
            f"BPM ({bpm}) != track number ({track})",
            "bpm_track_mismatch",
            "track_number",
        )

    # 5. Album is valid Camelot notation
    if album and album not in CAMELOT_NOTATIONS:
        result.add_issue(
            f"Album '{album}' is not valid Camelot notation",
            "invalid_camelot",
            "album",
        )

    # 6. Initial key corruption (null bytes, slashes)
    corrupted_key = bool(key and ("\x00" in key or "/" in key))
    if corrupted_key:
        result.add_issue(
            f"Corrupted initialkey value: '{repr(key)}'",
            "corrupted_field",
            "initialkey",
        )

    # 7. Initial key is valid and matches album
    if key and not corrupted_key and key not in INITIALKEY_NOTATIONS:
        result.add_issue(
            f"Initial key '{key}' is not valid notation",
            "invalid_key",
            "initialkey",
        )
    if album and key and not corrupted_key:
        expected_key = CAMELOT_KEYS.get(album)
        if expected_key and key != expected_key:
            result.add_issue(
                f"Key '{key}' doesn't match album '{album}' (expected '{expected_key}')",
                "key_album_mismatch",
                "initialkey",
            )

    # 8. Subtitle freshness
    if all([artist, title, album, bpm, year]):
        expected_sub = f"{artist} - {title} {album} {bpm} {year}"
        if subtitle and subtitle != expected_sub:
            result.add_issue(
                f"Subtitle drift: got '{subtitle}', expected '{expected_sub}'",
                "subtitle_drift",
                "subtitle",
            )

    # 9. Filename matches generate_filename
    if artist and title:
        try:
            expected_fn = generate_filename(artist, title)
            if filename_stem != expected_fn:
                result.add_issue(
                    f"Filename drift: got '{filename_stem}', expected '{expected_fn}'",
                    "filename_drift",
                    "filename",
                )
        except ValueError as e:
            result.add_issue(
                f"Filename generation error: {e}", "filename_drift", "filename"
            )

    # 10. Album artist fields match artist
    if artist:
        if album_artist and album_artist != artist:
            result.add_issue(
                f"album_artist '{album_artist}' != artist '{artist}'",
                "artist_field_mismatch",
                "album_artist",
            )
        if album_artist_sort and album_artist_sort != artist:
            result.add_issue(
                f"album_artist_sort '{album_artist_sort}' != artist '{artist}'",
                "artist_field_mismatch",
                "album_artist_sort",
            )

    # 11. Title contains parentheses
    if title and ("(" not in title or ")" not in title):
        result.add_issue(
            f"Title missing parentheses: '{title}'", "title_format", "title"
        )

    # 12. Publisher/grouping consistency
    if publisher and grouping and publisher != grouping:
        result.add_issue(
            f"Publisher '{publisher}' != grouping '{grouping}'",
            "publisher_grouping",
            "grouping",
        )

    # 13. Publisher/grouping bracket cleanup check
    if publisher and re.search(r"[\(\[]\d+[\)\]]", publisher):
        result.add_issue(
            f"Publisher contains bracketed numbers: '{publisher}'",
            "publisher_grouping",
            "publisher",
        )
    if grouping and re.search(r"[\(\[]\d+[\)\]]", grouping):
        result.add_issue(
            f"Grouping contains bracketed numbers: '{grouping}'",
            "publisher_grouping",
            "grouping",
        )

    # 14. Discogs ID present
    if discogs is None or discogs == 0:
        result.add_issue(
            "Discogs ID missing or zero", "discogs_missing", "discogs_id"
        )

    # 15. File size sanity
    if file_size_bytes is None:
        result.add_issue("Could not read file size", "file_size", "file_size")
    elif file_size_bytes < MIN_FILE_SIZE_BYTES:
        result.add_issue(
            f"Suspiciously small file: {file_size_bytes} bytes",
            "file_size",
            "file_size",
        )

    # 16. Full Pydantic validation — only reports problems on fields the
    # explicit checks above did not already flag, so nothing is counted twice
    if not missing:
        try:
            AudioMetadata(
                bpm=bpm,
                track_number=track,
                publisher=publisher,
                grouping=grouping,
                discogs_id=discogs or 0,
                year=year,
                title=title,
                album=album,
                initialkey=key,
                encodedby=encodedby,
                artist=artist,
                album_artist=album_artist,
                album_artist_sort=album_artist_sort,
                subtitle=subtitle,
                filename=filename_stem,
            )
        except ValidationError as e:
            flagged = result.flagged_fields()
            for error in e.errors():
                field = str(error["loc"][0]) if error.get("loc") else "unknown"
                if field in flagged:
                    continue
                msg = error.get("msg", "validation error")
                result.add_issue(f"Pydantic: {field}: {msg}", "pydantic_error", field)

    return result
