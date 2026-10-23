# Design: Registry-driven, DataFrame-capable music_edm checks

## Overview

Today `validate_metadata(fields, filename_stem, file_size_bytes)` runs 16 hardwired
checks top-to-bottom in one function. This design decomposes those 16 into a set of
individually addressable, named check units held in an **ordered registry**. Each unit
declares the canonical fields it needs and a callable that appends issues to a
`ValidationResult`. On top of the registry we add:

- a **row runner** (`validate_row`) that runs a selectable subset of the registry over
  one dict of fields, auto-skipping checks whose required fields are absent and
  reporting which checks were skipped;
- an **optional pandas adapter** (`validate_frame`) that maps a DataFrame's columns to
  canonical fields and aggregates per-row results into a summary; and
- **ready-made source field maps** (`mp3tag_csv`, `itunes_txt`) so consuming repos get
  a single source of truth for both the checks and the column mappings.

`validate_metadata` is retained verbatim in behavior as a thin wrapper over the
registry so all 42 existing tests pass unchanged.

**Technology stack (locked):** Python >=3.12, pydantic v2 (hard dep), pandas >=2.0.0
(optional extra, input channel only), pyarrow >=14 (dev/test only, parquet). stdlib
`dataclasses`, `collections.Counter`, `re`, `datetime`. No new runtime deps beyond
pandas-as-extra. src layout, ruff line-length 88 (E,W,F,I,UP,B).

**New files (all inside `src/data_quality/music_edm/`):**
- `registry.py` — the `Check` and `CheckContext` types, the ordered `CHECK_REGISTRY`
  (15 units) and derived `_REGISTRY_BY_ID`, the 15 check callables (covering the 16
  original blocks, 12+13 merged), `validate_row`, and `list_checks`.
- `field_maps.py` — `SourceMap` type, `mp3tag_csv`, `itunes_txt`, mapping helpers.
- `frame.py` — `validate_frame`, `FrameValidationSummary` (lazy pandas import).

`checks.py` keeps `validate_metadata`, `categorize_issue`, `EXPECTED_FIELDS` as the
stable public surface; its body is reimplemented to delegate to the registry.

---

## 1. Check registry data structure

A check is a frozen dataclass:

```python
@dataclass(frozen=True)
class Check:
    id: str                      # stable, unique within the registry
    required: frozenset[str]     # canonical fields that must be PRESENT to run
    run: Callable[[CheckContext, ValidationResult], None]
```

`CheckContext` is a small frozen struct holding the three inputs the current function
uses, defined exactly as:

```python
@dataclass(frozen=True)
class CheckContext:
    fields: dict[str, Any]       # full resolved canonical dict (= result.fields); NOT the presence universe
    filename_stem: str | None    # passed through to filename_drift / pydantic_fallback
    file_size_bytes: int | None  # passed through to the file_size check
    current_year: int            # datetime.now().year, captured once per run
```

`current_year` is captured **once per `validate_row` call** (the first line of the
runner does `current_year = datetime.now().year`) so every check in a single row sees a
consistent "now" — this reproduces the single `current_year = datetime.now().year` the
current function computes once at the top. Each callable reads what it needs from
`ctx.fields` via `.get(name)` (never direct indexing, so a check that runs on a mapped
dict missing an unrelated key cannot `KeyError`) and calls
`result.add_issue(message, code, field)` — the `ValidationResult.add_issue` signature is
`(message: str, code: str = "error", field: str = "unknown") -> None`, and the callables
pass all three positionally with **exactly** the message/code/field strings used today.
The callables are produced by mechanically lifting blocks 1–16 out of
`validate_metadata`, so wording, f-string formatting, and `repr()` usage are
byte-identical. Note `ValidationIssue` is a `str` subclass carrying `.code`/`.field`;
nothing in the refactor changes that, so joins/equality in existing tests keep working.

`ctx.fields` is the **full resolved canonical dict** (`= result.fields`, every
`EXPECTED_FIELDS` key present, value `None` where the source did not supply it), on
*both* paths. Callables always read values from it via `.get()` and therefore never
`KeyError`. This is intentionally **distinct from the presence universe** the auto-skip
gate reads (section 3): the gate inspects the *original input* `fields` dict's key set
(mapped keys only on the row/frame path; all keys on the `_resolve_all` path) to decide
which checks run, but once a check is selected to run, its callable sees the full
canonical dict. So on the row/frame path a value the source omitted is `None` to the
callable — but the callable only runs at all if the gate found its required keys present
in the original mapped dict. Keeping the gate input (mapped key set) and the callable
input (full canonical dict) as two objects is the mechanism that makes "absent ->
skip" and "present-but-None -> run and no-op" both work without any callable risking a
`KeyError`.

`CHECK_REGISTRY` is an ordered tuple of `Check` (order == current execution order ==
the numbered list below). A derived `dict[str, Check]` (`_REGISTRY_BY_ID`) gives O(1)
lookup and id-existence validation. A public `list_checks() -> list[str]` returns ids
in order for discoverability.

### The 16 checks, ids, required-field sets and emitted codes

`required` is the set of canonical fields whose **presence** the check fundamentally
needs for its logic to be meaningful. Presence gates *running* the check (section 3);
the check's own internal guards (`if bpm is not None`, `if artist and title`, etc.) are
preserved inside the callable and still decide whether an issue fires. `required` is
deliberately the *input* fields, not the field an issue is tagged with. The **emitted
code(s)** column is the `code` string(s) each callable passes to `add_issue` — these are
unchanged from today and are what `CHECK_TYPES`/`categorize_issue` key on; the `id` is a
separate registry handle (they coincide except where noted). The registry order below is
the canonical `CHECK_REGISTRY` order and equals the current top-to-bottom block order.

Canonical field spelling and the full set are fixed by `checks.EXPECTED_FIELDS`, whose
exact order is:
`bpm, track_number, title, artist, album, initialkey, encodedby, album_artist,
album_artist_sort, subtitle, publisher, grouping, year, discogs_id` (14 fields). Every
`required` entry below is drawn from this tuple.

| # | id | required (canonical fields) | emitted code(s) | issue `field` tag(s) |
|---|----|------------------------------|-----------------|----------------------|
| 1 | `missing_fields` | `title, artist, album, initialkey, encodedby, album_artist, album_artist_sort, subtitle, year` | `missing_fields` | comma-joined missing names |
| 2 | `bpm_range` | `bpm` | `value_out_of_range` | `bpm` |
| 3 | `year_range` | `year` | `value_out_of_range` | `year` |
| 4 | `bpm_track_mismatch` | `bpm, track_number` | `bpm_track_mismatch` | `track_number` |
| 5 | `invalid_camelot` | `album` | `invalid_camelot` | `album` |
| 6 | `corrupted_field` | `initialkey` | `corrupted_field` | `initialkey` |
| 7 | `key_album_mismatch` | `initialkey` | `invalid_key`, `key_album_mismatch` | `initialkey` |
| 8 | `subtitle_drift` | `artist, title, album, bpm, year, subtitle` | `subtitle_drift` | `subtitle` |
| 9 | `filename_drift` | `artist, title` | `filename_drift` | `filename` (runner param `filename_stem`; `validate_frame` auto-excludes when no filename column — see §4 step 4) |
| 10 | `artist_field_mismatch` | `artist` | `artist_field_mismatch` | `album_artist` / `album_artist_sort` |
| 11 | `title_format` | `title` | `title_format` | `title` |
| 12 | `publisher_grouping` | *(empty set — see note)* | `publisher_grouping` | `grouping` / `publisher` |
| 14 | `discogs_missing` | `discogs_id` | `discogs_missing` | `discogs_id` |
| 15 | `file_size` | *(empty set — see note)* | `file_size` | `file_size` |
| 16 | `pydantic_fallback` | `title, artist, album, initialkey, encodedby, album_artist, album_artist_sort, subtitle, year` | `pydantic_error` | the failing pydantic field |

The `id` and emitted code coincide for every row except 2/3 (`bpm_range`/`year_range`
both emit `value_out_of_range`), 7 (`key_album_mismatch` emits `invalid_key` **and**
`key_album_mismatch`), and 16 (`pydantic_fallback` emits `pydantic_error`). The ids are
chosen so no two registry entries share an id while every emitted **code** stays exactly
as today.

**The full ordered id list** — `CHECK_REGISTRY` ids in registry order, which is exactly
what `list_checks()` returns (so `list_checks()` must equal this literal sequence; this
is the testable id-stability spec):

```python
(
    "missing_fields",       # 1
    "bpm_range",            # 2
    "year_range",           # 3
    "bpm_track_mismatch",   # 4
    "invalid_camelot",      # 5
    "corrupted_field",      # 6
    "key_album_mismatch",   # 7  (emits codes invalid_key + key_album_mismatch)
    "subtitle_drift",       # 8
    "filename_drift",       # 9
    "artist_field_mismatch",# 10
    "title_format",         # 11
    "publisher_grouping",   # 12 (blocks 12+13 merged)
    "discogs_missing",      # 14
    "file_size",            # 15
    "pydantic_fallback",    # 16 (emits code pydantic_error)
)
```

15 ids total. Note `publisher_grouping` sits at list position 12 (the merged 12+13
unit), and there is **no** `invalid_key` id — `invalid_key` is only an emitted *code* of
`key_album_mismatch`, never a registry id.

Notes on id choices and merges, to keep behavior identical:

- **Ids reuse existing issue `code` values** where one block emits one code
  (`bpm_track_mismatch`, `invalid_camelot`, `corrupted_field`, `filename_drift`,
  `discogs_missing`, `file_size`, `title_format`). Where the id must differ from the
  code we pick a stable descriptive id: blocks 2 and 3 both emit code
  `value_out_of_range` but are independent checks, so they become ids `bpm_range` and
  `year_range` (the emitted **code stays** `value_out_of_range`, preserving tests and
  `CHECK_TYPES`).
- **Block 7 is one check (`key_album_mismatch`)** that can emit two codes
  (`invalid_key` and `key_album_mismatch`) exactly as the current code does — splitting
  it would change ordering/semantics, so it stays one unit. **Its required set is
  `{initialkey}` only, NOT `{initialkey, album}`.** Reason: the current code's
  `invalid_key` sub-check (`if key and not corrupted_key and key not in
  INITIALKEY_NOTATIONS`) needs only `initialkey`; the album-match sub-check is already
  internally guarded by `if album and key and not corrupted_key`. If `required` included
  `album`, an `initialkey`-only source row (album absent) would auto-skip the whole
  check and lose the `invalid_key` branch — a behavior change. By requiring only
  `{initialkey}`, the check runs whenever a key is present and the internal `if album
  and key ...` guard decides whether the album-match branch fires (it no-ops when album
  is absent). The `invalid_key` field tag remains `initialkey`. The `#7` row in the table above
  already reflects this (`required = initialkey`). *Q1 covers the finer-grained split.*
- **Blocks 12 and 13 are merged into one `publisher_grouping` check** (both emit code
  `publisher_grouping` and run consecutively today). It has **three independent
  sub-branches**: `if publisher and grouping and publisher != grouping`; `if publisher
  and <bracket-regex>`; `if grouping and <bracket-regex>`. Because the publisher-only
  and grouping-only bracket branches each need just one of the two fields, requiring
  both would auto-skip the whole check for a source that carries only one — dropping a
  branch that currently fires. **Its `required` set is therefore empty** (always run;
  the three internal guards decide what fires). Consequence: a source with neither field
  (e.g. itunes_txt carries `grouping` but not `publisher`) still *runs* the check, but
  all three guards no-op, so no issue and no behavior change; it simply won't appear in
  `skipped_checks`. If a consumer wants it skipped, `exclude=["publisher_grouping"]`.
  *See Q1.*

- **Required-set derivation rule (applied consistently).** A check's `required` set is
  the **intersection** of the fields every one of its sub-branches needs — i.e. the
  fields without which *no* branch of the check can fire — **not** the union of all
  fields any branch mentions. Using the union would auto-skip a check for a source that
  omits a field only one branch needs, silently dropping a branch today's code would run
  (the #7, #10 and #12 cases). Single-branch checks (#2 `bpm`, #3 `year`, #4 needs both
  `bpm` and `track_number`, #5 `album`, #6/#7 `initialkey`, #8 needs all six, #9 needs
  `artist`+`title`, #11 `title`) take the obvious set; multi-branch checks (#7, #10, #12)
  take the intersection as noted. #1/#16 require their full 9-field guard set because
  `missing_fields` fundamentally reasons about the presence of all nine and
  `pydantic_fallback` constructs the full model.
- **`pydantic_fallback` (block 16)** keeps its current contract: it runs the full
  `AudioMetadata(...)` construction only when the `missing_fields` check found nothing
  missing, and suppresses errors on fields already flagged by earlier checks via
  `result.flagged_fields()`. Because it reads *every* field and dedupes against prior
  issues, it must run **last** and must see the other checks' issues. Its `required`
  set mirrors block 1 (the fields `missing_fields` guards on); the `if not missing`
  gate is reimplemented as "run only if no issue with code `missing_fields` is present
  in the result so far" (equivalent, and avoids recomputing `missing`). See section 2.
  The callable constructs `AudioMetadata(...)` passing the same arguments the current
  block does — note two verbatim details that must be preserved: `discogs_id=ctx.fields
  .get("discogs_id") or 0` (the `or 0` coerces a missing/zero discogs to the model's
  `ge=0` field) and `filename=ctx.filename_stem`. After catching `ValidationError`, it
  computes `result.flagged_fields()` and, for each `e.errors()` entry, derives
  `field = str(error["loc"][0]) if error.get("loc") else "unknown"`, skips fields in
  `flagged`, and adds `f"Pydantic: {field}: {msg}"` with code `pydantic_error` — all
  byte-identical to today.
- **`file_size` has an empty required set** because `file_size_bytes` is a runner
  parameter, not a canonical field in `fields`. It therefore never auto-skips on field
  grounds. See Q2 for how `validate_frame` opts rows out of it.

- **Checks with empty `required` (`file_size` and `publisher_grouping`)** always run and
  never contribute to `skipped_checks`. This is intentional — both no-op safely when
  their inputs are absent (file_size via the `file_size_bytes is None` branch, which
  *does* emit on the row/frame path unless excluded per Q2; publisher_grouping via its
  three internal guards, which emit nothing when both fields are absent).

The resulting registry has **15 `Check` units** (blocks 12+13 merged) covering the 16
original blocks. `validate_metadata` output is unaffected because no block's logic or
emitted strings change.

---

## 2. Behavior-preservation contract

`validate_metadata(fields, filename_stem, file_size_bytes=None) -> ValidationResult`
is reimplemented as:

```python
def validate_metadata(
    fields: dict[str, Any],
    filename_stem: str,
    file_size_bytes: int | None = None,
) -> ValidationResult:
    return validate_row(
        fields,
        filename_stem=filename_stem,
        file_size_bytes=file_size_bytes,
        _resolve_all=True,
    )  # include=None, exclude=None -> full registry, _resolve_all => nothing auto-skips
```

**`validate_metadata` retains its current annotations** — `fields: dict[str, Any]`,
`filename_stem: str` (non-optional), `file_size_bytes: int | None = None` — unchanged
from today; only the body is rewritten to delegate. This keeps the public type surface
identical for the 42-test gate and existing callers, even though the underlying
`validate_row` widens `filename_stem` to `str | None`. Passing a `str` where the runner
accepts `str | None` is type-safe; the wrapper does not narrow or widen its own
signature. Note the wrapper passes `_resolve_all=True` (the private runner flag) so the
full canonical dict is the presence universe and no check auto-skips — reproducing
today's "run every block" behavior.

For the wrapper to be byte-identical to today, `validate_row` **when called with no
include/exclude and with every EXPECTED_FIELD key resolvable** must:

1. Set `result.fields = {name: fields.get(name) for name in EXPECTED_FIELDS}` (same as
   now — the runner always materializes the full canonical dict so `result.fields` is
   stable regardless of which checks ran).
2. Run the 15 registry checks **in registry order**, which is the current block order.
3. For `validate_metadata` specifically, **auto-skip must not change results.** Because
   the current function always runs every block (relying on internal `if` guards, not
   presence gating), the wrapper path must behave as "run all". This is guaranteed by
   section 3's explicit gate branch: with `_resolve_all=True` the runner sets
   `present = set(EXPECTED_FIELDS)` (independent of the caller dict's keys), so
   `check.required <= present` holds for **every** check and nothing is skipped — even
   for `validate_metadata({}, ...)`, where the raw dict is empty but `present` is still
   the full 14-key set (this is exactly what keeps `test_missing_keys_treated_as_none`
   green). (Presence = membership in the `present` set, not value truthy — see section 3.)
   `file_size` has empty `required`, so it always runs, preserving both the
   "unknown size" and "too small" branches including the `file_size_bytes=None` case.
4. `pydantic_fallback` runs last and gates on "no `missing_fields` issue recorded",
   reproducing the `if not missing:` behavior and the `flagged_fields()` dedupe.

Because the callables are lifted verbatim, codes, messages, field tags, pass/fail and
issue ordering are preserved. `CHECK_TYPES`, `categorize_issue`, `EXPECTED_FIELDS`
remain exactly as they are in `constants.py`/`checks.py` and keep working. **All 42
tests in `test_music_edm_checks.py`, `test_core_result.py`, `test_placeholders.py` must
pass unchanged**; this is the acceptance gate for the refactor.

One guaranteed-safe deviation: the current block 1 computes `missing` and blocks 16
reuses it. In the registry, `missing_fields` and `pydantic_fallback` are separate
callables; `pydantic_fallback` recovers the gate by checking for a recorded
`missing_fields` issue. Equivalent because block 1 adds the issue iff `missing` is
non-empty.

---

## 3. Row runner

```python
def validate_row(
    fields: dict[str, Any],
    *,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    filename_stem: str | None = None,
    file_size_bytes: int | None = None,
    _resolve_all: bool = False,   # internal; True only from validate_metadata
) -> ValidationResult:
```

`_resolve_all` is a private, undocumented-in-public-API keyword (leading underscore,
default `False`). It is **not** exported and **not** mentioned in the public docstring;
only `validate_metadata` passes `_resolve_all=True`. It selects the presence universe
(see "Important interaction" below).

**Presence-universe construction (explicit — this is the auto-skip gate input).** The
runner builds the presence set *before* iterating the registry, and it is NOT
`result.fields` and NOT the length/identity of the raw dict:

```python
present = set(EXPECTED_FIELDS) if _resolve_all else set(fields)
# ... then for each selected check, in registry order:
#   run it iff check.required <= present
#   else record its id in result.skipped (only when it was selected and not excluded)
```

So on the `_resolve_all=True` path (`validate_metadata`) `present` is the **full
14-key `EXPECTED_FIELDS` set regardless of what keys the caller's dict actually has** —
this is the critical branch for `validate_metadata({}, ...)`: the raw dict is empty, but
`present` is still the full set, so `check.required <= present` holds for every check,
nothing auto-skips, and `missing_fields` still fires (preserving
`test_missing_keys_treated_as_none`). On the row/frame path (`_resolve_all=False`)
`present = set(fields)` is the mapped source's actual key set, so canonical fields the
source never supplied are absent from `present` and their checks auto-skip. `result.fields`
is materialized separately and always full (see end of this section); it is never the
gate input.

**Selection semantics:**

- `include=None` -> start from the full ordered registry. `include=[...]` -> start from
  exactly those ids, **in registry order** (not caller order — ordering stays
  deterministic and matches `validate_metadata`).
- **Empty `include=[]` (non-None, zero ids) raises `ValueError` (finding 3).** Decided:
  `include=[]` is treated as a caller error, not a silent "select nothing". Raise
  `ValueError("include must be a non-empty iterable of check ids or None")`. Rationale:
  selecting zero checks would make every row trivially "pass" with no issues and an empty
  `skipped_checks` — a silent all-green footgun for a validation library (e.g. a caller
  that computed an empty include list from upstream config). This matches the fail-fast
  stance taken for unknown ids. (An empty `exclude=[]` is well-defined and benign: it
  excludes nothing. Only empty `include` raises.)
- `exclude=[...]` removes those ids from the selected set.
- **include + exclude interaction (decided):** `exclude` is applied *after* `include`,
  i.e. the effective set is `selected(include) - set(exclude)`. Exclude always wins on
  conflict. This is the least surprising rule ("take these, but not those") and makes
  `exclude` a safe override layer. Documented in the docstring.
- **Id validation (timing pinned — finding 2):** every id in the caller-supplied
  `include` and `exclude` is checked against `_REGISTRY_BY_ID` **once, up front, before
  any row iteration and regardless of how many rows the input has (including an empty
  DataFrame)**. Unknown ids raise `ValueError` listing the unknown id(s) and, for
  discoverability, noting `list_checks()`. In `validate_row` this happens at the top of
  the call; in `validate_frame` it happens before the row loop, so a typo like
  `exclude=["flie_size"]` on an **empty** frame still raises rather than silently passing
  (the loop would otherwise never call `validate_row`). The adapter validates the
  **caller's raw `include`/`exclude`**, *then* merges the known-valid auto-exclude ids
  (`file_size`/`filename_drift` per step 4) — the auto-added ids are always valid and so
  never trip validation. Rationale: a typo'd check id silently doing nothing is a
  correctness trap for consuming repos; fail fast. (This cannot affect
  `validate_metadata`, which passes no ids and no empty `include`.)

**Auto-skip on absent required fields:**

- A check runs only if **all** fields in its `required` set are *present* in the input
  `fields` dict. "Present" means **the key exists in the dict**, regardless of value —
  a key mapped to `None` counts as present (the value was supplied/known to be empty).
  "Absent" means the key is **not in** the dict at all. This distinction is what lets
  the itunes_txt source (which never supplies `bpm`, `initialkey`, etc.) auto-skip the
  value-level checks, while a CSV row that has a blank BPM cell (mapped to `None`, see
  section 5) still *runs* `bpm_range` (which then no-ops via its `if bpm is not None`
  guard) — matching intuition that "the column exists but this row is blank" is a
  pass, not a skip.
- Checks with empty `required` (`file_size`, `publisher_grouping`) never skip on field
  grounds — they always run and never appear in `skipped`.
- Skipped check ids are collected and exposed on the result.
- **Presence is evaluated against the `fields` dict the runner received** (the mapped
  dict on the row/frame path, the full resolved dict on the `_resolve_all` path), which
  is a distinct object from `result.fields` (always the full canonical dict — see
  below). Only the gate reads the mapped dict's key set; the callables read values via
  `ctx.fields.get(...)` on whichever dict the context carries.
- **Determinism:** the gate iterates the registry in order, so `skipped` is always in
  registry order and the subset that runs executes in registry order. This matters for
  `pydantic_fallback`'s `flagged_fields()` dedupe, which depends on earlier checks
  having already recorded their issues. `pydantic_fallback` only ever runs when its full
  9-field required set is present (i.e. the `_resolve_all` path, or a hypothetical source
  carrying all nine), where every preceding check also runs — so the dedupe always sees
  the same prior-issue set it sees today. On partial sources it auto-skips, so there is
  no path where it runs against a *partially* populated issue list.

**Important interaction with `validate_metadata`:** this is governed entirely by the
`present`-set construction shown above. The wrapper passes the caller's `fields` dict
through unchanged together with `_resolve_all=True`; the runner then sets `present =
set(EXPECTED_FIELDS)` (NOT `set(fields)`), so every check's `required` is satisfied and
**nothing auto-skips** — preserving today's "run all blocks" behavior even for a sparse
or empty caller dict. For the row/frame API (`_resolve_all=False`) `present =
set(fields)` is the **mapped** fields dict's key set (only keys the source/field_map
actually produced), so absent canonical fields trigger auto-skip. The wrapper does **not**
itself pre-materialize the canonical dict for gating purposes — `result.fields`
materialization (below) is a separate, always-full snapshot and is not the gate input.

**Exposing skipped ids:** extend `ValidationResult` with an optional
`skipped: list[str]` attribute (default empty list), populated by the runner with ids
that were **auto-skipped on absent required fields**, in registry order. Checks removed
by `exclude` (or never selected because `include` omitted them) are **not** recorded in
`skipped` — `skipped` means "applicable-but-not-runnable for lack of fields", distinct
from "caller chose not to run it". This keeps the Q2 `file_size` deselection out of
`skipped`/`skipped_checks` and makes `skipped_checks` a meaningful "this source doesn't
carry these fields" signal. This is additive and backward-compatible: existing tests
that construct `ValidationResult()` directly still pass (attribute defaults to `[]`),
and `validate_metadata` leaves it empty (nothing skips).

**`result.fields` is always the full canonical dict** regardless of path:
`result.fields = {name: mapped.get(name) for name in EXPECTED_FIELDS}` where `mapped` is
the input `fields`. On the row/frame path, canonical fields the source did not supply
therefore appear as `None` in `result.fields` (stable 14-key shape for downstream
consumers) even though they were *absent* from the presence universe and so caused their
checks to skip. The two notions are deliberately separate: `result.fields` is the
reported snapshot (always full); the presence universe is the gate input (mapped keys
only on the row/frame path). This preserves the existing contract that
`result.fields["<any EXPECTED_FIELD>"]` never raises `KeyError`.

Return value: a `ValidationResult` exactly as today, plus the populated `skipped` list.

---

## 4. Optional pandas adapter

```python
def validate_frame(
    df,                                   # pandas.DataFrame (not type-annotated to avoid import)
    *,
    field_map: Mapping[str, str] | SourceMap | None = None,
    source: str | None = None,            # "mp3tag_csv" | "itunes_txt"
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> "FrameValidationSummary":
```

Lives in `frame.py`. **Lazy import:** pandas is imported *inside* `validate_frame`
only (the `_coerce_int`/`_coerce_str` helpers that call `pd.isna` are themselves only
invoked from within `validate_frame`, after the import succeeds, so they do not need
their own top-level import). `FrameValidationSummary` holds only stdlib/typing/pydantic
result types and therefore needs **no** pandas import in any of its methods —
`pass_rate` and `failures()` touch only `self.*` fields. There must be **no**
`import pandas` at module top level of `frame.py`. Concretely: `import
data_quality.music_edm`, `from data_quality.music_edm import validate_metadata`,
`validate_row`, `validate_frame`, and `FrameValidationSummary` must all succeed with
pandas uninstalled; pandas is only required when `validate_frame` is actually *called*.
`frame.py` is imported by `music_edm/__init__.py` only to bind the *names*
`validate_frame`/`FrameValidationSummary`.

Missing-pandas handling:

```python
try:
    import pandas as pd
except ImportError as e:
    raise ImportError(
        "validate_frame requires the optional 'pandas' extra. "
        'Install it with: pip install "data-quality[pandas]"'
    ) from e
```

**Per-row flow:**
1. Resolve the mapping (section 5) into an effective `(columns, filename_from,
   filename_strip_suffix, filename_basename, size_from)`.
2. **Determine which mapped columns actually exist in `df.columns` once, up front**
   (not per row). A mapped raw column (member of `columns`) that is *not* a DataFrame
   column is dropped from the effective mapping entirely (Q3 lenient default) — so its
   canonical field key is never inserted into any row's `fields` dict, and the dependent
   checks auto-skip uniformly across all rows (surfacing in `skipped_checks`). This also
   means the present/absent decision is a per-*source* property, not per-row, which keeps
   `skipped_checks` a clean union rather than a ragged per-row thing.
   **The same absent-column rule applies to the two structural derivation fields, which
   are NOT members of `columns`:** if `filename_from` names a column not in `df.columns`,
   treat it as `None` for this call — `filename_stem` is then not derived (passed as
   `None` to the runner). Likewise, if `size_from` names a column not in `df.columns`,
   treat it as `None` — `file_size_bytes` is not derived, **and `size_from`-absence is
   precisely what triggers the Q2 `file_size` auto-exclude** (step 4 / finding 1). After
   this pass the adapter holds a resolved tuple `(columns', filename_from',
   filename_strip_suffix, filename_basename, size_from')` where every surviving name is
   guaranteed to be a real DataFrame column and `filename_from'`/`size_from'` are either a
   present column or `None`.
3. Iterate rows **by label**, pairing each original index value with a plain dict of the
   row's cells keyed by **original column name**, in DataFrame order:

   ```python
   for idx, row in zip(df.index, df.to_dict(orient="records")):
       cell = row.get(raw_col)   # raw_col may contain hyphens/spaces — label-safe
   ```

   `df.itertuples` is **prohibited**: it returns a namedtuple whose attribute names are
   the columns *rewritten to valid Python identifiers* (hyphens/spaces replaced, or
   positional `_<n>`), so attribute access by original column name fails for the exact
   shipped maps — every `mp3tag_csv` column has a hyphen (`MTG-Title`, `MTG-BPM`, ...)
   and `itunes_txt` has spaces (`Track Number`). Cells must be read by **label** from the
   `to_dict(orient="records")` mapping (`row.get(raw_col)`); the equivalent
   `df.loc[idx][raw_col]` is also acceptable. `idx` is the original index value and is
   what lands in `row_index`.

   For each row, build the canonical `fields` dict: for each surviving `(raw_col ->
   canonical)` pair, read the cell and apply `_coerce_int` (if canonical in
   `INT_FIELDS`) or `_coerce_str`. **The key is inserted even when the coerced value is
   `None`** (the column exists for the source, so the field is "present but blank" ->
   the check runs and no-ops), which is exactly the section-3 "present key, None value"
   case. Derive `filename_stem` from `filename_from` (apply basename then strip suffix)
   and `file_size_bytes` from `size_from` (via `_coerce_int`) when those columns exist.
4. Call `validate_row(fields, include=effective_include, exclude=effective_exclude,
   filename_stem=stem, file_size_bytes=size)` — note **not** `_resolve_all`, so canonical
   fields whose column was absent from the source auto-skip. `effective_exclude` is the
   caller's `exclude` plus two runner-parameter auto-excludes: `file_size` **when the
   resolved `size_from'` is `None`**, and `filename_drift` **when the resolved
   `filename_from'` is `None`** (i.e. the source map carried no such column, or named one
   absent from `df.columns` and so nulled in step 2). Both are computed **once** before
   row iteration (the resolved `size_from'`/`filename_from'` are per-source properties,
   not per-row):

   ```python
   effective_exclude = set(exclude or ())
   if size_from_resolved is None:          # no usable size column for this frame
       effective_exclude |= {"file_size"}
   if filename_from_resolved is None:      # no usable filename column for this frame
       effective_exclude |= {"filename_drift"}
   ```

   **Why `filename_drift` needs the same treatment as `file_size` (finding 1).**
   `filename_drift`'s `required` set is `{artist, title}` only — its filename input is
   `filename_stem`, a *runner parameter* not a canonical field, exactly like
   `file_size_bytes`. So on any frame carrying `artist`+`title` but no resolvable
   filename column (the identity/parquet path where `filename_from'` is `None`, and the
   plain-dict custom-`field_map` path), the runner would be called with
   `filename_stem=None`, block 9 would run, and `None != expected_fn` is always `True` —
   firing `filename_drift` on **every row**. Adding `filename_drift` to
   `effective_exclude` when `filename_from'` is `None` mirrors the `file_size` fix and
   eliminates that per-row noise. The shipped `mp3tag_csv`/`itunes_txt` maps both set a
   filename source, so they are unaffected; this only guards the identity/custom paths.
   `validate_metadata` is also unaffected — it passes a real `filename_stem: str` and
   never excludes the check, so `test_filename_drift`/`test_valid_fields_pass` stay green.

   Because the step-2 pass has already nulled a `size_from`/`filename_from` that points at
   a missing column, these single `… is None` tests cover both "the map never had the
   column" and "the map named one but the DataFrame lacks it" — closing finding 1's
   identity-source gap without a separate `… in df.columns` check.

   **Both auto-excludes intentionally win even over an explicit
   `include=["file_size"]` / `include=["filename_drift"]`.** Per the section-3
   `selected(include) - set(exclude)` rule, `exclude` is applied last, and the id lands in
   `effective_exclude` whenever its runner-parameter source resolved to `None`. So a
   caller who force-includes such a check on a frame with no usable source column gets it
   silently deselected — deliberate, because the check is unrunnable without that source
   (it would otherwise emit a spurious issue on every row). Being deselections rather than
   auto-skips, neither appears in `skipped_checks`.
5. Aggregate: append `result` to `results`, append the row's original index to
   `row_index`, increment `passed` if `result.passed`, update `issue_counts` with every
   `issue.code`, and union `result.skipped` into `skipped_checks`.

### Summary result type

```python
@dataclass
class FrameValidationSummary:
    total: int                               # rows processed
    passed: int                              # rows with result.passed
    results: list[ValidationResult]          # per-row, index-aligned to df.index order
    row_index: list[Any]                     # original df index values, aligned
    issue_counts: Counter[str]               # code -> count across all rows
    skipped_checks: set[str]                 # union of all per-row skipped ids

    @property
    def pass_rate(self) -> float:            # passed / total, 0.0 if total == 0

    def failures(self) -> Iterator[tuple[Any, ValidationResult]]:
        # yields (original_index, result) for rows where not result.passed
```

- **total rows / pass count / pass rate:** `total`, `passed`, `pass_rate`.
- **per-issue-code Counter:** `issue_counts` (keyed by `ValidationIssue.code`).
- **set of skipped checks:** `skipped_checks` (union). A check skipped on *every* row
  is the signal "this source doesn't carry that field" — useful for the itunes_txt case.
- **per-row failure detail:** `results` (full, index-aligned) + `failures()` convenience
  iterator that pairs each failing row's original index with its `ValidationResult`
  (whose `.issues` carry message/code/field). `results[i]` corresponds to
  `row_index[i]`; `failures()` is implemented as
  `zip(self.row_index, self.results)` filtered to `not result.passed`, guaranteeing the
  yielded index is the original DataFrame index for that row.
- **field types (explicit):** `total: int`, `passed: int`, `results:
  list[ValidationResult]`, `row_index: list[Any]` (the DataFrame index values, which may
  be ints, strings, or a MultiIndex tuple — hence `Any`), `issue_counts:
  collections.Counter[str]`, `skipped_checks: set[str]`. `pass_rate` is a computed
  `@property` returning `self.passed / self.total if self.total else 0.0`. The dataclass
  has no pandas types in its signature, so it is importable without pandas (section 6).

Edge cases: empty DataFrame -> `total=0`, `passed=0`, `pass_rate=0.0`, empty
`results`/`row_index`/`issue_counts`/`skipped_checks`.
A column named in the map but absent from the DataFrame is treated as "field not
supplied for any row" (key omitted -> that check auto-skips) rather than an error, so a
partial export still validates what it can; the omission surfaces via `skipped_checks`.
*See Q3 — strict vs lenient column presence.*

---

## 5. Ready-made field maps (sources)

In `field_maps.py`. A `SourceMap` describes how a raw tabular source maps to canonical
fields plus the two "special" derivations:

```python
@dataclass(frozen=True)
class SourceMap:
    name: str
    columns: dict[str, str]        # raw column name -> canonical field name
    filename_from: str | None = None   # raw column to derive filename_stem from
    filename_strip_suffix: str = ".mp3"
    filename_basename: bool = False    # take os.path basename before stripping suffix
    size_from: str | None = None       # raw column feeding file_size_bytes
```

Int-like canonical fields are the set `INT_FIELDS = {"year", "track_number", "bpm",
"discogs_id", "file_size_bytes"}`.

**`INT_FIELDS` home (decided).** `INT_FIELDS` is a new **public module-level constant in
`constants.py`**, exported like the other validation constants (`BPM_MIN`,
`MIN_FILE_SIZE_BYTES`, etc.) and imported where needed by `field_maps.py`/`frame.py`.
`constants.py` is already the single source of truth that both `models.py` and
`checks.py` import from, so it is the natural, dependency-cycle-free home; there is no
duplication of the set anywhere. Definition:

```python
# in constants.py
INT_FIELDS: frozenset[str] = frozenset(
    {"year", "track_number", "bpm", "discogs_id", "file_size_bytes"}
)
```

**`discogs_id` membership (decided — add it).** `discogs_id` **is** a member of
`INT_FIELDS`. It is an integer canonical field (`EXPECTED_FIELDS` includes it, and
`AudioMetadata.discogs_id: int = Field(ge=0)` is a non-optional int — verified in
`models.py`). Note `"year"`, `"track_number"`, `"bpm"`, and `"discogs_id"` are the four
int members that are also canonical `EXPECTED_FIELDS` entries; `"file_size_bytes"` is in
the set too but is **not** a canonical field (it is a runner parameter fed via
`SourceMap.size_from`), so it never lands in the `fields` dict — it is only consulted by
`_coerce_int` when deriving `file_size_bytes`. Adding `discogs_id` means that on any path
where a `discogs_id` column is mapped (the identity source with such a column, or a
custom `field_map`), the cell is `_coerce_int`'d to `int | None` rather than
`_coerce_str`'d to a string. This resolves the finding-6 boundary question: a pandas
`int64` discogs cell becomes a Python `int`, so `discogs_missing` sees a real int
(fires on `None`/`0`, passes otherwise) and `pydantic_fallback` receives an `int` for
`AudioMetadata(discogs_id=... or 0)` with no reliance on pydantic's string-to-int
coercion. Neither shipped source map (`mp3tag_csv`, `itunes_txt`) carries `discogs_id`,
so this only affects the identity/custom paths; on the shipped maps `discogs_missing`
and `pydantic_fallback` still auto-skip as documented.

Because `validate_frame` pulls values out of a pandas DataFrame,
cells are **not** necessarily strings — a numeric column yields Python `int`/`float` or
`numpy.int64`/`numpy.float64`, a blank numeric cell yields `float("nan")`, and an object
column yields `str` (or `None`). The coercion helper `_coerce_int(value) -> int | None`
must therefore handle all of these, in this order:

1. `None` -> `None`. **This is only a fast-path, NOT the sole missing-value gate** —
   step 2 is what actually catches pandas/numpy missing scalars. A bare `value is None`
   must never be the only missing test, or a `pd.NA` from an `Int64` column slips
   through to step 6 and raises on `int(pd.NA)`.
2. pandas/numpy "missing": `pd.isna(value)` is **the single missing-value test** and
   must cover **all** of `None`, `float('nan')`, `numpy.nan`, `pd.NA` (from pandas
   nullable `Int64`/`boolean`/`string` dtypes), and `pd.NaT`. If `pd.isna(value)` is
   `True` -> `None`. Note: reading any numeric column that contains a missing cell
   forces the whole column to `float64`, so an integer BPM like `128` arrives as
   `128.0`; step 2 lets a genuine `NaN` through to `None` here while step 5 narrows a
   real `128.0` back to `128`. `pd.isna` applied to a scalar returns a plain `bool`, so
   this is safe on single cells (never an array). This is the one place the
   row-extraction helper legitimately touches `pd`, which is fine because it only runs
   inside `validate_frame` where pandas is already imported.
3. `bool` -> treat as invalid -> `None` (guard against `True`/`False` sneaking in as 1/0
   from a mis-typed column; a bool is never a valid year/bpm).
4. `int` (and non-bool `numpy` integer) -> `int(value)`.
5. `float`/`numpy` float -> if it is integral (`value == int(value)`) use `int(value)`,
   else `None` (a fractional BPM like `128.5` is not a valid int field; treat as "no
   reliable value" per Q4).
6. `str` -> `strip()`; if empty -> `None`; else `int(stripped)` inside `try/except
   (ValueError, TypeError)` with failure -> `None`.
7. anything else -> `None`.

Non-int canonical fields use `_coerce_str(value) -> str | None`, using the **same**
`pd.isna` missing-value gate: if `value is None` **or** `pd.isna(value)` is `True` ->
`None` (so `pd.NA`/`NaN`/`NaT` are all caught, exactly as in `_coerce_int` step 2 — the
`is None` check is again only a fast-path, never the sole gate); otherwise
`str(value).strip()`, and empty-after-strip -> `None`. (Using
`str(value)` rather than assuming the cell is already a string guards against an object
column that pandas inferred as numeric.) Rationale for coerce-to-`None`-not-raise on a
dirty value: one bad cell must not abort the whole frame; the value-level check then
no-ops (its `if x is not None` / truthiness guard) or, for range checks, simply does not
fire — matching "we couldn't read a reliable number." *Q4 covers an opt-in stricter
`coercion_error` issue.*

### `mp3tag_csv`

```
MTG-Title            -> title
MTG-Subtitle         -> subtitle
MTG-Artist           -> artist
MTG-AlbumArtist      -> album_artist
MTG-Album            -> album
MTG-Year             -> year            (int-coerced)
MTG-TrackNumber      -> track_number    (int-coerced)
MTG-Publisher        -> publisher
MTG-EncodedBy        -> encodedby
MTG-GroupDescription -> grouping
MTG-InitialKey       -> initialkey
MTG-BPM              -> bpm             (int-coerced)
```
`size_from = "MTG-FileSizeBytes"` (int-coerced -> `file_size_bytes`, feeds the
`file_size` check; **not** a normal canonical field, so it is not placed in `fields`).
`filename_from = "MTG-Filename"`, `filename_strip_suffix = ".mp3"`,
`filename_basename = False`. **No `album_artist_sort` column, no Discogs column.**
Consequence: `album_artist_sort` is absent -> part of `missing_fields`' required set
is absent -> `missing_fields` and `pydantic_fallback` auto-skip for this source;
`discogs_id` absent -> `discogs_missing` auto-skips. (This is the desired behavior:
mp3tag CSV simply doesn't carry those, so we don't flag their absence as failures.)

### `itunes_txt`

```
Name          -> title
Artist        -> artist
Album         -> album
Grouping      -> grouping
Track Number  -> track_number   (int-coerced)
Year          -> year           (int-coerced)
```
`filename_from = "Location"`, `filename_basename = True`,
`filename_strip_suffix = ".mp3"` (basename of the path, minus `.mp3`). No `size_from`.

> **Camelot-coded `album` caveat (finding 4).** The `invalid_camelot` check (#5) treats
> canonical `album` as a Camelot code (`album not in CAMELOT_NOTATIONS` fires), because
> in this EDM domain the "album" tag carries the Camelot key notation, not a human album
> title. A genuine iTunes "Album" column holds real album titles, so mapping
> `Album -> album` means `invalid_camelot` will fire on essentially **every** iTunes row.
> This is behavior-consistent (the check is lifted verbatim), not a correctness
> regression — but it is a data-semantics mismatch, so the design makes it explicit and
> the `itunes_txt` map docstring must state it. **Decision:** keep the `Album -> album`
> mapping (so a library that *does* use Camelot album codes still validates), and
> **document that genuine iTunes libraries should pass `exclude=["invalid_camelot"]`** to
> `validate_frame`. The map docstring carries this guidance and a one-line example. An
> implementer must not silently drop the mapping; the exclude-on-call pattern keeps the
> single-source-of-truth map general while letting standard iTunes exports opt out of the
> false-firing check.
Carries **none** of `bpm, initialkey, encodedby, album_artist, album_artist_sort,
subtitle, publisher, discogs_id`. With the intersection-based required sets, the checks
that auto-skip for this source (land in `skipped_checks`) are exactly those whose
**entire** required set is absent: `bpm_range` (bpm absent), `corrupted_field` and
`key_album_mismatch` (initialkey absent), `subtitle_drift` (bpm/subtitle/etc absent),
`discogs_missing` (discogs_id absent), `missing_fields` and `pydantic_fallback`
(album_artist_sort etc absent), and `bpm_track_mismatch` (bpm absent).
`artist_field_mismatch` **runs** (its required set is just `artist`, which is present)
and no-ops because album_artist/album_artist_sort are absent — it does NOT appear in
`skipped_checks`. `publisher_grouping` **runs** (empty required) and no-ops because
publisher is absent and grouping!=publisher comparison needs both. What actively
validates: `year_range`, `invalid_camelot` (album present), `filename_drift`
(artist+title present), `title_format`. `file_size` is auto-excluded here (Q2) because
itunes_txt has no `size_from` and no DataFrame size column, so the **resolved
`size_from'` is `None`** and the adapter adds `file_size` to `effective_exclude`
automatically — no "could not read file size" noise on any row.

### Precedence when both `source` and `field_map` are given (decided)

`source` is a string key resolved via an internal `_SOURCES: dict[str, SourceMap] =
{"mp3tag_csv": mp3tag_csv, "itunes_txt": itunes_txt}`; an unknown `source` string raises
`ValueError` listing the valid keys. The resolution of `(source, field_map)` into one
effective `SourceMap` is:

1. **Both `None`** -> identity source: build `columns` as `{name: name for name in
   EXPECTED_FIELDS}` (14 canonical names mapped to themselves). The two structural
   derivation fields are set **conditionally on the column existing in `df.columns`**,
   mirroring each other: `filename_from = "filename_stem"` if that column is present else
   `None`; `size_from = "file_size_bytes"` if that column is present else `None`.
   (`file_size_bytes` is deliberately **not** added to `columns` — it is not a canonical
   field — it only ever flows through `size_from`.) This conditional `size_from` is what
   lets the Q2 auto-exclude (finding 1) fire for an identity frame that lacks a size
   column: `size_from` resolves to `None`, so `file_size` is added to
   `effective_exclude` and no "could not read file size" noise appears. (The "my
   DataFrame already uses canonical names" path. Any canonical column not actually
   present in the DataFrame is additionally dropped by step 2 of the per-row flow.)
2. **`source` only** -> the named `SourceMap` as-is.
3. **`field_map` only, as a plain `dict[str, str]`** -> a `SourceMap(name="custom",
   columns=dict(field_map))` with default derivation fields (`filename_from=None`,
   `size_from=None`). **Dict convention (fixed): keys are raw DataFrame column names,
   values are canonical field names** — same direction as `SourceMap.columns`. This is
   stated in the docstring with an example to remove any doubt.
4. **`field_map` only, as a `SourceMap`** -> used directly.
5. **`source` + plain `dict` `field_map`** -> start from the named `SourceMap`;
   produce a new `SourceMap` whose `columns` is `{**base.columns, **field_map}` (the
   override dict wins per raw-column key, and may add new raw->canonical pairs); the
   structural fields (`filename_from`, `filename_strip_suffix`, `filename_basename`,
   `size_from`) are inherited from the base unchanged. Covers the common "mp3tag_csv but
   my export renamed one column" case: the caller adds `{"My-Title": "title"}`; if they
   also want the stale `MTG-Title` gone they omit it from the DataFrame (absent columns
   are dropped in per-row step 2) or pass a full `SourceMap`.
6. **`source` + `SourceMap` `field_map`** -> the passed `SourceMap` replaces the base
   entirely (including all structural fields). A power user wanting different derivations
   takes this path.

Because `SourceMap` is frozen, merges produce a new instance via
`dataclasses.replace(base, columns={**base.columns, **field_map})` rather than mutating.
All of this is resolved **once** per `validate_frame` call, before row iteration.

---

## 6. Pandas optionality mechanism

`pyproject.toml` changes:

```toml
[project.optional-dependencies]
pandas = ["pandas>=2.0.0"]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "ruff>=0.5.0",
    "pre-commit>=3.5.0",
    "pandas>=2.0.0",
    "pyarrow>=14",      # parquet round-trip in tests
]
```

- pandas stays **out** of `[project].dependencies`; base install remains pydantic-only.
- `pandas` extra installs via `pip install "data-quality[pandas]"`.
- dev extra gains pandas + pyarrow so the test suite can exercise `validate_frame` and
  parquet inputs. pyarrow is test-only (parquet read), never imported by library code.
- Guard against regressions with an import test (`test_pandas_optional.py`):
  1. Assert `import data_quality.music_edm` and `from data_quality.music_edm import
     validate_row, validate_frame, FrameValidationSummary` all succeed (these run with
     pandas installed in dev, but the assertion documents that the names bind without
     touching pandas).
  2. Assert the missing-pandas error path. Since dev installs pandas, simulate absence
     deterministically by monkeypatching `builtins.__import__` so that an attempted
     `import pandas` raises `ImportError`, while all other imports pass through to the
     real `__import__`:

     ```python
     def test_validate_frame_without_pandas(monkeypatch):
         real_import = builtins.__import__

         def fake_import(name, *args, **kwargs):
             if name == "pandas" or name.startswith("pandas."):
                 raise ImportError("No module named 'pandas'")
             return real_import(name, *args, **kwargs)

         monkeypatch.setattr(builtins, "__import__", fake_import)
         # Pass a stand-in object; the pandas import inside validate_frame must
         # fail before the object is ever used.
         with pytest.raises(ImportError, match=r"data-quality\[pandas\]"):
             validate_frame(object(), source="itunes_txt")
     ```

     This is reliable because `validate_frame` imports pandas as its first action, so
     the patched `__import__` triggers the actionable `ImportError` before any DataFrame
     operation. `monkeypatch` restores `__import__` automatically at test teardown.
     Do **not** attempt to uninstall pandas or purge `sys.modules["pandas"]`, which is
     brittle and can leak across tests.

---

## Public API additions (`music_edm/__init__.py`)

Add to exports: `validate_row`, `validate_frame`, `FrameValidationSummary`,
`list_checks`, `Check`, `CHECK_REGISTRY`, `SourceMap`, `mp3tag_csv`, `itunes_txt`.
Keep all existing exports. `validate_frame`/`FrameValidationSummary` importable without
pandas (names only; pandas touched lazily at call time).

---

## Testability

- **Registry/row runner — unit tests (no pandas):** id-list stability (`list_checks()`
  equals the documented order); `include`/`exclude` selection incl. the
  `include - exclude` rule and unknown-id `ValueError`; auto-skip present-vs-absent-vs-
  None matrix for a representative check (e.g. `bpm_range`: key absent -> skipped; key
  None -> runs, no issue; out-of-range -> issue); `skipped` list population.
- **Behavior preservation:** the existing 42 tests are the gate and must pass unchanged.
- **Field maps — unit tests:** mp3tag_csv and itunes_txt produce the expected canonical
  dict from a sample raw row (incl. int coercion, blank->None, filename derivation,
  basename handling, `.mp3` strip); `source`+`field_map` precedence.
- **Pandas adapter — integration tests (dev extra):** small DataFrame -> correct
  `total`/`passed`/`pass_rate`/`issue_counts`/`skipped_checks`/`failures()`; empty
  DataFrame edge case; a parquet round-trip via pyarrow to prove origin-independence;
  itunes_txt frame shows the expected large `skipped_checks` set and no `file_size`
  noise (Q2 auto-exclude).
- **Optionality:** `test_pandas_optional.py` as in section 6.

Everything except the pandas adapter is unit-testable with plain dicts; the adapter is
a thin mapping+aggregation layer, which is the only part needing pandas and is covered
by integration tests. A design this shaped keeps the risky logic (the 16 checks) in
pure, pandas-free, dict-in/result-out functions.

---

## Open questions (each with a recommendation)

- **Q1 — check granularity for merged/multi-code blocks.** Block 7 emits two codes from
  one unit, and blocks 12+13 are merged. A consumer might want to disable *just* the
  bracket-number check or *just* `invalid_key`. **Recommendation:** ship the coarse
  units now (one `key_album_mismatch`, one `publisher_grouping`) to guarantee identical
  behavior and ordering; revisit finer splitting only if a consuming repo asks. Noted
  as a known limitation, not a blocker.
- **Q2 — `file_size` on sources with no size column.** It (like `publisher_grouping`)
  has empty `required` so never auto-skips, and on the row/frame path its
  `file_size_bytes is None` branch would flag "could not read file size" on every
  itunes_txt row. **Recommendation (adopt, and reflected in the per-row flow):**
  `validate_frame` resolves `size_from` against `df.columns` in step 2 (nulling it if
  the named column is absent); if the **resolved `size_from'` is `None`**, the adapter
  adds `"file_size"` to `effective_exclude` so the check is deselected for every row (it
  will not appear in `skipped_checks` either, since exclusion is not a skip — it's a
  deselection). This single resolved-`size_from'`-is-`None` test subsumes the former
  "`size_from is None` AND no literal `file_size_bytes` column" phrasing and, critically,
  covers the identity source (whose `size_from` is set conditionally on the column
  existing — precedence case 1), closing finding 1.
  `validate_row`/`validate_metadata` are unaffected: they always run
  `file_size`, preserving the `file_size_bytes=None` -> "could not read file size" test.
  `publisher_grouping` needs no such treatment because its guards emit nothing when the
  fields are absent (no false-positive noise).
- **Q3 — strict vs lenient when a mapped column is missing from the DataFrame.**
  **Recommendation:** lenient by default (omit the field -> check auto-skips ->
  surfaces in `skipped_checks`), because partial exports are common and the summary
  already makes skips visible. Consider a future `strict=True` flag to raise instead.
- **Q4 — unparseable int-like value (e.g. `"128a"` in a BPM cell).** **Recommendation:**
  coerce-to-None (treat as "no reliable value") rather than raising, so one dirty cell
  doesn't abort a whole frame; the row still validates its other fields. If stricter
  signalling is wanted later, emit a dedicated `coercion_error` issue — out of scope now.
- **Q5 — `ValidationResult.skipped` lives on the core result type.** It's a small
  additive field on a domain-agnostic class. **Recommendation (adopt):** in
  `core/result.py`, add one line to `ValidationResult.__init__`:
  `self.skipped: list[str] = []`, placed after `self.fields`. No other method changes;
  `__bool__`/`add_issue`/`flagged_fields` are untouched. This is backward compatible
  with every assertion in `test_core_result.py` (none inspect `skipped`, and
  `test_starts_passing_and_empty` only checks `passed`/`issues`/`bool`). It's generic
  ("checks not applicable to this item"), so it also keeps the core type domain-agnostic
  and the row/frame API uniform. The runner is the only writer; `validate_metadata`
  leaves it `[]`.

---

## Responses to design-review findings (revision pass)

Review: `.agents/tasks/design-review.md` — verdict CHANGES_REQUESTED (3 MEDIUM, 3 NIT).
All six findings are addressed in this revision; none backlogged or ignored.

- **Finding 1 (MEDIUM) — identity source defeats Q2 `file_size` auto-exclude.**
  *Addressed.* Section 5 precedence case 1 now sets the identity source's
  `size_from = "file_size_bytes"` **only when that column is present** in `df.columns`
  (mirroring `filename_from`), and section 4 step 4 + Q2 now key the auto-exclude off the
  **resolved `size_from'` being `None`** rather than the raw `SourceMap.size_from`. An
  identity frame lacking a size column resolves `size_from'` to `None`, so `file_size` is
  excluded and the per-row "could not read file size" noise is gone.

- **Finding 2 (MEDIUM) — absent-column drop rule did not cover `filename_from`/
  `size_from`.** *Addressed.* Section 4 step 2 now states explicitly that the
  absent-column rule applies to the two structural derivation fields (not members of
  `columns`): a `filename_from`/`size_from` naming a column absent from `df.columns` is
  nulled for the call, and `size_from`-absence then triggers the finding-1 auto-exclude.
  The step now produces a resolved tuple whose names are guaranteed present or `None`.

- **Finding 3 (MEDIUM) — `INT_FIELDS` home + `discogs_id` membership unspecified.**
  *Addressed.* Section 5 now pins `INT_FIELDS` as a **public `frozenset` in
  `constants.py`** (the existing single source of truth that `models.py` and `checks.py`
  already import, so no cycle, no duplication) and **adds `discogs_id` to the set**,
  since `AudioMetadata.discogs_id: int = Field(ge=0)` is a non-optional int (verified in
  `models.py`).

- **Finding 4 (NIT) — itunes_txt `Album -> album` false-fires `invalid_camelot`.**
  *Addressed.* The `itunes_txt` map section now documents that `album` is Camelot-coded
  in this domain, that genuine iTunes exports will flag `invalid_camelot` on every row,
  and that such libraries should pass `exclude=["invalid_camelot"]`. The mapping is kept
  (map stays general) with the opt-out pattern documented in the map docstring.

- **Finding 5 (NIT) — `validate_metadata` wrapper type surface.** *Addressed.*
  Section 2 now states the wrapper **retains its current annotations**
  (`fields: dict[str, Any]`, `filename_stem: str` non-optional,
  `file_size_bytes: int | None = None`); only the body changes. The code block shows the
  explicit annotations.

- **Finding 6 (NIT) — `_coerce_str` vs `discogs_id` on the identity path.** *Addressed*
  via finding 3: with `discogs_id` in `INT_FIELDS`, a mapped `discogs_id` cell is
  `_coerce_int`'d to `int | None`, so `discogs_missing` and `pydantic_fallback` receive a
  real int with no reliance on pydantic string-to-int coercion. Section 5's INT_FIELDS
  block spells this boundary out.

The one review "Unverified/Wrong assumption" that was not a scored finding (row/frame
divergence for sources missing `album_artist_sort`) remains as the design already
described it: it is the intended "disable checks that aren't relevant" behavior confined
to the row/frame path (the `validate_metadata` wrapper uses `_resolve_all` and is
unaffected, protecting the 42-test gate). The related `itertuples` concern is now a
scored finding (finding 1) and is resolved there by pinning label-based iteration via
`df.to_dict(orient="records")` zipped with `df.index`; `row_index: list[Any]` with
`results[i]`/`row_index[i]` alignment remains the index-handling constraint (an index
value may be an int, string, or MultiIndex tuple — hence `Any`).

---

## Responses to design-review findings (second revision pass)

Review: `.agents/tasks/design-review.md` — verdict CHANGES_REQUESTED (3 MEDIUM, 2 NIT).
All five findings are addressed in this revision; none backlogged or ignored.

- **Finding 1 (MEDIUM) — row iteration left ambiguous (`itertuples` vs `iterrows`).**
  *Addressed.* Section 4 step 3 now pins **label-based** iteration via
  `zip(df.index, df.to_dict(orient="records"))` with `row.get(raw_col)`, explicitly
  **prohibits `itertuples`** (its namedtuple attributes rewrite hyphen/space column
  names and break the shipped `mp3tag_csv`/`itunes_txt` maps), and names
  `df.loc[idx][raw_col]` as the only acceptable alternative. The `(or iterrows)`
  wording is gone.

- **Finding 2 (MEDIUM) — `pd.isna` not pinned as the sole missing-value gate for
  nullable (`Int64`/`pd.NA`) dtypes.** *Addressed.* Section 5 `_coerce_int` step 1 now
  states the `value is None` check is only a fast-path and must never be the sole gate;
  step 2 states `pd.isna` is the single missing-value test covering `None`,
  `float('nan')`, `numpy.nan`, `pd.NA`, and `pd.NaT`, with the explicit warning that a
  bare `is None` lets `pd.NA` reach `int(pd.NA)` and raise. `_coerce_str` is updated with
  mirrored wording.

- **Finding 3 (MEDIUM) — `_resolve_all` presence-universe shown only in prose; risked
  `test_missing_keys_treated_as_none` regression.** *Addressed.* Section 3 now shows the
  presence-set construction in code — `present = set(EXPECTED_FIELDS) if _resolve_all
  else set(fields)`, with "a check runs iff `check.required <= present`" — and states
  `present` (not `result.fields`, not the raw dict) is the auto-skip gate input. The
  Section 2 contract item 3 and the "Important interaction" prose now reference this
  branch, making the `validate_metadata({}, ...)` -> full-`present` -> `missing_fields`
  fires path explicit.

- **Finding 4 (NIT) — flat ordered id list not stated as one enumerated sequence.**
  *Addressed.* Section 1 now carries the literal 15-id tuple in registry order, flagged
  as exactly what `list_checks()` returns (the testable id-stability spec), with notes
  that `publisher_grouping` is position 12 (merged 12+13) and `invalid_key` is a code,
  not an id.

- **Finding 5 (NIT) — `include=["file_size"]` colliding with Q2 auto-exclude not called
  out.** *Addressed.* Section 4 step 4 now states the auto-exclude intentionally wins
  over an explicit `include=["file_size"]` (the check is unrunnable without a size
  source) and that, being a deselection, it does not appear in `skipped_checks`.


## Responses to design-review findings (third pass)

The third-pass review returned CHANGES_REQUESTED with 3 MEDIUM + 2 NIT and verified the
behavior-preservation core clean. The three MEDIUM findings are resolved here; the two
NITs are accepted and noted. These are the final design edits.

- **Finding 1 (MEDIUM) — `filename_drift` fires on every row when `filename_from`
  resolves to `None`.** *Addressed.* Section 4 step 4 now gives `filename_drift` the same
  runner-parameter auto-exclude as `file_size`: when the resolved `filename_from'` is
  `None` (identity/parquet path with no `filename_stem` column, or a plain-dict custom
  `field_map` with no filename source), the adapter adds `filename_drift` to
  `effective_exclude` once, before row iteration. Symmetric with the `file_size`/`size_from'`
  treatment; a deselection (not an auto-skip, so not in `skipped_checks`); wins over an
  explicit `include=["filename_drift"]`. The shipped `mp3tag_csv`/`itunes_txt` maps set a
  filename source and are unaffected; `validate_metadata` passes a real `str`
  `filename_stem` and never excludes, so `test_filename_drift`/`test_valid_fields_pass`
  stay green. Section 1 check #9 row annotated accordingly.

- **Finding 2 (MEDIUM) — include/exclude id-validation timing unspecified; empty-frame
  typo escapes.** *Addressed.* Section 3 "Id validation" now pins that the caller's
  `include`/`exclude` ids are validated against `_REGISTRY_BY_ID` **once, up front, before
  row iteration and regardless of DataFrame emptiness**, in both `validate_row` and
  `validate_frame`. `validate_frame` validates the caller's raw sets first, then merges
  the known-valid auto-exclude ids, so an empty-frame typo (`exclude=["flie_size"]`) still
  raises.

- **Finding 3 (MEDIUM) — `include=[]` behavior undefined.** *Addressed (option b).*
  Section 3 now specifies that a non-None empty `include` raises
  `ValueError("include must be a non-empty iterable of check ids or None")`, matching the
  fail-fast stance and avoiding a silent all-pass. Empty `exclude=[]` remains benign
  (excludes nothing). A test asserting the raise is added to the Testability list.

- **Finding 4 (NIT) — duplicate-index `df.loc[idx][raw_col]` fallback ambiguous.**
  *Accepted.* The canonical, duplicate-safe iteration is the `zip(df.index,
  df.to_dict(orient="records"))` form already pinned in Section 4 step 3; the
  `df.loc[idx][raw_col]` alternative is dropped as an option (it returns a sub-frame on
  duplicate labels). Implementation must use only the zip form.

- **Finding 5 (NIT) — `_coerce_int` non-finite float guard.** *Accepted.* `_coerce_int`
  step 5 must guard integral-float conversion with `math.isfinite(value)` (or catch
  `OverflowError`/`ValueError`), returning `None` for `inf`/`-inf` so a single non-finite
  cell cannot raise out of `validate_frame` (upholding the "one bad cell must not abort
  the frame" contract). `pd.isna` already handles `NaN` in step 2.

### Added testability items (finding-driven)

- `validate_frame` on an identity/canonical-name frame **without** a `filename_stem`
  column does not emit `filename_drift` on any row (finding 1).
- `validate_frame` on an **empty** DataFrame with a typo'd `exclude` id raises
  `ValueError` (finding 2).
- `validate_row`/`validate_frame` with `include=[]` raises `ValueError` (finding 3).
- `_coerce_int(float("inf"))` returns `None` and does not raise (finding 5).
