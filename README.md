# data-quality

Shared data quality checks reused across repositories. Maintain the checks here
once, pull them into any consumer repo from Git, and pin a version per repo.

The library ships Pydantic v2 models **and** reusable check functions — not just
constants. Consumers can import the validation logic itself.

Current domains:

- `data_quality.music` — audio metadata checks (ported from the music pipeline),
  decoupled from file I/O so they run on a plain dict of fields.
- `data_quality.garmin` — placeholder for future Garmin-file checks.
- `data_quality.pdf` — placeholder for future PDF checks.

## Install

Replace `<your-github-username>` with your GitHub account.

Pin a tagged release (recommended):

```bash
pip install "git+https://github.com/<your-github-username>/data-quality.git@v0.1.0"
```

Track the default branch (less stable):

```bash
pip install "git+https://github.com/<your-github-username>/data-quality.git@main"
```

In a consumer repo's `requirements.txt`:

```
data-quality @ git+https://github.com/<your-github-username>/data-quality.git@v0.1.0
```

Or in a consumer `pyproject.toml`:

```toml
dependencies = [
    "data-quality @ git+https://github.com/<your-github-username>/data-quality.git@v0.1.0",
]
```

## Usage

### Validate audio metadata with the Pydantic model

```python
from data_quality.music import AudioMetadata

track = AudioMetadata(
    bpm=128,
    track_number=128,
    discogs_id=12345,
    year=2020,
    title="Some Track (Extended Mix)",
    album="08B-CM",
    initialkey="C",
    encodedby="me",
    artist="Artist",
    album_artist="Artist",
    album_artist_sort="Artist",
    subtitle="Artist - Some Track (Extended Mix) 08B-CM 128 2020",
    filename="Artist-SomeTrack-ExtendedMix",
)
```

### Run the full check suite on an extracted dict of fields

The check engine is decoupled from mutagen: your pipeline reads the file and
hands over a plain dict. This keeps the shared library free of heavy I/O
dependencies and reusable for other domains.

```python
from data_quality.music import validate_metadata

fields = {
    "bpm": 128, "track_number": 128, "title": "Track (Mix)",
    "artist": "Artist", "album": "08B-CM", "initialkey": "C",
    "encodedby": "me", "album_artist": "Artist",
    "album_artist_sort": "Artist", "subtitle": "...",
    "publisher": None, "grouping": None, "year": 2020, "discogs_id": 12345,
}

result = validate_metadata(fields, filename_stem="Artist-Track-Mix", file_size_bytes=5_000_000)

if not result.passed:
    for issue in result.issues:
        print(issue.code, issue.field, str(issue))
```

### Import shared constants

```python
from data_quality.music import BPM_MIN, BPM_MAX, CAMELOT_KEYS
```

## Versioning

Tag releases with semantic versions (`v0.1.0`, `v0.2.0`, ...). Consumers pin to a
tag so upgrading one repo never silently breaks another. Bump the `version` in
`pyproject.toml` and create a matching Git tag for each release.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
pytest
```
