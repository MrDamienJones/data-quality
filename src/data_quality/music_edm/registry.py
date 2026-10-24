"""Ordered registry of individually addressable music-metadata checks.

The checks of the original ``validate_metadata`` are held here as 13 named
:class:`Check` units in :data:`CHECK_REGISTRY`, an ordered tuple. Each unit
declares the canonical fields it needs to be *present* to run and a callable
that appends issues to a :class:`ValidationResult`.

:func:`validate_row` runs a selectable subset of the registry over one dict of
fields, auto-skipping checks whose required fields are absent and recording
which checks ran and which were skipped. ``checks.validate_metadata`` is a thin
wrapper over :func:`validate_row`. Design decisions are recorded in
``docs/architecture-checks-registry.md``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError

from ..core.result import ValidationResult
from .checks import EXPECTED_FIELDS
from .constants import (
    BPM_MAX,
    BPM_MIN,
    CAMELOT_KEYS,
    CAMELOT_NOTATIONS,
    INITIALKEY_NOTATIONS,
    INT_FIELDS,
    YEAR_MIN,
)
from .filenames import generate_filename

_INT_ADAPTER = TypeAdapter(int)


def _resolve_int_field(name: str, value: Any, result: ValidationResult) -> int | None:
    """Parse an int-typed canonical field, reporting a bad value as an issue.

    The checks compare these values numerically, so a tag read as text
    (``"128"``) or an integral float is parsed to ``int`` with pydantic's lax
    rules. Blank text is ``None``. A value that cannot be read as an integer
    (``"128a"``, ``128.5``, ``inf``, a bool) is a data quality problem, not a
    crash: it is recorded as a ``pydantic_error`` issue on that field and
    treated as ``None`` by the checks.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        msg = "Input should be a valid integer, got a boolean"
    else:
        try:
            return _INT_ADAPTER.validate_python(value)
        except ValidationError as e:
            msg = e.errors()[0]["msg"]
    result.add_issue(f"Pydantic: {name}: {msg}", "pydantic_error", name)
    return None


@dataclass(frozen=True)
class CheckContext:
    """Inputs a single check callable reads for one validated row.

    ``fields`` is the full resolved canonical dict (every ``EXPECTED_FIELDS``
    key present, ``None`` where the source supplied nothing); callables read
    from it via ``.get()`` so they never ``KeyError``. ``current_year`` is
    captured once per :func:`validate_row` call so every check sees the same
    "now". ``present`` is the set of canonical fields the source supplied (the
    same set the auto-skip gate reads).
    """

    fields: dict[str, Any]
    filename_stem: str | None
    current_year: int
    present: frozenset[str]


@dataclass(frozen=True)
class Check:
    """One addressable check unit in the registry.

    The check runs when every field in ``required`` is present and, if
    ``any_of`` is non-empty, at least one field in ``any_of`` is present.
    """

    id: str
    required: frozenset[str]
    run: Callable[[CheckContext, ValidationResult], None]
    any_of: frozenset[str] = frozenset()

    def can_run(self, present: frozenset[str]) -> bool:
        """``True`` when the fields in ``present`` satisfy this check's gate."""
        if not self.required <= present:
            return False
        return not self.any_of or bool(self.any_of & present)


# --- The 13 check callables ------------------------------------------------


def _check_missing_fields(ctx: CheckContext, result: ValidationResult) -> None:
    # 1. Required fields present. Only the guard fields the source carries are
    # checked, so a source without (say) album_artist_sort still has its blank
    # titles reported. A field already reported as unparseable is not also
    # "missing".
    flagged = result.flagged_fields()
    missing = [
        name
        for name in _GUARD_FIELDS_ORDERED
        if name in ctx.present and not ctx.fields.get(name) and name not in flagged
    ]
    if missing:
        result.add_issue(
            f"Missing fields: {', '.join(missing)}",
            "missing_fields",
            ", ".join(missing),
        )


def _check_bpm_range(ctx: CheckContext, result: ValidationResult) -> None:
    # 2. BPM range
    bpm = ctx.fields.get("bpm")
    if bpm is not None and (bpm < BPM_MIN or bpm > BPM_MAX):
        result.add_issue(
            f"BPM out of range: {bpm} (must be {BPM_MIN}-{BPM_MAX})",
            "value_out_of_range",
            "bpm",
        )


def _check_year_range(ctx: CheckContext, result: ValidationResult) -> None:
    # 3. Year range
    year = ctx.fields.get("year")
    if year is not None and (year < YEAR_MIN or year > ctx.current_year):
        result.add_issue(
            f"Year out of range: {year} (must be {YEAR_MIN}-{ctx.current_year})",
            "value_out_of_range",
            "year",
        )


def _check_bpm_track_mismatch(ctx: CheckContext, result: ValidationResult) -> None:
    # 4. BPM / track number match
    bpm = ctx.fields.get("bpm")
    track = ctx.fields.get("track_number")
    if bpm and track and bpm != track:
        result.add_issue(
            f"BPM ({bpm}) != track number ({track})",
            "bpm_track_mismatch",
            "track_number",
        )


def _check_invalid_camelot(ctx: CheckContext, result: ValidationResult) -> None:
    # 5. Album is valid Camelot notation
    album = ctx.fields.get("album")
    if album and album not in CAMELOT_NOTATIONS:
        result.add_issue(
            f"Album '{album}' is not valid Camelot notation",
            "invalid_camelot",
            "album",
        )


def _check_corrupted_field(ctx: CheckContext, result: ValidationResult) -> None:
    # 6. Initial key corruption (null bytes, slashes)
    key = ctx.fields.get("initialkey")
    corrupted_key = bool(key and ("\x00" in key or "/" in key))
    if corrupted_key:
        result.add_issue(
            f"Corrupted initialkey value: '{repr(key)}'",
            "corrupted_field",
            "initialkey",
        )


def _check_key_album_mismatch(ctx: CheckContext, result: ValidationResult) -> None:
    # 7. Initial key is valid and matches album
    key = ctx.fields.get("initialkey")
    album = ctx.fields.get("album")
    corrupted_key = bool(key and ("\x00" in key or "/" in key))
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
                f"Key '{key}' doesn't match album '{album}' "
                f"(expected '{expected_key}')",
                "key_album_mismatch",
                "initialkey",
            )


def _check_subtitle_drift(ctx: CheckContext, result: ValidationResult) -> None:
    # 8. Subtitle freshness
    artist = ctx.fields.get("artist")
    title = ctx.fields.get("title")
    album = ctx.fields.get("album")
    bpm = ctx.fields.get("bpm")
    year = ctx.fields.get("year")
    subtitle = ctx.fields.get("subtitle")
    if all([artist, title, album, bpm, year]):
        expected_sub = f"{artist} - {title} {album} {bpm} {year}"
        if subtitle and subtitle != expected_sub:
            result.add_issue(
                f"Subtitle drift: got '{subtitle}', expected '{expected_sub}'",
                "subtitle_drift",
                "subtitle",
            )


def _check_filename_drift(ctx: CheckContext, result: ValidationResult) -> None:
    # 9. Filename matches generate_filename
    artist = ctx.fields.get("artist")
    title = ctx.fields.get("title")
    if artist and title:
        try:
            expected_fn = generate_filename(artist, title)
            stem = ctx.filename_stem
            if stem is not None and stem.lower() == expected_fn.lower():
                if stem != expected_fn:
                    # Same name apart from letter case: a separate code so it
                    # can be triaged apart from real content drift.
                    result.add_issue(
                        f"Filename case drift: got '{stem}', expected '{expected_fn}'",
                        "filename_case_drift",
                        "filename",
                    )
            else:
                result.add_issue(
                    f"Filename drift: got '{stem}', expected '{expected_fn}'",
                    "filename_drift",
                    "filename",
                )
        except ValueError as e:
            result.add_issue(
                f"Filename generation error: {e}", "filename_drift", "filename"
            )


def _check_artist_field_mismatch(ctx: CheckContext, result: ValidationResult) -> None:
    # 10. Album artist fields match artist
    artist = ctx.fields.get("artist")
    album_artist = ctx.fields.get("album_artist")
    album_artist_sort = ctx.fields.get("album_artist_sort")
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


def _check_title_format(ctx: CheckContext, result: ValidationResult) -> None:
    # 11. Title contains parentheses
    title = ctx.fields.get("title")
    if title and ("(" not in title or ")" not in title):
        result.add_issue(
            f"Title missing parentheses: '{title}'", "title_format", "title"
        )


def _check_publisher_grouping(ctx: CheckContext, result: ValidationResult) -> None:
    # 12. Publisher/grouping consistency
    publisher = ctx.fields.get("publisher")
    grouping = ctx.fields.get("grouping")
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


def _check_discogs_missing(ctx: CheckContext, result: ValidationResult) -> None:
    # 14. Discogs ID present
    discogs = ctx.fields.get("discogs_id")
    # An unparseable id was already reported; it is not "missing or zero".
    if "discogs_id" in result.flagged_fields():
        return
    if discogs is None or discogs == 0:
        result.add_issue("Discogs ID missing or zero", "discogs_missing", "discogs_id")
    elif discogs < 0:
        result.add_issue(
            f"Discogs ID out of range: {discogs} (must be positive)",
            "value_out_of_range",
            "discogs_id",
        )


# --- The ordered registry ----------------------------------------------------

# Required-field sets use the INTERSECTION rule ("Required-Field Rule" in
# docs/architecture-checks-registry.md): the fields without
# which *no* branch of the check can fire — not the union of every field any
# branch mentions.
_GUARD_FIELDS_ORDERED = (
    "title",
    "artist",
    "album",
    "initialkey",
    "encodedby",
    "album_artist",
    "album_artist_sort",
    "subtitle",
    "year",
)
_GUARD_FIELDS = frozenset(_GUARD_FIELDS_ORDERED)

CHECK_REGISTRY: tuple[Check, ...] = (
    Check("missing_fields", frozenset(), _check_missing_fields, _GUARD_FIELDS),
    Check("bpm_range", frozenset({"bpm"}), _check_bpm_range),
    Check("year_range", frozenset({"year"}), _check_year_range),
    Check(
        "bpm_track_mismatch",
        frozenset({"bpm", "track_number"}),
        _check_bpm_track_mismatch,
    ),
    Check("invalid_camelot", frozenset({"album"}), _check_invalid_camelot),
    Check("corrupted_field", frozenset({"initialkey"}), _check_corrupted_field),
    Check("key_album_mismatch", frozenset({"initialkey"}), _check_key_album_mismatch),
    Check(
        "subtitle_drift",
        frozenset({"artist", "title", "album", "bpm", "year", "subtitle"}),
        _check_subtitle_drift,
    ),
    Check("filename_drift", frozenset({"artist", "title"}), _check_filename_drift),
    Check(
        "artist_field_mismatch",
        frozenset({"artist"}),
        _check_artist_field_mismatch,
    ),
    Check("title_format", frozenset({"title"}), _check_title_format),
    Check("publisher_grouping", frozenset(), _check_publisher_grouping),
    Check("discogs_missing", frozenset({"discogs_id"}), _check_discogs_missing),
)

_REGISTRY_BY_ID: dict[str, Check] = {check.id: check for check in CHECK_REGISTRY}


def list_checks() -> list[str]:
    """Return the registry check ids in execution order."""
    return [check.id for check in CHECK_REGISTRY]


def _validate_ids(ids: Iterable[str], *, param: str) -> None:
    """Raise ``ValueError`` for any id not in the registry."""
    unknown = [check_id for check_id in ids if check_id not in _REGISTRY_BY_ID]
    if unknown:
        raise ValueError(
            f"Unknown check id(s) in {param}: {', '.join(unknown)}. "
            f"Call list_checks() for the valid ids."
        )


def validate_row(
    fields: dict[str, Any],
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    filename_stem: str | None = None,
    _resolve_all: bool = False,
) -> ValidationResult:
    """Run a selectable subset of the registry over one dict of fields.

    Args:
        fields: canonical field values. On this path a key's *presence* (not its
            value) gates whether a check that requires it runs; absent required
            fields auto-skip the check and record its id in ``result.skipped``.
            Int fields (``bpm``, ``track_number``, ``year``, ``discogs_id``)
            accept ints, integral floats or integer strings such as ``"128"``;
            any other value is reported as a ``pydantic_error`` issue.
        include: check ids to run, in registry order. ``None`` runs the full
            registry. An empty iterable is a caller error and raises
            ``ValueError``. Unknown ids raise ``ValueError``.
        exclude: check ids to remove from the selected set. ``exclude`` is
            applied after ``include`` — exclude always wins on conflict. Unknown
            ids raise ``ValueError``; an empty iterable is benign.
        filename_stem: passed to the filename-drift check.

    Returns:
        A :class:`ValidationResult` with ``passed``, structured ``issues``, the
        full canonical ``fields`` snapshot, the ids of the checks that ran in
        ``ran``, and the auto-skipped check ids in ``skipped``.

    Raises:
        ValueError: for unknown/empty include/exclude ids.
    """
    current_year = datetime.now().year

    # Up-front id validation (before any check runs, so an empty-input caller
    # still gets a typo'd id reported).
    if include is not None:
        include = list(include)
        if not include:
            raise ValueError(
                "include must be a non-empty iterable of check ids or None"
            )
        _validate_ids(include, param="include")
    if exclude is not None:
        exclude = list(exclude)
        _validate_ids(exclude, param="exclude")

    include_set = None if include is None else set(include)
    exclude_set = set(exclude or ())

    # Selected ids in registry order, then minus exclude (exclude wins).
    selected = {
        check.id
        for check in CHECK_REGISTRY
        if include_set is None or check.id in include_set
    } - exclude_set

    present = frozenset(EXPECTED_FIELDS) if _resolve_all else frozenset(fields)

    result = ValidationResult()
    result.fields = {
        name: (
            _resolve_int_field(name, fields.get(name), result)
            if name in INT_FIELDS
            else fields.get(name)
        )
        for name in EXPECTED_FIELDS
    }

    ctx = CheckContext(
        fields=result.fields,
        filename_stem=filename_stem,
        current_year=current_year,
        present=present,
    )

    for check in CHECK_REGISTRY:
        if check.id not in selected:
            continue
        if check.can_run(present):
            check.run(ctx, result)
            result.ran.append(check.id)
        else:
            result.skipped.append(check.id)

    return result
