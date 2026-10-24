"""Ready-made source field maps for the pandas adapter.

A :class:`SourceMap` describes how a raw tabular source (an mp3tag CSV export,
an iTunes text export, ...) maps its columns onto the canonical field names the
checks expect, plus the "special" columns for the filename stem and the
full file path.

Two maps ship ready to use: :data:`mp3tag_csv` and :data:`itunes_txt`. Consuming
repos get a single source of truth for both the checks and the column mappings.
The :func:`resolve_source_map` resolver turns a ``(source, field_map)`` pair into
one effective :class:`SourceMap` following the precedence rules in
``docs/architecture-checks-registry.md`` ("Precedence of source and field_map").
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field

from .checks import EXPECTED_FIELDS


@dataclass(frozen=True)
class SourceMap:
    """Describes how a raw tabular source maps to canonical fields.

    The ``columns`` convention is **raw-column-name -> canonical-field-name**
    (same direction as a ``field_map`` dict passed to ``validate_frame``).
    ``path_from`` names the column holding the full file path; the
    ``reconcile_frames`` cross-source check joins two sources on it.
    """

    name: str
    columns: dict[str, str] = field(default_factory=dict)
    filename_from: str | None = None
    filename_strip_suffix: str = ".mp3"
    filename_basename: bool = False
    path_from: str | None = None


mp3tag_csv = SourceMap(
    name="mp3tag_csv",
    columns={
        "MTG-Title": "title",
        "MTG-Subtitle": "subtitle",
        "MTG-Artist": "artist",
        "MTG-AlbumArtist": "album_artist",
        "MTG-Album": "album",
        "MTG-Year": "year",
        "MTG-TrackNumber": "track_number",
        "MTG-Publisher": "publisher",
        "MTG-EncodedBy": "encodedby",
        "MTG-GroupDescription": "grouping",
        "MTG-InitialKey": "initialkey",
        "MTG-BPM": "bpm",
    },
    filename_from="MTG-Filename",
    filename_strip_suffix=".mp3",
    filename_basename=False,
    path_from="MTG-Path",
)
"""mp3tag CSV export.

Carries no ``album_artist_sort`` and no Discogs column, so ``discogs_missing``
auto-skips and ``missing_fields`` checks only the guard fields it does carry.
"""


itunes_txt = SourceMap(
    name="itunes_txt",
    columns={
        "Name": "title",
        "Artist": "artist",
        "Album": "album",
        "Work": "grouping",  # iTunes shows the content-group tag (TIT1) as Work
        "Track Number": "track_number",
        "Year": "year",
    },
    filename_from="Location",
    filename_strip_suffix=".mp3",
    filename_basename=True,
    path_from="Location",
)
"""iTunes text export.

Camelot ``album`` caveat: the ``invalid_camelot`` check treats canonical
``album`` as a Camelot code, because in this EDM domain the "album" tag carries
the Camelot key notation rather than a human album title. A genuine iTunes
"Album" column holds real album titles, so ``invalid_camelot`` will fire on
essentially every iTunes row. The mapping is kept so libraries that *do* use
Camelot album codes still validate; standard iTunes exports should opt out::

    validate_frame(df, source="itunes_txt", exclude=["invalid_camelot"])

This source carries none of bpm/initialkey/encodedby/album_artist/
album_artist_sort/subtitle/publisher/discogs_id, so the checks needing those
auto-skip.
"""


_SOURCES: dict[str, SourceMap] = {
    "mp3tag_csv": mp3tag_csv,
    "itunes_txt": itunes_txt,
}


def resolve_source_map(
    *,
    source: str | None = None,
    field_map: Mapping[str, str] | SourceMap | None = None,
    columns: list[str] | None = None,
) -> SourceMap:
    """Resolve a ``(source, field_map)`` pair into one effective ``SourceMap``.

    Implements the six precedence cases in ``docs/architecture-checks-registry.md``:

    1. Both ``None`` -> identity source mapping each canonical name to itself;
       ``filename_from``/``path_from`` are set only when their column is present
       in ``columns``.
    2. ``source`` only -> the named :class:`SourceMap` as-is.
    3. ``field_map`` only as a plain dict -> a ``custom`` :class:`SourceMap`.
    4. ``field_map`` only as a :class:`SourceMap` -> used directly.
    5. ``source`` + plain dict -> named map with ``columns`` merged (dict wins),
       structural fields inherited from the base.
    6. ``source`` + :class:`SourceMap` -> the passed map replaces the base.

    Args:
        source: a key in ``_SOURCES`` (``"mp3tag_csv"`` or ``"itunes_txt"``), or
            ``None``. An unknown key raises ``ValueError``.
        field_map: a plain ``dict`` (raw-column -> canonical) or a
            :class:`SourceMap`, or ``None``.
        columns: the available raw column names (e.g. ``df.columns``), used only
            to set the identity source's structural fields conditionally.

    Returns:
        The effective :class:`SourceMap` (a new instance; frozen maps are never
        mutated).
    """
    base: SourceMap | None = None
    if source is not None:
        if source not in _SOURCES:
            raise ValueError(
                f"Unknown source '{source}'. "
                f"Valid sources: {', '.join(sorted(_SOURCES))}."
            )
        base = _SOURCES[source]

    if field_map is None:
        if base is not None:
            # Case 2: source only.
            return base
        # Case 1: identity source.
        available = set(columns or ())
        return SourceMap(
            name="identity",
            columns={name: name for name in EXPECTED_FIELDS},
            filename_from="filename_stem" if "filename_stem" in available else None,
            path_from="path" if "path" in available else None,
        )

    if isinstance(field_map, SourceMap):
        # Cases 4 & 6: a SourceMap replaces any base entirely.
        return field_map

    # field_map is a plain mapping of raw-column -> canonical.
    overrides = dict(field_map)
    if base is not None:
        # Case 5: merge into the named base (override wins), inherit structure.
        return dataclasses.replace(base, columns={**base.columns, **overrides})
    # Case 3: custom source from the dict alone.
    return SourceMap(name="custom", columns=overrides)
