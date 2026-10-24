"""Cross-source reconciliation of two exports of the same library.

``reconcile_frames`` joins two DataFrames (for example an iTunes export and an
mp3tag export) on the file path or the filename stem, then reports:

- tracks present in only one source,
- join keys that are blank or duplicated within a source, and
- canonical fields whose values differ between the two sources.

Each source is described by a :class:`~data_quality.music_edm.field_maps.SourceMap`
(a ready-made ``source`` name or a ``field_map``), exactly as for
``validate_frame``. Like ``validate_frame``, pandas is imported lazily, so
importing this module works without pandas installed.
"""

from __future__ import annotations

import ntpath
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError

from .checks import EXPECTED_FIELDS
from .constants import INT_FIELDS
from .field_maps import SourceMap, resolve_source_map
from .frame import _coerce_str, _derive_stem, _is_missing

_INT_ADAPTER = TypeAdapter(int)

JOIN_KEYS = ("path", "filename")


@dataclass(frozen=True)
class FieldMismatch:
    """One canonical field whose value differs between the two sources.

    ``key`` is the join key as written in the left source. ``left`` and
    ``right`` are the compared values after normalisation (ints parsed, text
    stripped, blanks as ``None``).
    """

    key: str
    field: str
    left: Any
    right: Any


@dataclass
class ReconcileSummary:
    """Result of reconciling two sources.

    Attributes:
        left_name / right_name: the source names (the ``SourceMap`` names).
        on: the join key, ``"path"`` or ``"filename"``.
        fields_compared: canonical fields compared, in canonical order.
        left_total / right_total: rows in each source.
        matched: keys present in both sources.
        only_left / only_right: keys present in one source only.
        duplicate_left / duplicate_right: keys that occur more than once in a
            source. The first occurrence is the one compared.
        missing_key_left / missing_key_right: index values of rows with a blank
            join key, which cannot be matched.
        mismatches: one :class:`FieldMismatch` per differing field per track.
    """

    left_name: str
    right_name: str
    on: str
    fields_compared: list[str]
    left_total: int = 0
    right_total: int = 0
    matched: int = 0
    only_left: list[str] = field(default_factory=list)
    only_right: list[str] = field(default_factory=list)
    duplicate_left: list[str] = field(default_factory=list)
    duplicate_right: list[str] = field(default_factory=list)
    missing_key_left: list[Any] = field(default_factory=list)
    missing_key_right: list[Any] = field(default_factory=list)
    mismatches: list[FieldMismatch] = field(default_factory=list)

    @property
    def mismatch_counts(self) -> Counter[str]:
        """Canonical field -> number of tracks whose values differ."""
        return Counter(m.field for m in self.mismatches)

    @property
    def issue_counts(self) -> Counter[str]:
        """Issue code -> count, using the codes in ``CHECK_TYPES``."""
        counts: Counter[str] = Counter()
        counts["unmatched"] = len(self.only_left) + len(self.only_right)
        counts["duplicate_key"] = len(self.duplicate_left) + len(self.duplicate_right)
        counts["missing_key"] = len(self.missing_key_left) + len(self.missing_key_right)
        counts["cross_source_mismatch"] = len(self.mismatches)
        return +counts  # drop zero counts

    @property
    def passed(self) -> bool:
        """``True`` when the sources match completely."""
        return not self.issue_counts

    def records(self) -> Iterator[dict[str, Any]]:
        """Yield one flat dict per issue, for logs, dashboards or a DataFrame.

        Keys: ``code``, ``key``, ``field``, ``source``, ``left``, ``right``.
        ``source`` names the source the issue is about, or is ``None`` for a
        mismatch, which involves both.
        """
        for code, per_side in (
            ("unmatched", (self.only_left, self.only_right)),
            ("duplicate_key", (self.duplicate_left, self.duplicate_right)),
            ("missing_key", (self.missing_key_left, self.missing_key_right)),
        ):
            for name, keys in zip(
                (self.left_name, self.right_name), per_side, strict=True
            ):
                for key in keys:
                    yield _record(code, str(key), name)
        for m in self.mismatches:
            yield {
                "code": "cross_source_mismatch",
                "key": m.key,
                "field": m.field,
                "source": None,
                "left": m.left,
                "right": m.right,
            }


def _record(code: str, key: str, source: str) -> dict[str, Any]:
    return {
        "code": code,
        "key": key,
        "field": None,
        "source": source,
        "left": None,
        "right": None,
    }


def _normalise(canonical: str, cell: Any) -> Any:
    """A comparable form of a cell: parsed int for int fields, else text.

    An int-field value that cannot be parsed is compared as stripped text, so
    ``"128a"`` on one side and ``128`` on the other still count as different.
    """
    if _is_missing(cell):
        return None
    if canonical in INT_FIELDS:
        text = _coerce_str(cell)
        if text is None:
            return None
        try:
            return _INT_ADAPTER.validate_python(cell)
        except ValidationError:
            return text
    return _coerce_str(cell)


@dataclass
class _Side:
    """One source, resolved against its DataFrame."""

    name: str
    rows: list[tuple[Any, dict[str, Any]]]
    fields: dict[str, str]  # canonical -> raw column
    key_column: str
    source_map: SourceMap

    def key_of(self, row: dict[str, Any], on: str) -> tuple[str, str] | None:
        """``(match_key, display_key)`` for a row, or ``None`` if blank.

        Matching is case-insensitive and treats "/" and "\\" alike, as Windows
        does; the display key keeps the original spelling.
        """
        cell = row.get(self.key_column)
        if on == "path":
            display = _coerce_str(cell)
        else:
            display = _derive_stem(cell, self.source_map)
        if display is None:
            return None
        return ntpath.normcase(display), display


def _resolve_side(df, source: str | None, field_map, on: str, label: str) -> _Side:
    columns = list(df.columns)
    source_map = resolve_source_map(source=source, field_map=field_map, columns=columns)
    available = set(columns)

    key_column = source_map.path_from if on == "path" else source_map.filename_from
    if key_column is None or key_column not in available:
        raise ValueError(
            f"The {label} source '{source_map.name}' has no usable "
            f"{'path' if on == 'path' else 'filename'} column for on={on!r}."
        )

    fields: dict[str, str] = {}
    for raw, canonical in source_map.columns.items():
        if raw in available:
            fields.setdefault(canonical, raw)

    rows = list(zip(df.index, df.to_dict(orient="records"), strict=True))
    return _Side(source_map.name, rows, fields, key_column, source_map)


def _index_rows(
    side: _Side, on: str
) -> tuple[dict[str, tuple[str, dict]], list[str], list[Any]]:
    """Map match key -> (display key, first row); also duplicates and blanks."""
    by_key: dict[str, tuple[str, dict]] = {}
    duplicates: dict[str, str] = {}
    missing: list[Any] = []
    for index, row in side.rows:
        key = side.key_of(row, on)
        if key is None:
            missing.append(index)
            continue
        match_key, display = key
        if match_key in by_key:
            duplicates.setdefault(match_key, display)
        else:
            by_key[match_key] = (display, row)
    return by_key, list(duplicates.values()), missing


def reconcile_frames(
    left,
    right,
    *,
    left_source: str | None = None,
    right_source: str | None = None,
    left_map: Mapping[str, str] | SourceMap | None = None,
    right_map: Mapping[str, str] | SourceMap | None = None,
    on: str = "path",
    fields: Iterable[str] | None = None,
) -> ReconcileSummary:
    """Join two exports of the same library and report where they disagree.

    Args:
        left, right: ``pandas.DataFrame`` objects (not type-annotated to avoid
            importing pandas at module load time).
        left_source, right_source: ready-made source names (``"itunes_txt"``,
            ``"mp3tag_csv"``), resolved as for ``validate_frame``.
        left_map, right_map: a ``field_map`` dict or ``SourceMap`` per side.
        on: ``"path"`` joins on the full file path (``SourceMap.path_from``);
            ``"filename"`` joins on the filename stem (``filename_from``).
            Both match case-insensitively.
        fields: canonical fields to compare. ``None`` compares every canonical
            field that both sources carry.

    Returns:
        A :class:`ReconcileSummary`.

    Raises:
        ImportError: if pandas is not installed.
        ValueError: for an unknown ``on``, a source with no usable key column,
            an unknown field, or a requested field that a source lacks.
    """
    try:
        import pandas as pd  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "reconcile_frames requires the optional 'pandas' extra. "
            'Install it with: pip install "data-quality[pandas]"'
        ) from e

    if on not in JOIN_KEYS:
        raise ValueError(f"on must be one of {', '.join(JOIN_KEYS)}, got {on!r}")

    lside = _resolve_side(left, left_source, left_map, on, "left")
    rside = _resolve_side(right, right_source, right_map, on, "right")

    shared = [f for f in EXPECTED_FIELDS if f in lside.fields and f in rside.fields]
    if fields is None:
        compared = shared
    else:
        compared = list(fields)
        unknown = [f for f in compared if f not in EXPECTED_FIELDS]
        if unknown:
            raise ValueError(f"Unknown canonical field(s): {', '.join(unknown)}")
        lacking = [f for f in compared if f not in shared]
        if lacking:
            raise ValueError(
                f"Field(s) not carried by both sources: {', '.join(lacking)}"
            )

    lrows, ldup, lmissing = _index_rows(lside, on)
    rrows, rdup, rmissing = _index_rows(rside, on)

    summary = ReconcileSummary(
        left_name=lside.name,
        right_name=rside.name,
        on=on,
        fields_compared=compared,
        left_total=len(lside.rows),
        right_total=len(rside.rows),
        duplicate_left=ldup,
        duplicate_right=rdup,
        missing_key_left=lmissing,
        missing_key_right=rmissing,
    )

    for match_key, (display, lrow) in lrows.items():
        if match_key not in rrows:
            summary.only_left.append(display)
            continue
        summary.matched += 1
        _, rrow = rrows[match_key]
        for canonical in compared:
            lval = _normalise(canonical, lrow.get(lside.fields[canonical]))
            rval = _normalise(canonical, rrow.get(rside.fields[canonical]))
            if lval != rval:
                summary.mismatches.append(FieldMismatch(display, canonical, lval, rval))
    summary.only_right = [
        display for match_key, (display, _) in rrows.items() if match_key not in lrows
    ]
    return summary
