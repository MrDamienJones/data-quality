# data-quality

Shared data quality checks reused across repositories. Maintain the checks here
once, pull them into any consumer repo from Git, and pin a version per repo.

The library ships Pydantic v2 models **and** reusable check functions — not just
constants. Consumers can import the validation logic itself.

## Domains

| Domain | Package | Status | Docs |
|--------|---------|--------|------|
| Music  | `data_quality.music`  | Implemented | [music/README.md](src/data_quality/music/README.md) |
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
  src/data_quality/
    core/        # ValidationIssue, ValidationResult (no domain knowledge, no I/O)
    music/       # audio metadata: constants.py, models.py, checks.py
    garmin/      # placeholder
    pdf/         # placeholder
  tests/
```

Each domain subpackage follows the same three-file shape:

- `constants.py` — ranges, enums, lookup tables (the single source of truth)
- `models.py` — Pydantic v2 models and validators
- `checks.py` — a `validate_*` function that takes an already-extracted dict of
  fields and returns a `data_quality.core.ValidationResult`

File I/O (reading tags, stat-ing files) stays in the consumer. The library
validates plain data, which keeps it dependency-light and reusable across
domains.

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

## Quick start

```python
from data_quality.music import validate_metadata

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

See the [music docs](src/data_quality/music/README.md) for the full field list,
every check, and the Pydantic model.

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

## Versioning

Tag releases with semantic versions (`v0.1.0`, `v0.2.0`, ...). Consumers pin to a
tag so upgrading one repo never silently breaks another. Bump the `version` in
`pyproject.toml` and create a matching Git tag for each release:

```powershell
git tag v0.1.0 -m "First release"
git push origin v0.1.0
```
