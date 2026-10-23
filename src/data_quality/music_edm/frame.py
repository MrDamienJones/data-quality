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

import math
import os
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
        skipped_checks: union of every row's auto-skipped check ids.
    """

    total: int = 0
    passed: int = 0
    results: list[ValidationResult] = field(default_factory=list)
    row_index: list[Any] = field(default_factory=list)
    issue_counts: Counter[str] = field(default_factory=Counter)
    skipped_checks: set[str] = field(default_factory=set)

    @property
    def pass_rate(self) -> float:
        """Fraction of rows that passed, ``0.0`` when no rows were processed."""
        return self.passed / self.total if self.total else 0.0

    def failures(self) -> Iterator[tuple[Any, ValidationResult]]:
        """Yield ``(original_index, result)`` for each failing row."""
        for index, result in zip(self.row_index, self.results, strict=True):
            if not result.passed:
                yield index, result


def _coerce_int(value: Any) -> int | None:
    """Coerce a DataFrame cell to ``int | None`` (design §5).

    Handles Python/numpy ints and floats, pandas/numpy missing scalars
    (``None``/``NaN``/``pd.NA``/``NaT`` via the single ``pd.isna`` gate), and
    string cells. An unparseable or fractional value coerces to ``None`` rather
    than raising, so one dirty cell never aborts the whole frame. Called only
    from inside ``validate_frame`` (after pandas is imported).
    """
    import pandas as pd

    # 1. Fast-path only — NOT the sole missing gate (see step 2).
    if value is None:
        return None
    # 2. The single missing-value test (covers NaN, pd.NA, NaT).
    if pd.isna(value):
        return None
    # 3. A bool is never a valid int field.
    if isinstance(value, bool):
        return None
    # 4. Integers (incl. non-bool numpy integers).
    if isinstance(value, int):
        return int(value)
    # 5. Floats: use only when integral and finite.
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value == int(value):
            return int(value)
        return None
    # 6. Strings: strip then parse.
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except (ValueError, TypeError):
            return None
    # 7. Anything else.
    return None


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
            ``file_size`` when no size column resolves and ``filename_drift`` when
            no filename column resolves, so neither fires spuriously on every row.

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
    validate_row({}, include=include, exclude=exclude)

    # Resolve the (source, field_map) pair into one effective SourceMap.
    source_map = resolve_source_map(source=source, field_map=field_map, columns=columns)

    available = set(columns)
    # Drop mapped columns absent from the DataFrame (lenient default, Q3): their
    # canonical fields are never inserted, so dependent checks auto-skip.
    effective_columns = {
        raw: canonical
        for raw, canonical in source_map.columns.items()
        if raw in available
    }
    # The two structural derivations are NOT members of columns; null them if
    # they name a column absent from the DataFrame (design §4 step 2).
    filename_from = (
        source_map.filename_from if source_map.filename_from in available else None
    )
    size_from = source_map.size_from if source_map.size_from in available else None

    # effective_exclude = caller exclude + runner-parameter auto-excludes
    # (file_size / filename_drift) whose source column did not resolve.
    effective_exclude = set(exclude or ())
    if size_from is None:
        effective_exclude |= {"file_size"}
    if filename_from is None:
        effective_exclude |= {"filename_drift"}

    summary = FrameValidationSummary()

    for idx, row in zip(df.index, df.to_dict(orient="records"), strict=True):
        fields: dict[str, Any] = {}
        for raw, canonical in effective_columns.items():
            cell = row.get(raw)
            if canonical in INT_FIELDS:
                fields[canonical] = _coerce_int(cell)
            else:
                fields[canonical] = _coerce_str(cell)

        stem: str | None = None
        if filename_from is not None:
            stem = _coerce_str(row.get(filename_from))
            if stem is not None:
                if source_map.filename_basename:
                    stem = os.path.basename(stem)
                if source_map.filename_strip_suffix:
                    stem = stem.removesuffix(source_map.filename_strip_suffix)

        size = _coerce_int(row.get(size_from)) if size_from is not None else None

        result = validate_row(
            fields,
            include=include,
            exclude=effective_exclude,
            filename_stem=stem,
            file_size_bytes=size,
        )

        summary.total += 1
        summary.results.append(result)
        summary.row_index.append(idx)
        if result.passed:
            summary.passed += 1
        for issue in result.issues:
            summary.issue_counts[issue.code] += 1
        summary.skipped_checks.update(result.skipped)

    return summary
