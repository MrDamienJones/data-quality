"""Optional pandas DataFrame adapter for the music-metadata checks.

``validate_frame`` maps a DataFrame's columns onto canonical fields (via a
:class:`~data_quality.music_edm.field_maps.SourceMap`) and aggregates per-row
:class:`~data_quality.core.result.ValidationResult` objects into a
:class:`FrameValidationSummary`. This lets the exact same checks run against a
CSV, a tab-delimited export or a parquet file — origin-independent, as long as
the data arrives as a DataFrame.

pandas is an **optional** dependency. It is imported LAZILY, inside
``validate_frame`` only — never at module top level — so importing this module
(and the package) works with pandas uninstalled. pandas is only required when
``validate_frame`` is actually called; install it with::

    pip install "data-quality[pandas]"
"""

from __future__ import annotations

import ntpath
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..core.result import ValidationResult
from .constants import INT_FIELDS
from .field_maps import SourceMap, resolve_source_map
from .registry import validate_row


@dataclass
class FrameValidationSummary:
    """Aggregated result of validating every row of a DataFrame.

    ``results[i]`` corresponds to ``row_index[i]`` — both are aligned to the
    DataFrame's row order. No pandas types appear in the signature, so this type
    is importable without pandas installed.

    Attributes:
        total: rows processed.
        passed: rows whose result passed.
        results: per-row results, aligned to ``row_index``.
        row_index: original DataFrame index values, aligned to ``results``.
        issue_counts: ``ValidationIssue.code`` -> count across all rows.
        checks_run: union of every row's ran check ids.
        skipped_checks: selected checks that could not run because the source
            lacks their input: every row's auto-skipped ids, plus
            ``filename_drift`` when the adapter excluded it for want of a
            filename column.
    """

    total: int = 0
    passed: int = 0
    results: list[ValidationResult] = field(default_factory=list)
    row_index: list[Any] = field(default_factory=list)
    issue_counts: Counter[str] = field(default_factory=Counter)
    checks_run: set[str] = field(default_factory=set)
    skipped_checks: set[str] = field(default_factory=set)

    @property
    def pass_rate(self) -> float:
        """Fraction of rows that passed, ``0.0`` when no rows were processed."""
        return self.passed / self.total if self.total else 0.0

    @property
    def checks_selected(self) -> set[str]:
        """Checks the caller selected: those that ran plus those skipped."""
        return self.checks_run | self.skipped_checks

    def failures(self) -> Iterator[tuple[Any, ValidationResult]]:
        """Yield ``(original_index, result)`` for each failing row."""
        for index, result in zip(self.row_index, self.results, strict=True):
            if not result.passed:
                yield index, result


def _is_missing(value: Any) -> bool:
    """``True`` for ``None``/``NaN``/``pd.NA``/``NaT`` (the single missing gate).

    Called only from inside ``validate_frame`` (after pandas is imported).
    """
    import pandas as pd

    return value is None or bool(pd.isna(value))


def _coerce_str(value: Any) -> str | None:
    """Coerce a DataFrame cell to ``str | None`` using the same missing gate.

    Blank-after-strip becomes ``None``. Called only from inside
    ``validate_frame`` (after pandas is imported).
    """
    import pandas as pd

    if value is None:
        return None
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _derive_stem(cell: Any, source_map: SourceMap) -> str | None:
    """The filename stem from a filename cell, per the map's rules.

    Called only from inside pandas-using functions (after pandas is imported).
    """
    stem = _coerce_str(cell)
    if stem is None:
        return None
    if source_map.filename_basename:
        # ntpath splits on both "\" and "/", so a Windows path from an iTunes
        # export works on any OS (posixpath ignores "\").
        stem = ntpath.basename(stem)
    if source_map.filename_strip_suffix:
        stem = stem.removesuffix(source_map.filename_strip_suffix)
    return stem


def validate_frame(
    df,
    *,
    field_map: Mapping[str, str] | SourceMap | None = None,
    source: str | None = None,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> FrameValidationSummary:
    """Validate every row of a DataFrame, aggregating per-row results.

    Args:
        df: a ``pandas.DataFrame`` (not type-annotated to avoid importing pandas
            at module load time).
        field_map: a plain ``dict`` (raw-column -> canonical) or a
            :class:`SourceMap`, or ``None``. See ``resolve_source_map``.
        source: a ready-made source key (``"mp3tag_csv"`` / ``"itunes_txt"``), or
            ``None``. An unknown key raises ``ValueError``.
        include: check ids to run (registry order). ``None`` runs the full
            registry. Unknown ids / an empty iterable raise ``ValueError`` — even
            on an empty frame.
        exclude: check ids to remove. The adapter also auto-excludes
            ``filename_drift`` when no filename column resolves, so it does not
            fire spuriously on every row. It is then listed in ``skipped_checks``.

    Returns:
        A :class:`FrameValidationSummary`.

    Raises:
        ImportError: if pandas is not installed.
        ValueError: for an unknown source or unknown/empty include/exclude ids.
    """
    try:
        import pandas as pd  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "validate_frame requires the optional 'pandas' extra. "
            'Install it with: pip install "data-quality[pandas]"'
        ) from e

    columns = list(df.columns)

    # Validate the caller's raw include/exclude up front, before any row loop,
    # so a typo raises even on an empty frame. This mirrors validate_row's
    # up-front check; the auto-added ids below are always valid and never trip it.
    if include is not None:
        include = list(include)
        if not include:
            raise ValueError(
                "include must be a non-empty iterable of check ids or None"
            )
    # Materialise exclude too: a one-shot iterator would be consumed by the
    # validation call below and silently lost before the row loop.
    if exclude is not None:
        exclude = list(exclude)
    validate_row({}, include=include, exclude=exclude)

    # Resolve the (source, field_map) pair into one effective SourceMap.
    source_map = resolve_source_map(source=source, field_map=field_map, columns=columns)

    available = set(columns)
    # Drop mapped columns absent from the DataFrame (lenient default, see
    # "Missing Columns" in docs/architecture-checks-registry.md): their
    # canonical fields are never inserted, so dependent checks auto-skip.
    effective_columns = {
        raw: canonical
        for raw, canonical in source_map.columns.items()
        if raw in available
    }
    # The filename derivation is NOT a member of columns; null it if it names a
    # column absent from the DataFrame.
    filename_from = (
        source_map.filename_from if source_map.filename_from in available else None
    )

    # effective_exclude = caller exclude + the filename_drift auto-exclude when
    # no filename column resolved.
    auto_excluded: set[str] = set()
    if filename_from is None:
        auto_excluded.add("filename_drift")
    effective_exclude = set(exclude or ()) | auto_excluded

    summary = FrameValidationSummary()
    # An auto-excluded check the caller selected could not run for lack of a
    # column, so report it as skipped rather than hiding it.
    summary.skipped_checks = {
        check_id
        for check_id in auto_excluded - set(exclude or ())
        if include is None or check_id in include
    }

    for idx, row in zip(df.index, df.to_dict(orient="records"), strict=True):
        fields: dict[str, Any] = {}
        for raw, canonical in effective_columns.items():
            cell = row.get(raw)
            if canonical in INT_FIELDS:
                # Only the missing gate here: validate_row parses the value and
                # reports an unparseable one as a pydantic_error issue.
                fields[canonical] = None if _is_missing(cell) else cell
            else:
                fields[canonical] = _coerce_str(cell)

        stem = (
            _derive_stem(row.get(filename_from), source_map)
            if filename_from is not None
            else None
        )

        result = validate_row(
            fields,
            include=include,
            exclude=effective_exclude,
            filename_stem=stem,
        )

        summary.total += 1
        summary.results.append(result)
        summary.row_index.append(idx)
        if result.passed:
            summary.passed += 1
        for issue in result.issues:
            summary.issue_counts[issue.code] += 1
        summary.checks_run.update(result.ran)
        summary.skipped_checks.update(result.skipped)

    return summary
