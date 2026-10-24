# data-quality

Shared data quality checks reused across repositories. Maintain the checks here
once, pull them into any consumer repo from Git, and pin a version per repo.

The library ships Pydantic v2 models **and** reusable check functions — not just
constants. Consumers can import the validation logic itself.

## Domains

| Domain | Package | Status | Docs |
|--------|---------|--------|------|
| Music (EDM) | `data_quality.music_edm` | Implemented | [music_edm/README.md](src/data_quality/music_edm/README.md) |
| Garmin | `data_quality.garmin` | Placeholder | [garmin/README.md](src/data_quality/garmin/README.md) |
| PDF    | `data_quality.pdf`    | Placeholder | [pdf/README.md](src/data_quality/pdf/README.md) |

Domain-agnostic result primitives (`ValidationIssue`, `ValidationResult`) live
in `data_quality.core` — see [core/README.md](src/data_quality/core/README.md).

## Layout

```
data-quality/
  pyproject.toml
  requirements-dev.txt
  .pre-commit-config.yaml
  docs/                   # architecture notes
  src/data_quality/
    core/        # ValidationIssue, ValidationResult (no domain knowledge, no I/O)
    music_edm/   # EDM audio metadata: constants, models, checks, registry,
                 #   field_maps, frame (optional pandas adapter)
    garmin/      # placeholder
    pdf/         # placeholder
  tests/
```

Each domain subpackage is built around:

- `constants.py` — ranges, enums, lookup tables (the single source of truth)
- `models.py` — Pydantic v2 models and validators
- `checks.py` / `registry.py` — the named checks and the runners
  (`validate_metadata`, `validate_row`) that return a
  `data_quality.core.ValidationResult`
- `field_maps.py` + `frame.py` — ready-made source column maps and the optional
  pandas `validate_frame` adapter

File I/O (reading tags, stat-ing files, reading CSV/parquet) stays in the
consumer. The library validates plain data — a dict or a DataFrame — which keeps
it dependency-light and reusable across domains.

## Install

Pin a tagged release (recommended):

```bash
pip install "git+https://github.com/MrDamienJones/data-quality.git@v0.1.0"
```

Track the default branch (less stable):

```bash
pip install "git+https://github.com/MrDamienJones/data-quality.git@main"
```

In a consumer repo's `requirements.txt`:

```
data-quality @ git+https://github.com/MrDamienJones/data-quality.git@v0.1.0
```

Or in a consumer `pyproject.toml`:

```toml
dependencies = [
    "data-quality @ git+https://github.com/MrDamienJones/data-quality.git@v0.1.0",
]
```

### Optional pandas extra

The DataFrame adapter (`validate_frame`) needs pandas. It's an **optional**
extra — pydantic is the only hard dependency, and importing the package never
pulls pandas. Install it only in repos that validate DataFrames:

```bash
pip install "data-quality[pandas] @ git+https://github.com/MrDamienJones/data-quality.git@v0.1.0"
```

A repo that only validates one record at a time (dicts) needs nothing extra.

## Quick start

```python
from data_quality.music_edm import validate_metadata

fields = {
    "bpm": 128, "track_number": 128, "title": "Track (Mix)",
    "artist": "Artist", "album": "08B-CM", "initialkey": "C",
    "encodedby": "me", "album_artist": "Artist",
    "album_artist_sort": "Artist",
    "subtitle": "Artist - Track (Mix) 08B-CM 128 2020",
    "publisher": None, "grouping": None, "year": 2020, "discogs_id": 12345,
}

result = validate_metadata(fields, filename_stem="Artist-Track-Mix", file_size_bytes=5_000_000)

if not result.passed:
    for issue in result.issues:
        print(issue.code, issue.field, str(issue))
```

### Validate a DataFrame (any origin)

Once your CSV, text export, or parquet is a DataFrame, validation is identical.
Ready-made column maps mean you don't hand-write the mapping:

```python
import pandas as pd
from data_quality.music_edm import validate_frame

df = pd.read_parquet("tracks.parquet")          # or read_csv / read_table
summary = validate_frame(df, source="mp3tag_csv")

summary.pass_rate        # fraction of rows with no issues
summary.issue_counts     # Counter of issue code -> count
summary.skipped_checks   # checks skipped because their columns are absent
for idx, result in summary.failures():
    print(idx, [i.code for i in result.issues])
```

### Turn off checks that don't apply

`exclude` drops checks; `include` restricts to a subset. Checks whose columns
are simply absent from the DataFrame **auto-skip** (reported in
`skipped_checks`), so a sparse source doesn't produce false failures:

```python
# iTunes exports put real album titles in "album"; skip the Camelot-album check
validate_frame(df, source="itunes_txt", exclude=["invalid_camelot"])

# the same toggles exist for single records
from data_quality.music_edm import validate_row, list_checks
validate_row(fields, exclude=["discogs_missing"])
list_checks()            # the 15 check ids you can include/exclude
```

See the [music_edm docs](src/data_quality/music_edm/README.md) for the full field list,
all 15 checks, the source maps, and the Pydantic model.

## Development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -e ".[dev]"
pip install -r requirements-dev.txt   # dev tooling + pre-commit
pre-commit install                    # installs commit + push hooks
pytest
```

Run the hooks across the whole tree at any time (with the venv activated, so
the local `pytest` hook resolves `python -m pytest` against it):

```powershell
pre-commit run --all-files
```

### Pre-commit hooks

Configured in `.pre-commit-config.yaml`:

- Standard hygiene (trailing whitespace, end-of-file, YAML/TOML checks,
  large-file guard) and [ruff](https://docs.astral.sh/ruff/) for lint + format.
- A local `pytest` hook so the suite runs before each commit.
- Two hooks pulled from
  [MrDamienJones/aws-precommit-hooks](https://github.com/MrDamienJones/aws-precommit-hooks):
  - `no-real-aws-account-ids` — blocks committing a real 12-digit AWS account id.
  - `no-push-from-main` — blocks pushing directly from `main` (branch + PR flow).

The three CDK/Terraform-specific hooks in that repo
(`no-destroy-removal-policy`, `no-committed-iac-state`,
`require-cdk-nag-present`) are intentionally **not** included — this is a pure
Python library with no infrastructure code for them to act on.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request:
it installs the package with the `dev` + `pandas` extras and runs `ruff check`,
`ruff format --check`, and `pytest` on Linux / Python 3.12. The job uses
read-only permissions. Pair it with branch protection on GitHub (require the
check to pass before merging) for real enforcement — the local pre-commit hooks
are a convenience, CI is the gate that can't be skipped with `--no-verify`.

## Versioning

Tag releases with semantic versions (`v0.1.0`, `v0.2.0`, ...). Consumers pin to a
tag so upgrading one repo never silently breaks another. Bump the `version` in
`pyproject.toml` and create a matching Git tag for each release:

```powershell
git tag v0.1.0 -m "First release"
git push origin v0.1.0
```
