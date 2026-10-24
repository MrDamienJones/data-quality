# Music EDM Check Registry Design

This document records the design decisions behind `data_quality.music_edm` and the reasons for them. Read it before you change how checks are selected, skipped or fed with data. For usage, see the [music_edm README](../src/data_quality/music_edm/README.md).

Last updated: 2026-10-24.

## Why the Registry Exists

The first version of `validate_metadata` was one function that ran 16 checks in a fixed order. That design had three problems:

1. A caller could not run a subset of the checks.
2. A data source that does not carry a field, for example an iTunes export with no BPM column, failed every check that needs that field.
3. The function accepted one dict at a time. Each consumer repo needed its own loop and its own column mapping for a CSV or parquet export.

The refactor in commits `7f1bd79` and `91847d9` (2026-10-23) split the checks into named units and added a row runner, a pandas adapter and ready-made column maps. `validate_metadata` stayed as a wrapper, and the 42 tests that existed before the refactor passed with no change.

## Components

| Module | Contents |
|---|---|
| `registry.py` | `Check`, `CheckContext`, the ordered `CHECK_REGISTRY`, the 13 check functions, `validate_row` and `list_checks` |
| `checks.py` | `validate_metadata` (a wrapper over `validate_row`), `categorize_issue` and `EXPECTED_FIELDS` |
| `filenames.py` | `generate_filename` |
| `field_maps.py` | `SourceMap`, the `mp3tag_csv` and `itunes_txt` maps, and `resolve_source_map` |
| `frame.py` | `validate_frame` and `FrameValidationSummary` |
| `reconcile.py` | `reconcile_frames`, `ReconcileSummary` and `FieldMismatch` |
| `constants.py` | Ranges, Camelot maps, `INT_FIELDS`, `CHARACTER_REPLACEMENTS` and `CHECK_TYPES` |

All check logic works on plain dicts and needs no pandas. Only `frame.py` and `reconcile.py` use pandas.

## Check Registry

Each check is a frozen `Check(id, required, run, any_of)`. `required` is the set of canonical fields that must all be present for the check to run. If `any_of` is not empty, at least one of its fields must also be present. `run` reads values from `CheckContext.fields` with `.get()` and records issues with `result.add_issue(message, code, field)`.

`CHECK_REGISTRY` is a tuple, and its order is the execution order. `list_checks()` returns the ids in that order. The order sets the order of the issues and of the ids in `result.ran` and `result.skipped`.

| Order | Id | Required fields | Issue codes |
|---|---|---|---|
| 1 | `missing_fields` | at least one of the 9 guard fields (see below) | `missing_fields` |
| 2 | `bpm_range` | `bpm` | `value_out_of_range` |
| 3 | `year_range` | `year` | `value_out_of_range` |
| 4 | `bpm_track_mismatch` | `bpm`, `track_number` | `bpm_track_mismatch` |
| 5 | `invalid_camelot` | `album` | `invalid_camelot` |
| 6 | `corrupted_field` | `initialkey` | `corrupted_field` |
| 7 | `key_album_mismatch` | `initialkey` | `invalid_key`, `key_album_mismatch` |
| 8 | `subtitle_drift` | `artist`, `title`, `album`, `bpm`, `year`, `subtitle` | `subtitle_drift` |
| 9 | `filename_drift` | `artist`, `title` | `filename_drift`, `filename_case_drift` |
| 10 | `artist_field_mismatch` | `artist` | `artist_field_mismatch` |
| 11 | `title_format` | `title` | `title_format` |
| 12 | `publisher_grouping` | none | `publisher_grouping` |
| 13 | `discogs_missing` | `discogs_id` | `discogs_missing`, `value_out_of_range` |

The 9 guard fields are `title`, `artist`, `album`, `initialkey`, `encodedby`, `album_artist`, `album_artist_sort`, `subtitle` and `year`.

An id is a handle for selecting a check. A code is the label on an issue that `CHECK_TYPES` maps to a dashboard category. The codes are the stable contract for consumers. The message text can change. The id and the code differ where two checks emit one code (`bpm_range` and `year_range`), and where one check emits two codes:

- `key_album_mismatch` emits `invalid_key` for a key that is not valid notation, and `key_album_mismatch` for a valid key that does not match the album.
- `filename_drift` emits `filename_case_drift` when the file name matches the expected name apart from letter case, and `filename_drift` for any other difference. On the 2026-10-21 exports, 36 of the 70 drifts were letter case only. The separate code lets you fix those as one group.
- `discogs_missing` emits `discogs_missing` for a missing or zero id, and `value_out_of_range` for a negative id.

`pydantic_error` is the code for an int field that cannot be parsed, and no check has that id (see [Int Fields](#int-fields)).

### Required-Field Rule

A check's required set holds only the fields without which no branch of the check can fire. It does not hold every field that some branch reads. With the larger set, a source that lacks a field used by one branch would skip the whole check. The branches that could still run would then be lost. Three checks show the rule:

- `key_album_mismatch` requires only `initialkey`. The `invalid_key` branch needs only the key. The album comparison has its own guard and does nothing when `album` is absent.
- `artist_field_mismatch` requires only `artist`. Each comparison has its own guard.
- `publisher_grouping` requires nothing. Its three branches each need only `publisher`, only `grouping`, or both.

`missing_fields` uses `any_of` in place of `required`. It runs when at least one guard field is present, and it reports only the guard fields that are present but blank. The `mp3tag_csv` export has no `album_artist_sort` column. With all 9 guard fields required, `missing_fields` never ran on that export, and a blank title, artist, album, key, year or encoder passed with no issue. If no guard field is present, the check is skipped.

### Merged Checks

The original function had 16 blocks. Blocks 12 and 13 both emitted `publisher_grouping` and ran one after the other, so the registry merges them into one check. `key_album_mismatch` stays one check with two codes, so that its order and output did not change. The cost is that a caller cannot turn off only the bracket-number test or only `invalid_key`.

## Running Checks With validate_row

`validate_row(fields, include=None, exclude=None, filename_stem=None)` runs part or all of the registry over one dict.

Selection follows these rules:

- `include=None` selects every check. A list selects those ids, and they run in registry order, not in the order given.
- `exclude` removes ids from the set that `include` selected. If an id is in both, `exclude` wins.
- An empty `include` raises `ValueError`. Selecting no checks would make every row pass, which hides a configuration mistake.
- An unknown id in either list raises `ValueError` before any check runs. In `validate_frame` this happens before the row loop, so a mistyped id raises even on an empty DataFrame.

### Absent, Blank and Skipped

A check runs only when every field in its required set is a key in the input dict. The value of the key does not matter.

- If the key is absent, the check is skipped and its id goes into `result.skipped`. This is how a source that has no BPM column skips `bpm_range`.
- If the key is present with the value `None`, the check runs. Its own guard then decides whether to report an issue. A blank BPM cell in a CSV that has a BPM column therefore runs `bpm_range`, which reports nothing for a blank value.

`result.ran` lists the checks that ran. `result.skipped` lists only checks that could not run for lack of fields. Checks removed by `include` or `exclude` are in neither list.

`result.fields` always holds all 14 canonical fields, with `None` for any that the source did not supply. It is a snapshot for the caller and is not used to decide which checks run.

### validate_metadata

`validate_metadata(fields, filename_stem)` calls `validate_row` with the private argument `_resolve_all=True`. This treats all 14 canonical fields as present, so no check is skipped, which is how the original function behaved. `validate_metadata({}, ...)` therefore reports `missing_fields`.

## Int Fields

`INT_FIELDS` in `constants.py` lists `bpm`, `track_number`, `year` and `discogs_id`. Tags read from files and cells read from CSV files can arrive as text, and the checks compare these values as numbers.

`validate_row` parses each int field with pydantic:

- An int, an integral float such as `128.0`, or integer text such as `"128"` or `" 128 "` becomes an `int`.
- `None` or blank text becomes `None`.
- Any other value, for example `"128a"`, `128.5`, `inf` or a bool, becomes a `pydantic_error` issue on that field, such as `Pydantic: bpm: Input should be a valid integer, unable to parse string as an integer`. The checks then see `None`.

A field that has this issue is not also reported by `missing_fields` or `discogs_missing`.

The rule behind this design: a data problem is reported as an issue, and only an unexpected fault raises an exception. A bad value in one track must not stop a run over a whole library, and it must not disappear without a report.

## DataFrame Adapter

`validate_frame(df, field_map=None, source=None, include=None, exclude=None)` runs `validate_row` on each row and returns a `FrameValidationSummary` with `total`, `passed`, `pass_rate`, `issue_counts`, `checks_run`, `skipped_checks`, the per-row `results` and the original index values in `row_index`. `failures()` yields `(index, result)` for each failed row.

A pass rate alone hides how much was checked. On the 2026-10-21 iTunes export, 98.5% of rows passed, but only 7 of the 13 checks ran. `checks_selected` is `checks_run | skipped_checks`, so `len(checks_run)` of `len(checks_selected)` gives the coverage to show next to the pass rate.

### Reading Rows

The adapter reads cells by column label from `zip(df.index, df.to_dict(orient="records"))`. Do not change this to `df.itertuples()`. That method renames columns to valid Python identifiers, and every `mp3tag_csv` column contains a hyphen (`MTG-Title`) while `itunes_txt` has spaces (`Track Number`). `df.loc[idx]` is also unsafe, because it returns several rows when index labels repeat.

### Missing Columns

The adapter compares the map with `df.columns` once, before the row loop.

- The adapter drops a mapped column that the DataFrame lacks. Its canonical field is never added to any row. The checks that need the field skip on every row and appear in `skipped_checks`. The other checks still run, so a partial export gets checked on the fields it has.
- If no filename column resolves, `filename_drift` is excluded for the whole call. Without a filename, the check would report drift on every row.

This exclusion wins over an explicit `include`. The check could not run for lack of a column, so `skipped_checks` lists it, the same as a check skipped for lack of a field. If the caller excluded the check or did not include it, it is not listed.

### Filenames

When `SourceMap.filename_basename` is true, the adapter takes the file name from a full path with `ntpath.basename`, then removes `filename_strip_suffix`. `ntpath` splits on both `\` and `/` on every operating system. iTunes on Windows exports paths such as `C:\...\Track.mp3`, and `os.path.basename` does not split those on Linux, which includes the GitHub Actions CI.

### Pandas Is Optional

pandas is an optional install (`pip install "data-quality[pandas]"`). `frame.py` and `reconcile.py` import pandas inside `validate_frame` and `reconcile_frames` only, so `import data_quality.music_edm` works without it. A call to either function without pandas raises an `ImportError` that gives the install command. `tests/test_pandas_optional.py` and `tests/test_reconcile.py` test these cases.

## Field Maps

A `SourceMap` maps raw column names to canonical field names (`raw -> canonical`). It also names two special columns: `filename_from` for the filename and `path_from` for the full file path.

iTunes shows the content-group tag in its `Work` column. mp3tag calls the same tag `MTG-GroupDescription`. So `itunes_txt` maps `Work` to `grouping`. The iTunes `Grouping` column holds a different tag. On the 2026-10-21 exports, `Work` matched `MTG-GroupDescription` on 4,572 of 4,632 tracks, and `Grouping` had a value on only 62 tracks.

| Map | Columns it lacks | Checks skipped on every row |
|---|---|---|
| `mp3tag_csv` | `album_artist_sort`, `discogs_id` | `discogs_missing` |
| `itunes_txt` | `bpm`, `initialkey`, `encodedby`, `album_artist`, `album_artist_sort`, `subtitle`, `publisher`, `discogs_id` | `discogs_missing`, `bpm_range`, `bpm_track_mismatch`, `corrupted_field`, `key_album_mismatch`, `subtitle_drift` |

In this library the album tag holds the Camelot key code, for example `08A-Am`, not an album title. `itunes_txt` maps `Album` to `album`, so `invalid_camelot` runs on it. An iTunes library that holds real album titles must pass `exclude=["invalid_camelot"]`, or every row fails.

### Precedence of source and field_map

`resolve_source_map` turns the two arguments into one map:

| `source` | `field_map` | Result |
|---|---|---|
| none | none | Identity map: each canonical name maps to itself. The adapter also reads `filename_stem` and `path` columns if they exist. |
| a name | none | The named map |
| none | dict | A custom map with those columns and no filename or path column |
| none | `SourceMap` | That map |
| a name | dict | The named map with the dict merged into its columns. The dict wins on conflicts. |
| a name | `SourceMap` | The given map replaces the named map |

An unknown `source` name raises `ValueError`.

## Cross-Source Reconciliation

`reconcile_frames(left, right, left_source=..., right_source=..., on="path", fields=None)` compares two exports of the same library, for example iTunes and mp3tag. Each source resolves to a `SourceMap` in the same way as for `validate_frame`. The function returns a `ReconcileSummary`.

The design decisions are:

- The default join key is the full file path from `path_from`. Two files in different folders can have the same file name, and both exports carry the full path. `on="filename"` joins on the filename stem in place of the path.
- Matching ignores letter case and treats `/` and `\` as the same, because Windows paths work that way. `ntpath.normcase` does the normalisation. Reports show the key as the source wrote it.
- By default, the function compares every canonical field that both sources carry. A requested field that one source lacks raises `ValueError`, because a silent skip would hide a configuration mistake.
- Int fields compare as parsed integers, so `"2020"` and `2020.0` are equal. A value that cannot be parsed compares as text, so it still differs from a valid number.
- A value on one side and a blank on the other is a mismatch. That is drift between the sources, for example a label in the file tag that iTunes does not show. Two blanks are equal.
- A key that occurs more than once in a source is reported in `duplicate_left` or `duplicate_right`. The function compares the first occurrence only. A blank key is reported in `missing_key_left` or `missing_key_right`.
- `records()` yields one flat dict per issue, with `code`, `key`, `field`, `source`, `left` and `right`, for a log or a dashboard table. The codes (`unmatched`, `duplicate_key`, `missing_key`, `cross_source_mismatch`) are in `CHECK_TYPES`, under the `join` and `cross_source` categories.

On the 2026-10-21 exports, all 4,632 tracks matched on path. The only mismatches were 60 tracks where the file has a label in its group tag and iTunes shows none.

## Filename Generation

`generate_filename(artist, title)` builds the expected file name in these steps:

1. Replace each character listed in `CHARACTER_REPLACEMENTS`.
2. Remove hyphens inside each field.
3. Join artist and title with `-`.
4. Replace the last `(` with `-`.
5. Remove all other brackets and all spaces.

`CHARACTER_REPLACEMENTS` turns Unicode dashes into `-` and removes typographic quotes, the same as their ASCII forms. Both kinds of character appear in real tags. Without these entries, a title with `’` (U+2019) or `‐` (U+2010) gives a different file name from the same title typed in ASCII.

## Known Limitations

- `key_album_mismatch` and `publisher_grouping` cannot be turned off in part. See [Merged Checks](#merged-checks).
- `track_number` is not range-checked when `bpm` is blank. The retired `pydantic_fallback` check reported this, but only on sources that carried all 9 guard fields.

## Changes From the Original Spec

The spec that guided the refactor required that every issue message stay byte-identical to the original function. That rule protected the refactor. It no longer applies: the issue codes are the contract, and the message text can change. These later changes depart from the spec:

- Unparseable int values are reported as `pydantic_error` issues on both the dict path and the DataFrame path. The spec turned them into `None` without a report on the DataFrame path. On the dict path they caused a `TypeError`.
- `missing_fields` runs on the guard fields a source carries, in place of requiring all 9. See [Required-Field Rule](#required-field-rule).
- The `pydantic_fallback` check is retired. It repeated the rules of the explicit checks through `AudioMetadata` and added almost no coverage. It also caused a bug: every row from a DataFrame with no filename column failed.
- `filename_drift` emits `filename_case_drift` for a difference in letter case only.
- `discogs_missing` reports a negative id as `value_out_of_range`.
- `validate_frame` lists the auto-excluded `filename_drift` in `skipped_checks`, and reports `checks_run`.
- The adapter uses `ntpath.basename` in place of `os.path.basename`.
- `CHARACTER_REPLACEMENTS` maps typographic apostrophes and double quotes, and three more dash lookalikes (U+FE58, U+FE63, U+FF0D).
- `itunes_txt` maps `Work` to `grouping` in place of `Grouping`.
- `reconcile_frames` and `SourceMap.path_from` are new.
- `categorize_issue` classifies a plain-string message by the fixed phrase that starts it. The earlier version searched the whole message for keywords, so track data inside the message could change the result. For example, a subtitle-drift message for a track titled "Missing" was classified as `missing_fields`. A test now checks that every message the checks emit classifies to its own code and field.
- The `file_size` check is removed, with `MIN_FILE_SIZE_BYTES`, `SourceMap.size_from` and the `file_size_bytes` arguments. It compared the file size with a fixed 100 KB minimum to find broken files. It never fired on the 2026-10-21 export, where the smallest file is 5.2 MB. A broken file usually fails earlier, when the consumer cannot read its tags.
- `models.py` is replaced by `filenames.py`, which holds only `generate_filename`. The `AudioMetadata` model and the pipeline config models (`Config`, `MetadataMapping`, `PathConfig`, `ValidationConfig`, `AudioFormatEnum`) are removed. No check used them, and `AudioMetadata` held a second copy of the check rules. This repo is to be the only source of the checks, so the registry is the only copy.

The full original spec, with its open questions and three rounds of review responses, is in the git history at commit `ee6fc28`.
