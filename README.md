# data-quality

Shared data quality checks reused across repositories. Maintain the checks here
once, pull them into any consumer repo from Git, and pin a version per repo.

The library ships reusable check functions, not only constants. Consumers
import the validation logic itself.

## Domains

| Domain | Package | Status | Docs |
|--------|---------|--------|------|
| Music (EDM) | `data_quality.music_edm` | Implemented | [music_edm/README.md](src/data_quality/music_edm/README.md) |

Domain-agnostic result primitives (`ValidationIssue`, `ValidationResult`) live
in `data_quality.core` — see [core/README.md](src/data_quality/core/README.md).

## Layout

```
data-quality/
  pyproject.toml
  .pre-commit-config.yaml
  docs/                   # architecture notes
  src/data_quality/
    core/        # ValidationIssue, ValidationResult (no domain knowledge, no I/O)
    music_edm/   # EDM audio metadata: constants, filenames, checks, registry,
                 #   field_maps, frame and reconcile (optional pandas)
  tests/
```

Each domain subpackage is built around the modules below. To add a domain,
create `src/data_quality/<domain>/` with the same modules, and re-export its
public API from its `__init__.py` so consumers can write
`from data_quality.<domain> import validate_...`:

- `constants.py` — ranges, enums, lookup tables (the single source of truth)
- `checks.py` / `registry.py` — the named checks and the runners
  (`validate_metadata`, `validate_row`) that return a
  `data_quality.core.ValidationResult`
- `field_maps.py` + `frame.py` — ready-made source column maps and the optional
  pandas `validate_frame` adapter
- `reconcile.py` — `reconcile_frames`, which compares two sources of the same
  data (optional pandas)

File I/O (reading tags, reading CSV/parquet) stays in the
consumer. The library validates plain data — a dict or a DataFrame — which keeps
it dependency-light and reusable across domains.

## Install

Pin a tagged release (recommended):

```bash
pip install "git+https://github.com/MrDamienJones/data-quality.git@v0.3.0"
```

Track the default branch (less stable):

```bash
pip install "git+https://github.com/MrDamienJones/data-quality.git@main"
```

In a consumer repo's `requirements.txt`:

```
data-quality @ git+https://github.com/MrDamienJones/data-quality.git@v0.3.0
```

Or in a consumer `pyproject.toml`:

```toml
dependencies = [
    "data-quality @ git+https://github.com/MrDamienJones/data-quality.git@v0.3.0",
]
```

### Optional pandas extra

The DataFrame adapter (`validate_frame`) and the cross-source check
(`reconcile_frames`) need pandas. It's an **optional** extra — pydantic is the
only hard dependency, and importing the package never pulls pandas. Install it
only in repos that validate DataFrames:

```bash
pip install "data-quality[pandas] @ git+https://github.com/MrDamienJones/data-quality.git@v0.3.0"
```

A repo that only validates one record at a time (dicts) needs nothing extra.

## Quick start

```python
from data_quality.music_edm import validate_metadata

fields = {
    "bpm": 128,
    "track_number": 128,
    "title": "Track (Mix)",
    "artist": "Artist",
    "album": "08B-CM",
    "initialkey": "C",
    "encodedby": "me",
    "album_artist": "Artist",
    "album_artist_sort": "Artist",
    "subtitle": "Artist - Track (Mix) 08B-CM 128 2020",
    "publisher": None,
    "grouping": None,
    "year": 2020,
    "discogs_id": 12345,
}

result = validate_metadata(fields, filename_stem="Artist-Track-Mix")

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

df = pd.read_parquet("tracks.parquet")  # or read_csv / read_table
summary = validate_frame(df, source="mp3tag_csv")

summary.pass_rate  # fraction of rows with no issues
summary.issue_counts  # Counter of issue code -> count
summary.skipped_checks  # checks skipped because their columns are absent
summary.checks_run  # checks that ran (compare with checks_selected)
for idx, result in summary.failures():
    print(idx, [i.code for i in result.issues])
```

### Turn off checks that don't apply

`exclude` drops checks; `include` restricts to a subset. Checks whose columns
are simply absent from the DataFrame **auto-skip** (reported in
`skipped_checks`), so a sparse source doesn't produce false failures:

```python
# a library whose iTunes "Album" holds real album titles, not Camelot codes
validate_frame(df, source="itunes_txt", exclude=["invalid_camelot"])

# the same toggles exist for single records
from data_quality.music_edm import validate_row, list_checks

validate_row(fields, exclude=["discogs_missing"])
list_checks()  # the 16 check ids you can include/exclude
```

See the [music_edm docs](src/data_quality/music_edm/README.md) for the full field list,
all 16 checks, the source maps, and the cross-source check.

## Development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -e ".[dev]"               # package + test/lint tooling + pandas
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
  large-file guard, merge-conflict markers, LF line endings) and
  [ruff](https://docs.astral.sh/ruff/) for lint + format.
- [gitleaks](https://github.com/gitleaks/gitleaks) scans the staged changes for
  secrets. pre-commit downloads Go to build it the first time, so the first run
  takes a few minutes.
- A local `pytest` hook so the suite runs before each commit.
- Two hooks pulled from
  [MrDamienJones/aws-precommit-hooks](https://github.com/MrDamienJones/aws-precommit-hooks):
  - `no-real-aws-account-ids` — blocks committing a real 12-digit AWS account id.
  - `no-push-from-main` — blocks pushing directly from `main` (branch + PR flow).

The three CDK/Terraform-specific hooks in that repo
(`no-destroy-removal-policy`, `no-committed-iac-state`,
`require-cdk-nag-present`) are intentionally **not** included — this is a pure
Python library with no infrastructure code for them to act on.

CI runs the same hooks at the same versions, so a commit that passes locally
passes the CI lint step. When you change the ruff `rev`, change the `ruff` pin
in the `dev` extra of `pyproject.toml` to match. Update all hook versions with
`pre-commit autoupdate`.

`.gitattributes` stores and checks out every text file with LF line endings.
Without it, Git for Windows (`core.autocrlf=true`) checks files out with CRLF,
and the line-ending hook rewrites them on every commit.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request,
with read-only permissions. It has four jobs:

| Job | What it does |
|---|---|
| `hooks` | Runs the pre-commit hooks on all files (lint, format, hygiene, AWS account ids). It skips `pytest`, `no-push-from-main` and `gitleaks`, which the other jobs cover or which only apply locally. |
| `secrets` | Runs gitleaks over every commit in the history. Keep its `GITLEAKS_VERSION` equal to the gitleaks `rev` in `.pre-commit-config.yaml`. |
| `test` | Installs the `dev` extra and runs `pytest` on Python 3.12 and 3.13. |
| `package` | Builds the wheel, installs it into a clean environment with no extras, and runs `scripts/smoke_test.py`. This proves the wheel works and that the base install needs no pandas. |

Pair CI with branch protection on GitHub (require the checks to pass before
merging) for real enforcement — the local pre-commit hooks are a convenience,
CI is the gate that can't be skipped with `--no-verify`.

## Versioning

Tag releases with semantic versions (`v0.2.0`, `v0.3.0`, ...). Consumers pin to a
tag so upgrading one repo never silently breaks another. Bump the `version` in
`pyproject.toml` and create a matching Git tag for each release:

```powershell
git tag v0.2.0 -m "Registry, DataFrame adapter and cross-source check"
git push origin v0.2.0
```
