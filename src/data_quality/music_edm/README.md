# data_quality.music_edm

Audio metadata data quality checks for the EDM library, decoupled from file I/O.
The caller supplies an extracted dict of fields (or a DataFrame); this package
validates it. The 16 original checks are organised as an ordered **registry** of
15 named units, runnable individually, as a selectable subset, or across a whole
DataFrame.

```python
from data_quality.music_edm import (
    validate_metadata,  # validate one dict (full suite)
    validate_row,  # validate one dict with include/exclude/auto-skip
    validate_frame,  # validate a pandas DataFrame (optional extra)
    list_checks,  # the ordered check ids
    AudioMetadata,
    BPM_MIN,
    BPM_MAX,
)
```

## Files

- `constants.py` — validation ranges, Camelot key maps, filename character
  replacements (incl. Unicode-dash normalisation), the `AudioFormat` /
  `MetadataField` enums, `CHECK_TYPES`, and `INT_FIELDS`.
- `models.py` — the `AudioMetadata` Pydantic v2 model, `generate_filename`, and
  the config models (`Config`, `MetadataMapping`, `PathConfig`,
  `ValidationConfig`, `AudioFormatEnum`).
- `registry.py` — the check registry: the frozen `Check` / `CheckContext` types,
  the ordered `CHECK_REGISTRY` (15 units), `list_checks()`, and `validate_row`.
- `checks.py` — `validate_metadata(...)` (a thin wrapper over the registry),
  `categorize_issue(...)`, and `EXPECTED_FIELDS`.
- `field_maps.py` — `SourceMap` plus the ready-made `mp3tag_csv` / `itunes_txt`
  maps and the `resolve_source_map` resolver.
- `frame.py` — the optional pandas adapter: `validate_frame` and
  `FrameValidationSummary`.

## Three ways to validate

### 1. One record, full suite — `validate_metadata`

The stable single-item entry point. Runs every check; behaviour is unchanged
from the original implementation.

```python
def validate_metadata(
    fields: dict,
    filename_stem: str,
    file_size_bytes: int | None = None,
) -> ValidationResult: ...
```

- `fields` — canonical field values (see `EXPECTED_FIELDS`). Missing keys are
  treated as `None` and every check still runs.
- `filename_stem` — the file name without extension, for the filename-drift
  check.
- `file_size_bytes` — size of the source file, or `None` if unknown/unreadable.

The returned `ValidationResult` has `passed: bool`, `issues: list[ValidationIssue]`
(each carrying `.code` and `.field`), `fields: dict` of what was validated, and
`skipped: list[str]` (always empty here — nothing auto-skips).

### 2. One record, selectable — `validate_row`

```python
def validate_row(
    fields: dict,
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    filename_stem: str | None = None,
    file_size_bytes: int | None = None,
) -> ValidationResult: ...
```

- `include=None` runs the full registry; `include=[...]` restricts to those
  check ids (always applied in registry order, not caller order).
- `exclude=[...]` removes check ids. **Exclude wins** over include on conflict.
- **Unknown check ids raise `ValueError`**, validated up front. An empty
  `include=[]` also raises (selecting nothing would silently pass everything).
- **Auto-skip**: a check whose required canonical fields are *absent* from
  `fields` (the key is not in the dict at all) does not run and its id is
  recorded in `result.skipped`. A key present but `None` still *runs* the check
  (which then no-ops) — "the column exists but this row is blank" is a pass, not
  a skip.

### 3. A whole DataFrame — `validate_frame` (optional pandas extra)

Origin-independent: CSV, tab-delimited text, or parquet all become a DataFrame
first, then validate identically. Requires the `pandas` extra
(`pip install "data-quality[pandas]"`); importing the package itself never pulls
pandas.

```python
def validate_frame(
    df,  # pandas.DataFrame
    *,
    field_map: Mapping[str, str] | SourceMap | None = None,
    source: str | None = None,  # "mp3tag_csv" | "itunes_txt"
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> FrameValidationSummary: ...
```

`FrameValidationSummary` exposes:

- `total: int` — rows processed
- `passed: int` and `pass_rate: float`
- `issue_counts: Counter[str]` — issue code → count across all rows
- `skipped_checks: set[str]` — union of every row's auto-skipped checks
- `results: list[ValidationResult]` and `row_index: list` — per-row, aligned
- `failures()` — yields `(original_index, result)` for each failing row

```python
import pandas as pd
from data_quality.music_edm import validate_frame

df = pd.read_parquet("tracks.parquet")  # or read_csv / read_table
summary = validate_frame(df, source="mp3tag_csv")

summary.pass_rate  # e.g. 0.98
summary.issue_counts  # Counter({"filename_drift": 71, ...})
summary.skipped_checks  # {"discogs_missing", ...} columns absent for this source
for idx, result in summary.failures():
    print(idx, [i.code for i in result.issues])
```

## Field maps and sources

A `SourceMap` describes how a raw source's columns map to canonical fields
(`columns` is **raw-column → canonical-field**), plus how to derive the filename
stem and file size. Two ship ready to use:

- **`mp3tag_csv`** — MP3Tag semicolon CSV. Carries no `album_artist_sort` and no
  Discogs column, so `missing_fields`, `pydantic_fallback` and `discogs_missing`
  auto-skip.
- **`itunes_txt`** — iTunes tab-delimited export. Carries none of
  bpm/initialkey/encodedby/album_artist/album_artist_sort/subtitle/publisher/
  discogs_id (those checks auto-skip) and no size column (`file_size`
  auto-excluded). Its `album` column holds a Camelot code in this EDM domain; a
  standard iTunes export with real album titles should
  `exclude=["invalid_camelot"]`.

Precedence (via `resolve_source_map`):

- neither `source` nor `field_map` → identity map (canonical names map to
  themselves);
- `source` only → that map as-is;
- `field_map` dict only → a custom map; `field_map` as a `SourceMap` → used
  directly;
- `source` + dict → named map with the dict merged in (dict wins);
- `source` + `SourceMap` → the passed map replaces the named one.

int-like canonical fields (`INT_FIELDS`: `bpm`, `track_number`, `year`,
`discogs_id`, `file_size_bytes`) are coerced from strings; blank/`NaN`/`inf`
cells become `None` rather than raising.

The adapter also **auto-excludes** `file_size` when no size column resolves and
`filename_drift` when no filename column resolves, so neither fires on every row
of a source that cannot supply them. (These are deselections, not auto-skips, so
they don't appear in `skipped_checks`.)

## Canonical fields (`EXPECTED_FIELDS`)

`bpm`, `track_number`, `title`, `artist`, `album`, `initialkey`, `encodedby`,
`album_artist`, `album_artist_sort`, `subtitle`, `publisher`, `grouping`,
`year`, `discogs_id`.

## Checks: ids, required fields, issue codes

`list_checks()` returns these 15 ids in this order. The **id** is the registry
handle (for include/exclude); the **code** is what each issue carries and what
`CHECK_TYPES` / `categorize_issue` key on. They coincide except where noted.

| # | id | required fields (auto-skip if absent) | issue code(s) |
|---|----|----------------------------------------|---------------|
| 1 | `missing_fields` | title, artist, album, initialkey, encodedby, album_artist, album_artist_sort, subtitle, year | `missing_fields` |
| 2 | `bpm_range` | bpm | `value_out_of_range` |
| 3 | `year_range` | year | `value_out_of_range` |
| 4 | `bpm_track_mismatch` | bpm, track_number | `bpm_track_mismatch` |
| 5 | `invalid_camelot` | album | `invalid_camelot` |
| 6 | `corrupted_field` | initialkey | `corrupted_field` |
| 7 | `key_album_mismatch` | initialkey | `invalid_key`, `key_album_mismatch` |
| 8 | `subtitle_drift` | artist, title, album, bpm, year, subtitle | `subtitle_drift` |
| 9 | `filename_drift` | artist, title (+ `filename_stem` runner param) | `filename_drift` |
| 10 | `artist_field_mismatch` | artist | `artist_field_mismatch` |
| 11 | `title_format` | title | `title_format` |
| 12 | `publisher_grouping` | *(none — three internal guards)* | `publisher_grouping` |
| 13 | `discogs_missing` | discogs_id | `discogs_missing` |
| 14 | `file_size` | *(none — uses `file_size_bytes` runner param)* | `file_size` |
| 15 | `pydantic_fallback` | title, artist, album, initialkey, encodedby, album_artist, album_artist_sort, subtitle, year | `pydantic_error` |

Notes:

- `bpm_range` and `year_range` are separate checks that both emit
  `value_out_of_range`. `key_album_mismatch` can emit `invalid_key` and/or
  `key_album_mismatch`. `pydantic_fallback` emits `pydantic_error`.
- Original blocks 12 and 13 (publisher==grouping, and bracketed-number cleanup)
  are merged into the single `publisher_grouping` unit. `invalid_key` is only an
  emitted code of `key_album_mismatch`, never a separate registry id.
- `required` is the set of fields whose **presence** gates running the check;
  each check's own internal guards still decide whether an issue fires.

`CHECK_TYPES` maps each issue code to a dashboard category (`field_presence`,
`value_validity`, `cross_field`, `pydantic`, `file`).

## Constants

```python
BPM_MIN, BPM_MAX  # 100, 200
YEAR_MIN  # 1970
MIN_FILE_SIZE_BYTES  # 100_000
CAMELOT_NOTATIONS  # valid album values
INITIALKEY_NOTATIONS  # valid initialkey values
CAMELOT_KEYS  # album -> expected initialkey
CHARACTER_REPLACEMENTS  # filename sanitisation (incl. Unicode-dash normalisation)
INT_FIELDS  # canonical fields coerced to int by validate_frame
```

## Pydantic model

`AudioMetadata` enforces the same rules declaratively (ranges, Camelot album,
key/album agreement, subtitle and filename format, artist-field agreement). Use
it when you want construction to raise on invalid data; use `validate_metadata`
/ `validate_row` / `validate_frame` when you want a non-raising report of every
issue at once.

## Using it from a consumer (e.g. the music pipeline)

Keep the mutagen reading in the consumer; hand the extracted dict over:

```python
from data_quality.music_edm import validate_metadata

fields = extract_fields_with_mutagen(path)  # your existing code
result = validate_metadata(
    fields,
    filename_stem=path.stem,
    file_size_bytes=path.stat().st_size,
)
```

Or validate a whole export in bulk via `validate_frame(df, source=...)`.
