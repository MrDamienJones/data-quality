# data_quality.music

Audio metadata data quality checks, ported from the music file pipeline and
decoupled from file I/O. The caller reads the file and passes an extracted dict
of fields; this package validates it.

```python
from data_quality.music import validate_metadata, AudioMetadata, BPM_MIN, BPM_MAX
```

## Files

- `constants.py` — validation ranges, Camelot key maps, filename character
  replacements, the `AudioFormat` / `MetadataField` enums, and `CHECK_TYPES`.
- `models.py` — the `AudioMetadata` Pydantic v2 model, `generate_filename`, and
  the config models (`Config`, `MetadataMapping`, `PathConfig`,
  `ValidationConfig`, `AudioFormatEnum`).
- `checks.py` — `validate_metadata(...)` runs the full suite and returns a
  `ValidationResult`; `categorize_issue(...)` classifies a plain-string issue;
  `EXPECTED_FIELDS` lists the canonical field names.

## `validate_metadata`

```python
def validate_metadata(
    fields: dict,
    filename_stem: str,
    file_size_bytes: int | None = None,
) -> ValidationResult: ...
```

- `fields` — canonical field values (see `EXPECTED_FIELDS`). Missing keys are
  treated as `None`.
- `filename_stem` — the file name without extension, for the filename-drift
  check.
- `file_size_bytes` — size of the source file, or `None` if unknown/unreadable.

The returned `ValidationResult` has `passed: bool`, `issues: list[ValidationIssue]`
(each carrying `.code` and `.field`), and `fields: dict` of what was validated.

### Canonical fields (`EXPECTED_FIELDS`)

`bpm`, `track_number`, `title`, `artist`, `album`, `initialkey`, `encodedby`,
`album_artist`, `album_artist_sort`, `subtitle`, `publisher`, `grouping`,
`year`, `discogs_id`.

## Checks and their issue codes

| # | Check | Issue code |
|---|-------|------------|
| 1 | Required fields present | `missing_fields` |
| 2 | BPM within `BPM_MIN`–`BPM_MAX` | `value_out_of_range` |
| 3 | Year within `YEAR_MIN`–current year | `value_out_of_range` |
| 4 | BPM equals track number (when both set) | `bpm_track_mismatch` |
| 5 | Album is valid Camelot notation | `invalid_camelot` |
| 6 | Initial key not corrupted (no null bytes / slashes) | `corrupted_field` |
| 7 | Initial key valid and matches album | `invalid_key`, `key_album_mismatch` |
| 8 | Subtitle matches `Artist - Title Album BPM Year` | `subtitle_drift` |
| 9 | Filename matches `generate_filename(artist, title)` | `filename_drift` |
| 10 | `album_artist` / `album_artist_sort` equal `artist` | `artist_field_mismatch` |
| 11 | Title contains parentheses | `title_format` |
| 12 | Publisher equals grouping | `publisher_grouping` |
| 13 | Publisher/grouping free of bracketed numbers | `publisher_grouping` |
| 14 | Discogs id present and non-zero | `discogs_missing` |
| 15 | File size at least `MIN_FILE_SIZE_BYTES` | `file_size` |
| 16 | Full Pydantic model validation (unflagged fields only) | `pydantic_error` |

`CHECK_TYPES` maps each issue code to a dashboard category
(`field_presence`, `value_validity`, `cross_field`, `pydantic`, `file`).

## Constants

```python
BPM_MIN, BPM_MAX  # 100, 200
YEAR_MIN  # 1970
MIN_FILE_SIZE_BYTES  # 100_000
CAMELOT_NOTATIONS  # valid album values
INITIALKEY_NOTATIONS  # valid initialkey values
CAMELOT_KEYS  # album -> expected initialkey
CHARACTER_REPLACEMENTS  # filename sanitisation (incl. Unicode-dash normalisation)
```

## Pydantic model

`AudioMetadata` enforces the same rules declaratively (ranges, Camelot album,
key/album agreement, subtitle and filename format, artist-field agreement). Use
it when you want construction to raise on invalid data; use `validate_metadata`
when you want a non-raising report of every issue at once.

## Using it from a consumer (e.g. the music pipeline)

Keep the mutagen reading in the consumer; hand the extracted dict over:

```python
from data_quality.music import validate_metadata

fields = extract_fields_with_mutagen(path)  # your existing code
result = validate_metadata(
    fields,
    filename_stem=path.stem,
    file_size_bytes=path.stat().st_size,
)
```
