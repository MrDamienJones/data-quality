# data_quality.music_edm

Audio metadata data quality checks for the EDM library, decoupled from file I/O.
The caller supplies an extracted dict of fields (or a DataFrame); this package
validates it. The checks are organised as an ordered **registry** of 13 named
units, runnable individually, as a selectable subset, or across a whole
DataFrame.

```python
from data_quality.music_edm import (
    validate_metadata,  # validate one dict (full suite)
    validate_row,  # validate one dict with include/exclude/auto-skip
    validate_frame,  # validate a pandas DataFrame (optional extra)
    list_checks,  # the ordered check ids
    BPM_MIN,
    BPM_MAX,
)
```

## Files

- `constants.py` — validation ranges, Camelot key maps, filename character
  replacements (incl. Unicode dashes and quotes), the `AudioFormat` /
  `MetadataField` enums, `CHECK_TYPES`, and `INT_FIELDS`.
- `filenames.py` — `generate_filename`, which builds the file name stem the
  `filename_drift` check expects.
- `registry.py` — the check registry: the frozen `Check` / `CheckContext` types,
  the ordered `CHECK_REGISTRY` (13 units), `list_checks()`, and `validate_row`.
- `checks.py` — `validate_metadata(...)` (a thin wrapper over the registry),
  `categorize_issue(...)`, and `EXPECTED_FIELDS`.
- `field_maps.py` — `SourceMap` plus the ready-made `mp3tag_csv` / `itunes_txt`
  maps and the `resolve_source_map` resolver.
- `frame.py` — the optional pandas adapter: `validate_frame` and
  `FrameValidationSummary`.
- `reconcile.py` — the cross-source check: `reconcile_frames`,
  `ReconcileSummary` and `FieldMismatch` (optional pandas extra).

## Four ways to validate

### 1. One record, full suite — `validate_metadata`

The stable single-item entry point. Runs every check.

```python
def validate_metadata(
    fields: dict,
    filename_stem: str,
) -> ValidationResult: ...
```

- `fields` — canonical field values (see `EXPECTED_FIELDS`). Missing keys are
  treated as `None` and every check still runs.
- `filename_stem` — the file name without extension, for the filename-drift
  check.

The returned `ValidationResult` has `passed: bool`, `issues: list[ValidationIssue]`
(each carrying `.code` and `.field`), `fields: dict` of what was validated,
`ran: list[str]` (the checks that ran), and `skipped: list[str]` (always empty
here, because nothing auto-skips).

### 2. One record, selectable — `validate_row`

```python
def validate_row(
    fields: dict,
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    filename_stem: str | None = None,
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
  a skip. `missing_fields` is the exception: it runs when at least one of its
  guard fields is present, and checks only the guard fields present.
- `result.ran` lists the checks that ran, in registry order.

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
- `checks_run: set[str]` — checks that ran on at least one row
- `skipped_checks: set[str]` — selected checks that could not run because the
  source lacks their input (including `filename_drift` when the adapter
  excludes it)
- `checks_selected: set[str]` — `checks_run | skipped_checks`, so
  `len(checks_run)` of `len(checks_selected)` is the coverage
- `results: list[ValidationResult]` and `row_index: list` — per-row, aligned
- `failures()` — yields `(original_index, result)` for each failing row

```python
import pandas as pd
from data_quality.music_edm import validate_frame

df = pd.read_parquet("tracks.parquet")  # or read_csv / read_table
summary = validate_frame(df, source="mp3tag_csv")

summary.pass_rate  # e.g. 0.985
summary.issue_counts  # Counter({"filename_case_drift": 36, "filename_drift": 34})
summary.skipped_checks  # {"discogs_missing"}: columns absent for this source
print(f"{len(summary.checks_run)} of {len(summary.checks_selected)} checks ran")
for idx, result in summary.failures():
    print(idx, [i.code for i in result.issues])
```

### 4. Two exports of the same library — `reconcile_frames`

`reconcile_frames` joins two DataFrames on the full file path (or the filename
stem with `on="filename"`) and reports where they disagree. Matching ignores
letter case and slash direction, as Windows does. It needs the `pandas` extra.

```python
from data_quality.music_edm import reconcile_frames

recon = reconcile_frames(
    itunes_df, mp3tag_df, left_source="itunes_txt", right_source="mp3tag_csv"
)
recon.matched  # tracks present in both
recon.only_left, recon.only_right  # tracks in one export only
recon.duplicate_left, recon.missing_key_left  # unusable join keys
recon.mismatch_counts  # Counter({"grouping": 60}): field -> tracks that differ
recon.passed  # True when the exports agree completely
for record in recon.records():  # flat dicts for a log or a DataFrame
    print(record)
```

By default it compares every canonical field that both sources carry (for
`itunes_txt` and `mp3tag_csv`: `track_number`, `title`, `artist`, `album`,
`grouping`, `year`). Pass `fields=[...]` to compare fewer. Int fields compare
as numbers, so `"2020"` equals `2020.0`. A value present on one side and blank
on the other is a mismatch. The issue codes (`unmatched`, `duplicate_key`,
`missing_key`, `cross_source_mismatch`) are in `CHECK_TYPES`.

## Field maps and sources

A `SourceMap` describes how a raw source's columns map to canonical fields
(`columns` is **raw-column → canonical-field**), plus the columns for the filename
stem and the full file path. Two ship ready to use:

- **`mp3tag_csv`** — MP3Tag semicolon CSV. Carries no `album_artist_sort` and no
  Discogs column, so `discogs_missing` auto-skips and `missing_fields` checks
  only the guard fields the export carries.
- **`itunes_txt`** — iTunes tab-delimited export. Carries none of
  bpm/initialkey/encodedby/album_artist/album_artist_sort/subtitle/publisher/
  discogs_id (those checks auto-skip). Its `album` column holds a Camelot code in this EDM domain; a
  standard iTunes export with real album titles should
  `exclude=["invalid_camelot"]`. iTunes shows the content-group tag, which
  mp3tag calls `MTG-GroupDescription`, in its `Work` column, so `Work` maps to
  `grouping`. The iTunes `Grouping` column is a different tag and is not mapped.

Each map also names the column with the full file path (`path_from`:
`MTG-Path` and `Location`), which `reconcile_frames` joins on.

Precedence (via `resolve_source_map`):

- neither `source` nor `field_map` → identity map (canonical names map to
  themselves);
- `source` only → that map as-is;
- `field_map` dict only → a custom map; `field_map` as a `SourceMap` → used
  directly;
- `source` + dict → named map with the dict merged in (dict wins);
- `source` + `SourceMap` → the passed map replaces the named one.

int-like canonical fields (`INT_FIELDS`: `bpm`, `track_number`, `year`,
`discogs_id`) are parsed from strings and integral floats. Blank and `NaN`
cells become `None`. A cell that cannot be read as an integer (for example
`128a`, `128.5` or `inf`) is reported as a `pydantic_error` issue on that
field. It does not raise.

The adapter also **auto-excludes** `filename_drift` when no filename column
resolves, so it does not fire on every row of a source that cannot supply one.
It then appears in `skipped_checks`, unless you excluded it yourself.

## Canonical fields (`EXPECTED_FIELDS`)

`bpm`, `track_number`, `title`, `artist`, `album`, `initialkey`, `encodedby`,
`album_artist`, `album_artist_sort`, `subtitle`, `publisher`, `grouping`,
`year`, `discogs_id`.

## Checks: ids, required fields, issue codes

`list_checks()` returns these 13 ids in this order. The **id** is the registry
handle (for include/exclude); the **code** is what each issue carries and what
`CHECK_TYPES` / `categorize_issue` key on. They coincide except where noted.

| # | id | required fields (auto-skip if absent) | issue code(s) |
|---|----|----------------------------------------|---------------|
| 1 | `missing_fields` | at least one of: title, artist, album, initialkey, encodedby, album_artist, album_artist_sort, subtitle, year | `missing_fields` |
| 2 | `bpm_range` | bpm | `value_out_of_range` |
| 3 | `year_range` | year | `value_out_of_range` |
| 4 | `bpm_track_mismatch` | bpm, track_number | `bpm_track_mismatch` |
| 5 | `invalid_camelot` | album | `invalid_camelot` |
| 6 | `corrupted_field` | initialkey | `corrupted_field` |
| 7 | `key_album_mismatch` | initialkey | `invalid_key`, `key_album_mismatch` |
| 8 | `subtitle_drift` | artist, title, album, bpm, year, subtitle | `subtitle_drift` |
| 9 | `filename_drift` | artist, title (+ `filename_stem` runner param) | `filename_drift`, `filename_case_drift` |
| 10 | `artist_field_mismatch` | artist | `artist_field_mismatch` |
| 11 | `title_format` | title | `title_format` |
| 12 | `publisher_grouping` | *(none — three internal guards)* | `publisher_grouping` |
| 13 | `discogs_missing` | discogs_id | `discogs_missing`, `value_out_of_range` (negative id) |

Notes:

- `bpm_range` and `year_range` are separate checks that both emit
  `value_out_of_range`. `key_album_mismatch` can emit `invalid_key` and/or
  `key_album_mismatch`.
- `filename_drift` emits `filename_case_drift` when the file name matches the
  expected name apart from letter case, and `filename_drift` for any other
  difference.
- `pydantic_error` is the code for an int field whose value cannot be read as
  an integer (see above). No check has that id.
- Original blocks 12 and 13 (publisher==grouping, and bracketed-number cleanup)
  are merged into the single `publisher_grouping` unit. `invalid_key` is only an
  emitted code of `key_album_mismatch`, never a separate registry id.
- `required` is the set of fields whose **presence** gates running the check;
  each check's own internal guards still decide whether an issue fires.

`CHECK_TYPES` maps each issue code to a dashboard category (`field_presence`,
`value_validity`, `cross_field`, `pydantic`, `file`, and `join` /
`cross_source` for the `reconcile_frames` codes). `file` holds `unreadable`,
which a consumer records when it cannot read a file's tags.

## Constants

```python
BPM_MIN, BPM_MAX  # 100, 200
YEAR_MIN  # 1970
CAMELOT_NOTATIONS  # valid album values
INITIALKEY_NOTATIONS  # valid initialkey values
CAMELOT_KEYS  # album -> expected initialkey
CHARACTER_REPLACEMENTS  # filename sanitisation (incl. Unicode dashes and quotes)
INT_FIELDS  # fields parsed to int (pydantic_error issue if unparseable)
```

## Using it from a consumer (e.g. the music pipeline)

Keep the mutagen reading in the consumer; hand the extracted dict over:

```python
from data_quality.music_edm import validate_metadata

fields = extract_fields_with_mutagen(path)  # your existing code
result = validate_metadata(fields, filename_stem=path.stem)
```

Or validate a whole export in bulk via `validate_frame(df, source=...)`.
